import datetime

from django.conf import settings
from django.db import models
from django.db.models import F
from django.utils.text import slugify
from django_extensions.db.fields import AutoSlugField
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from modelcluster.tags import ClusterTaggableManager
from taggit.models import TagBase, TaggedItemBase
from wagtail import blocks
from wagtail.admin.panels import (
    FieldPanel,
    InlinePanel,
    MultiFieldPanel,
    ObjectList,
    PageChooserPanel,
    TabbedInterface,
)
from wagtail.documents import get_document_model
from wagtail.fields import RichTextField, StreamField
from wagtail.images.blocks import ImageChooserBlock
from wagtail.models import Orderable, Page
from wagtail.snippets.models import register_snippet

from content.blocks import BlockQuoteBlock, EditorsNoteBlock
from wahf.mixins import OpenGraphMixin

Document = get_document_model()


class PageTag(TaggedItemBase):
    content_object = ParentalKey(
        "wagtailcore.Page", on_delete=models.CASCADE, related_name="tagged_pages"
    )


class LocationTag(TagBase):
    location_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="User-friendly name for the location (e.g., 'Eiffel Tower')",
    )
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="WGS 84 Latitude (-90 to +90)",
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="WGS 84 Longitude (-180 to +180)",
    )

    def get_display_name(self):
        if self.location_name:
            return self.location_name
        return self.name

    class Meta:
        verbose_name = "Location Tag"
        verbose_name_plural = "Location Tags"


class TaggedLocation(TaggedItemBase):
    tag = models.ForeignKey(
        LocationTag, on_delete=models.CASCADE, related_name="tagged_locations"
    )

    content_object = ParentalKey(
        "content.InducteeDetailPage",
        on_delete=models.CASCADE,
        related_name="location_tag_page",
    )

    class Meta:
        # Prevents creation of duplicate tag relations for the same page/tag pair
        unique_together = ("tag", "content_object")


class ArticleAuthor(models.Model):
    name = models.CharField(max_length=255)
    about_blurb = RichTextField(
        help_text="A short blurb about this author, to be included at the end of articles that they author.",
        blank=True,
    )
    contact_email = models.EmailField(blank=True)
    image = models.ForeignKey(
        "archives.WAHFImage",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Author photo, headshot, or whatever you want to put below their articles.",
    )

    def __str__(self):
        return self.name


class ArticleListPage(OpenGraphMixin, Page):
    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)

        qs = (
            ArticlePage.objects.child_of(self)
            .select_related("author")
            .order_by("-website_publish_date", "-pk")
        )
        if not request.user.is_authenticated:
            qs = qs.live()

        context["articles_list"] = qs.all()

        return context

    subpage_types = [
        "content.ArticlePage",
    ]

    parent_page_type = [
        "home.HomePage",
    ]


class KohnProjectPage(Page):
    funding_percent_raised = models.FloatField(null=True, blank=True)
    fundraising_status = RichTextField(
        help_text="The description of the fundraising status of our project.",
        blank=True,
    )

    show_donors_list = models.BooleanField(default=False)

    business_donors = RichTextField(
        help_text="A list of businesses that have donated.",
        blank=True,
    )

    individual_donors = RichTextField(
        help_text="A list of individuals that have donated.",
        blank=True,
    )

    silent_auction_donors = RichTextField(
        help_text="A list of individuals that donated items to the silent auction.",
        blank=True,
    )

    special_donors = RichTextField(
        help_text="A list of special donors to be featured at the top of the page.",
        blank=True,
    )

    content_panels = Page.content_panels + [
        MultiFieldPanel(
            [
                FieldPanel("funding_percent_raised"),
                FieldPanel("fundraising_status"),
            ],
            heading="Funding Status",
        ),
        MultiFieldPanel(
            [
                FieldPanel("show_donors_list"),
                FieldPanel("special_donors"),
                FieldPanel("business_donors"),
                FieldPanel("individual_donors"),
                FieldPanel("silent_auction_donors"),
            ],
            heading="Donors",
        ),
    ]

    parent_page_type = [
        "home.HomePage",
    ]


