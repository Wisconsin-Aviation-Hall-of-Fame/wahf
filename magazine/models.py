import uuid

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchHeadline, SearchQuery, SearchVector
from django.db import models
from django.db.models import Prefetch
from wagtail.admin.panels import FieldPanel, FieldRowPanel, MultiFieldPanel
from wagtail.fields import RichTextField
from wagtail.models import Page
from wagtail.url_routing import RouteResult

from magazine.forms import SearchForm
from wahf.mixins import OpenGraphMixin


class MagazineIssuePage(OpenGraphMixin, Page):
    date = models.DateField(
        help_text="Date of issue for this magazine release. Used for sorting issues by date.",
        db_index=True,
    )
    volume_number = models.PositiveSmallIntegerField(null=True, blank=True)
    issue_number = models.PositiveSmallIntegerField(null=True, blank=True)

    headline = models.TextField(help_text="Headline on the cover of the magazine.")
    blurb = RichTextField(
        help_text="Short snippet of text describing the content inside this issue."
    )
    cover = models.ForeignKey(
        "archives.WAHFImage",
        null=True,
        blank=False,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Cover image.",
    )
    download_pdf = models.ForeignKey(
        "wagtaildocs.Document",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    ai_data = models.JSONField(default=dict)
    ai_processed_datetime = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return self.get_admin_display_title()

    def get_graph_image_url(self):
        if self.cover:
            return self.cover.full_url
        return super().get_graph_image_url()

    def get_sitemap_urls(self, request):
        # Individual issues are paywalled and should not appear in sitemaps
        return []

    def get_admin_display_title(self):
        title = f"{self.title}"
        if self.volume_number and self.issue_number:
            title += f" - Volume {self.volume_number}, Issue {self.issue_number}"
        return title

    def route(self, request, path_components):
        if not path_components:
            # This is the base URL: /url/magazine-issue/
            return super().route(request, path_components)

        # Check if the sub-path looks like "page-2"
        if len(path_components) == 1 and path_components[0].startswith("page-"):
            # It's a valid sub-path, so we return 'self' (this page)
            return RouteResult(self)

        # If it doesn't match our pattern, 404
        return super().route(request, path_components)

    def get_context(self, request):
        context = super().get_context(request)
        # Extract the page number from the URL to use in the template if needed
        path_bits = [bit for bit in request.path.split("/") if bit]
        last_bit = path_bits[-1]
        pagenum_str = last_bit if "page-" in last_bit else "page-1"
        pagenum_chunk_str = pagenum_str.split("-", 1)[1]

        try:
            current_pagenum = int(pagenum_chunk_str)
        except ValueError:
            current_pagenum = 1

        if not self.pages.filter(page=current_pagenum).exists():
            current_pagenum = 1

        current_page = self.pages.filter(page=current_pagenum).get()

        # Override the OG data
        self.title = self.title
        if current_pagenum > 1:
            self.title += f" - Page {current_pagenum}"

        # Description
        clean_text = " ".join(current_page.text.split())
        if len(clean_text) > 150:
            clean_text = clean_text[: 150 - 3].strip() + "..."
        self.search_description = clean_text

        # Image
        self.og_image_url = current_page.get_open_graph_url

        # Canonical URLs
        self.canonical_url = self.url

        context["current_pagenum"] = current_pagenum
        return context

    content_panels = Page.content_panels + [
        MultiFieldPanel(
            [
                FieldRowPanel(
                    [
                        FieldPanel("date"),
                        FieldPanel("volume_number"),
                        FieldPanel("issue_number"),
                    ]
                ),
            ],
            heading="Issue Details",
        ),
        MultiFieldPanel(
            [
                FieldPanel("headline"),
                FieldPanel("blurb"),
            ],
            heading="Content",
        ),
        MultiFieldPanel(
            [
                FieldPanel("cover"),
                FieldPanel("download_pdf"),
            ],
            heading="Images and Files",
        ),
    ]

    parent_page_type = [
        "magazine.MagazineListPage",
    ]

    subpage_types = []


class MagazineListPage(OpenGraphMixin, Page):
    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)

        context["magazine_list"] = (
            MagazineIssuePage.objects.live()  # .child_of(self)
            .order_by("-date")
            .select_related("cover", "page_ptr")
        )

        context["form"] = SearchForm()

        return context

    def get_graph_image(self):
        image = super().get_graph_image()
        if image:
            return image
        first_magazine = (
            MagazineIssuePage.objects.child_of(self)
            .live()
            .select_related("cover")
            .order_by("-date")
            .first()
        )
        if first_magazine:
            return first_magazine.get_graph_image()
        return None

    subpage_types = [
        "magazine.MagazineIssuePage",
        "magazine.MagazineSearchPage",
    ]

    parent_page_type = [
        "content.HomePage",
    ]