class RelatedArticle(Orderable):
    page = ParentalKey("content.ArticlePage", related_name="related_articles")

    link_to = models.ForeignKey(
        "wagtailcore.Page",
        null=True,
        blank=False,
        on_delete=models.CASCADE,
        related_name="+",
    )

    panels = [
        FieldPanel("link_to"),
    ]


class ArticlePage(OpenGraphMixin, Page):
    subtitle = models.TextField(
        null=True, blank=True, help_text="Text that appears under the title. Optional."
    )

    author = models.ForeignKey(
        "content.ArticleAuthor", null=True, blank=True, on_delete=models.PROTECT
    )
    date = models.DateField(
        null=True,
        blank=True,
        help_text="The date this article was published somewhere. Only displayed on the website.",
    )
    website_publish_date = models.DateField(
        null=True,
        blank=True,
        default=datetime.date.today,
        db_index=True,
        help_text="This date is used for sorting the articles on the website. It is not displayed on the website.",
    )

    image = models.ForeignKey(
        "archives.WAHFImage",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Thumbnail and social media preview image for this gallery.",
    )
    short_description = models.TextField(
        help_text="A short description of this gallery, used for gallery list page and social media preview."
    )
    top_badge = models.TextField(
        help_text="A short tag placed over the image. Example 'WAHF: 40 YEARS, 40 STORIES",
        blank=True,
        null=True,
    )

    tags = ClusterTaggableManager(through="content.PageTag", blank=True)

    body = StreamField(
        [
            ("heading", blocks.CharBlock(form_classname="title")),
            (
                "paragraph",
                blocks.RichTextBlock(
                    # features=["bold", "italic", "link", "text-highlight"]
                ),
            ),
            ("image", ImageChooserBlock()),
            ("blockquote", BlockQuoteBlock()),
            ("editorsnote", EditorsNoteBlock()),
        ],
        use_json_field=True,
    )

    page_css = models.TextField(
        "CSS/Style",
        blank=True,
        help_text="Leave blank if you do not have any custom CSS. This is custom styling for this article.",
    )

    # Wagtail CMS panel configs w/ custom tabs at top
    detail_panels = Page.content_panels + [
        FieldPanel("subtitle"),
        FieldPanel("author"),
        FieldPanel("date"),
        FieldPanel("website_publish_date"),
        FieldPanel("image"),
        FieldPanel("short_description"),
        FieldPanel("top_badge"),
        FieldPanel("tags"),
    ]

    content_panels = [
        FieldPanel("body"),
    ]

    related_content_panels = [
        InlinePanel("related_articles", label="Related Articles", max_num=4),
    ]

    style_panels = [
        FieldPanel("page_css"),
    ]

    edit_handler = TabbedInterface(
        [
            ObjectList(detail_panels, heading="Details"),
            ObjectList(content_panels, heading="Content"),
            ObjectList(related_content_panels, heading="Related Articles"),
            ObjectList(style_panels, heading="Style"),
            ObjectList(OpenGraphMixin.promote_panels, heading="Promote"),
            # ObjectList(Page.settings_panels, heading='Settings', classname="settings"),
        ]
    )

    parent_page_type = [
        "home.ArticleListPage",
    ]

    class Meta:
        ordering = ["-website_publish_date", "-pk"]

    def get_graph_image(self):
        image = super().get_graph_image()
        if image:
            return image
        if self.image:
            return self.image
        return None


class FourtyYearsStory(models.Model):
    article_number = models.PositiveSmallIntegerField(unique=True)
    article = models.OneToOneField(
        "content.ArticlePage", related_name="fourty_article", on_delete=models.CASCADE
    )
    short_title = models.CharField(
        max_length=250, help_text="Shorter version of the title for the 40th page."
    )
    image = models.ForeignKey(
        "archives.WAHFImage",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Article Image",
    )

    class Meta:
        ordering = ["-article_number"]
        verbose_name_plural = "40/40 Stories"

    def __str__(self):
        return f"#{self.article_number} - {self.short_title}"


class FourtyYearsFourtyStoriesListPage(OpenGraphMixin, Page):
    body = StreamField(
        [
            ("heading", blocks.CharBlock(form_classname="title")),
            ("paragraph", blocks.RichTextBlock()),
            ("image", ImageChooserBlock()),
        ],
        use_json_field=True,
        blank=True,
    )

    content_panels = Page.content_panels + [
        MultiFieldPanel(
            [
                FieldPanel("body"),
            ],
            heading="Page Contents",
        ),
    ]

    parent_page_type = [
        "home.HomePage",
    ]

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)

        qs = FourtyYearsStory.objects.select_related("article", "image")

        # Only show live stories to public
        if not request.user.is_authenticated:
            qs = qs.filter(article__live=True)

        context["articles_list"] = qs.all()

        return context


class ScholarshipPage(OpenGraphMixin, Page):
    body = StreamField(
        [
            ("heading", blocks.CharBlock(form_classname="title")),
            ("paragraph", blocks.RichTextBlock()),
            ("image", ImageChooserBlock()),
        ],
        use_json_field=True,
        blank=True,
    )

    content_panels = Page.content_panels + [
        MultiFieldPanel(
            [
                FieldPanel("body"),
            ],
            heading="Page Content",
        ),
    ]

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)

        context["scholarship_list"] = ScholarshipRecipient.objects.select_related(
            "image"
        ).all()

        context["top_images"] = []
        context["bottom_images"] = []

        count = 0
        for recipient in context["scholarship_list"]:
            if recipient.image:
                if count % 2 == 0:
                    if recipient.image not in context["top_images"]:
                        context["top_images"].append(recipient.image)
                        count += 1
                else:
                    if recipient.image not in context["bottom_images"]:
                        context["bottom_images"].append(recipient.image)
                        count += 1

        return context

    parent_page_type = [
        "home.ArticleListPage",
    ]


class ScholarshipRecipient(models.Model):
    year = models.PositiveSmallIntegerField(help_text="example: 2023")
    scholarship_name = models.CharField(
        max_length=250, help_text="example: 'Test Person Scholarship'"
    )
    recipient_name = models.CharField(max_length=150)

    blurb = RichTextField(
        help_text="A longer description of this gallery. Displayed on the gallery detail page."
    )

    image = models.ForeignKey(
        "archives.WAHFImage",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Scholarship recipient photo.",
    )

    def __str__(self):
        return f"{self.year} {self.scholarship_name} - {self.recipient_name}"

    class Meta:
        ordering = ["-year", "scholarship_name"]


class InducteeListPage(OpenGraphMixin, Page):
    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)

        inductee_qs = (
            InducteeDetailPage.objects.child_of(self).select_related("photo").live()
        )

        order_by = ["last_name", "first_name"]

        if "year" in request.GET:
            order_by.insert(0, F("inducted_date").desc(nulls_last=True))
            context["view_type"] = "year"
        else:
            context["view_type"] = "name"

        context["inductee_list"] = inductee_qs.order_by(*order_by)

        return context

    subpage_types = [
        "content.InducteeDetailPage",
        "content.FreeformPage",
    ]

    parent_page_type = [
        "home.HomePage",
    ]