class MagazinePage(models.Model):
    issue = models.ForeignKey(
        "magazine.MagazineIssuePage", on_delete=models.CASCADE, related_name="pages"
    )
    page = models.PositiveIntegerField(db_index=True)
    text = models.TextField(blank=True)
    guid = models.UUIDField(default=uuid.uuid4)

    ai_page_title = models.CharField(max_length=250, blank=True, null=True)
    ai_story_title = models.CharField(max_length=250, blank=True, null=True)
    ai_story_author = models.CharField(max_length=250, blank=True, null=True)
    ai_story_summary = models.TextField(blank=True, null=True)
    ai_data = models.JSONField(default=dict)

    def get_filename(self, prefix):
        # 123/L2-<guid>.jpg
        if prefix in ["L", "OG"]:
            return f"{self.issue.pk}/{prefix}-{self.page:0>2}.jpg"
        else:
            return f"{self.issue.pk}/{prefix}{self.page}-{self.guid}.jpg"

    def get_page_link(self):
        return f"{self.issue.url}page-{self.page}"

    @property
    def get_thumbnail_filename(self):
        return self.get_filename("T")

    @property
    def get_small_filename(self):
        return self.get_filename("S")

    @property
    def get_medium_filename(self):
        return self.get_filename("M")

    @property
    def get_original_filename(self):
        return self.get_filename("L")

    @property
    def get_open_graph_filename(self):
        return self.get_filename("OG")

    @property
    def get_base_url(self):
        return f"{settings.MEDIA_URL}magazines/"

    @property
    def get_thumbnail_url(self):
        return f"{self.get_base_url}{self.get_thumbnail_filename}"

    @property
    def get_small_url(self):
        return f"{self.get_base_url}{self.get_small_filename}"

    @property
    def get_medium_url(self):
        return f"{self.get_base_url}{self.get_medium_filename}"

    @property
    def get_original_url(self):
        return f"{self.get_base_url}{self.get_original_filename}"

    @property
    def get_open_graph_url(self):
        return f"{self.get_base_url}{self.get_open_graph_filename}"

    def __str__(self):
        return f"{self.issue} - page {self.page}"

    class Meta:
        ordering = ["page"]
        constraints = [
            models.UniqueConstraint(
                fields=["issue", "page"], name="issuepageuniquetogether"
            )
        ]
        indexes = [
            GinIndex(
                fields=["text"], name="magazine_page_text", opclasses=["gin_trgm_ops"]
            ),
            GinIndex(
                SearchVector("text", config="english"), name="mg_page_search_vector_idx"
            ),
        ]


class MagazineSearchPage(Page):
    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)

        form = SearchForm(request.GET)

        if form.is_valid():
            context["form"] = form

            query_text = form.cleaned_data["query"]
            context["query"] = query_text

            query = SearchQuery(query_text, config="english")

            # 1. Create a queryset for the children (the snippets)
            snippet_qs = MagazinePage.objects.annotate(
                headline=SearchHeadline(
                    "text",
                    query,
                    start_sel="<mark>",
                    stop_sel="</mark>",
                )
            ).filter(text__search=query)

            # 2. Query the Parents (Issues), prefetching only matching children
            # We filter the parent to only those that HAVE matching children
            search_results = (
                MagazineIssuePage.objects.filter(pages__text__search=query)
                .distinct()
                .prefetch_related(
                    Prefetch(
                        "pages",
                        queryset=snippet_qs,
                        to_attr="matching_snippets",
                    )
                )
                .order_by("-date")
            )

            context["count"] = search_results.count()
            context["page_obj"] = search_results
        else:
            context["form"] = SearchForm()

        return context

    parent_page_type = [
        "magazine.MagazineListPage",
    ]

    subpage_types = []