class InducteeDetailPage(OpenGraphMixin, Page):
    first_name = models.CharField(
        max_length=100,
        db_index=True,
        null=True,
        blank=True,
        help_text="Used for sorting on the Inductee List page.",
    )

    last_name = models.CharField(
        max_length=100,
        db_index=True,
        null=True,
        blank=True,
        help_text="Used for sorting on the Inductee List page.",
    )

    name = models.CharField(
        "Display Name",
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
        help_text="First and Last Name, or a custom name if they are multiple people.",
    )

    tagline = models.TextField(
        blank=True,
        help_text="Short description of the Inductee. This is displayed on the Inductee List page.",
    )

    body = StreamField(
        [
            ("heading", blocks.CharBlock(form_classname="title")),
            ("paragraph", blocks.RichTextBlock()),
            ("image", ImageChooserBlock()),
        ],
        use_json_field=True,
        blank=True,
    )

    photo = models.ForeignKey(
        "archives.WAHFImage",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Main image for the inductee list and primary photo for their page.",
        db_index=True,
    )

    gallery = StreamField(
        [
            ("image", ImageChooserBlock()),
        ],
        use_json_field=True,
        default=[],
        blank=True,
    )

    inducted_date = models.DateField(null=True, blank=True, db_index=True)
    born_date = models.DateField(null=True, blank=True)
    died_date = models.DateField(null=True, blank=True)
    born_year = models.PositiveSmallIntegerField(null=True, blank=True)
    died_year = models.PositiveSmallIntegerField(null=True, blank=True)

    tags = ClusterTaggableManager("Tags", through="content.PageTag", blank=True)

    locations = ClusterTaggableManager(
        through=TaggedLocation,
        manager=LocationTag,
        verbose_name="Locations",
        blank=True,
    )

    # Wagtail Panels
    detail_panels = Page.content_panels + [
        FieldPanel("first_name"),
        FieldPanel("last_name"),
        FieldPanel("name"),
        FieldPanel("tagline"),
        FieldPanel("tags"),
        FieldPanel("body"),
        MultiFieldPanel(
            [
                FieldPanel("inducted_date"),
                FieldPanel("born_date"),
                FieldPanel("died_date"),
                FieldPanel("locations"),
            ],
            heading="Dates",
        ),
    ]

    photo_gallery_panels = [
        MultiFieldPanel(
            [
                FieldPanel(
                    "photo",
                ),
                FieldPanel("gallery"),
            ],
            heading="Photos",
        ),
    ]

    link_panels = [InlinePanel("sections", label="Link Sections")]

    edit_handler = TabbedInterface(
        [
            ObjectList(detail_panels, heading="Inductee Details"),
            ObjectList(photo_gallery_panels, heading="Photo Gallery"),
            ObjectList(link_panels, heading="Outbound Links"),
            ObjectList(OpenGraphMixin.promote_panels, heading="Promote"),
        ]
    )

    parent_page_type = [
        "content.InducteeListPage",
    ]

    class Meta:
        ordering = ["last_name", "first_name", "name"]

    def get_graph_image(self):
        photo = super().get_graph_image()
        if photo:
            return photo
        elif self.photo:
            return self.photo
        return None

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)

        sections = self.sections.prefetch_related("links").all()
        context["link_sections"] = sections

        return context


@register_snippet
class InducteePhotoPlaceholder(models.Model):
    image = models.ForeignKey(
        "archives.WAHFImage",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Placeholder image for inductees that are missing an image.",
    )

    panels = [
        FieldPanel("image"),
    ]

    class Meta:
        verbose_name_plural = "Inductees List - Missing Photo Placeholder Image"

    def __str__(self):
        return "Inductee Missing Photo Placeholder Image"


class InducteeOutboundLink(Orderable):
    section = ParentalKey("InducteeOutboundLinkSection", related_name="links")
    url = models.URLField()
    domain = models.CharField(max_length=70, null=True, blank=True)

    title = models.CharField(max_length=250, blank=True, null=True)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="link-images/", blank=True, null=True)

    created_datetime = models.DateTimeField(auto_now_add=True)
    downloaded_datetime = models.DateTimeField(null=True, blank=True, db_index=True)

    panels = [
        FieldPanel("url"),
    ]

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["section", "url"], name="unique_page_url_link"
            )
        ]
        ordering = ["sort_order"]

    def save(self, *args, **kwargs):
        url_pre_save = None
        if self.pk:
            link_obj_pre_save = InducteeOutboundLink.objects.filter(pk=self.pk).first()
            if link_obj_pre_save:
                url_pre_save = link_obj_pre_save.url

        if self.url and url_pre_save and self.url != url_pre_save:
            self.domain = ""
            self.title = ""
            self.description = ""
            self.image = None  # deleted ones could be cleaned up?
            self.downloaded_datetime = None

        super().save(*args, **kwargs)

    def __str__(self):
        if self.title:
            return f"{self.title} - {self.url}"
        return self.url


class InducteeOutboundLinkSection(Orderable, ClusterableModel):
    page = ParentalKey("InducteeDetailPage", related_name="sections")
    title = models.CharField(max_length=250, help_text="Section Heading", blank=True)

    panels = [FieldPanel("title"), InlinePanel("links", label="Link", min_num=1)]

    class Meta:
        ordering = ["sort_order"]


class FreeformPage(OpenGraphMixin, Page):
    body = StreamField(
        [
            ("heading", blocks.CharBlock(form_classname="title")),
            ("paragraph", blocks.RichTextBlock()),
            ("image", ImageChooserBlock()),
        ],
        use_json_field=True,
    )

    content_panels = Page.content_panels + [
        FieldPanel("body"),
    ]


# Menu System
# https://learnwagtail.com/tutorials/how-to-create-a-custom-wagtail-menu-system/
class MenuItem(Orderable):
    menu_label = models.CharField(blank=True, null=True, max_length=50)

    menu_icon = models.CharField(max_length=50, blank=True, null=True)

    link_url = models.CharField(max_length=500, blank=True)

    link_page = models.ForeignKey(
        "wagtailcore.Page",
        null=True,
        blank=True,
        related_name="+",
        on_delete=models.CASCADE,
    )

    page = ParentalKey("Menu", related_name="menu_items")

    panels = [
        FieldPanel("menu_label"),
        FieldPanel("menu_icon"),
        FieldPanel("link_url"),
        PageChooserPanel("link_page"),
    ]

    @property
    def link(self):
        if self.link_page:
            return self.link_page.url
        elif self.link_url:
            return self.link_url
        return "#"

    @property
    def title(self):
        if self.link_page and not self.menu_label:
            return self.link_page.title
        elif self.menu_label:
            return self.menu_label
        return "Missing Title"


@register_snippet
class Menu(ClusterableModel):
    """The main menu clusterable model."""

    title = models.CharField(max_length=100)
    slug = AutoSlugField(populate_from="title", editable=True)
    # slug = models.SlugField()

    panels = [
        MultiFieldPanel(
            [
                FieldPanel("title"),
                FieldPanel("slug"),
            ],
            heading="Menu",
        ),
        InlinePanel("menu_items", label="Menu Item"),
    ]

    def __str__(self):
        return self.title


class DocumentDownloadLog(models.Model):
    """
    Tracks individual download events for Wagtail documents,
    including browser information.
    """

    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="downloads",
        verbose_name="Document",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="User",
    )
    download_date = models.DateTimeField(
        auto_now_add=True, verbose_name="Download Date"
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    browser_info = models.CharField(
        max_length=255, blank=True, verbose_name="Browser/OS"
    )

    def __str__(self):
        return f"{self.document.title} downloaded by {self.user or 'Anonymous'} on {self.download_date.strftime('%Y-%m-%d')}"

    class Meta:
        verbose_name = "Document Download Log"
        verbose_name_plural = "Document Download Logs"


@register_snippet
class SectionalMap(models.Model):
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    year = models.PositiveSmallIntegerField(db_index=True)

    attribution = models.TextField(blank=True)
    attribution_link = models.TextField(blank=True)

    tiles_url = models.CharField(max_length=255, blank=True, null=True)
    min_zoom = models.PositiveSmallIntegerField(default=1)
    max_zoom = models.PositiveSmallIntegerField(default=12)

    panels = [
        FieldPanel("title"),
        FieldPanel("slug"),
        FieldPanel("year"),
        FieldPanel("attribution"),
        FieldPanel("attribution_link"),
        FieldPanel("tiles_url"),
        FieldPanel("min_zoom"),
        FieldPanel("max_zoom"),
    ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)

    class Meta:
        verbose_name_plural = "Sectional Map Tile Configs"

    def __str__(self):
        return self.title
