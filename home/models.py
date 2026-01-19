from django.db import models
from modelcluster.fields import ParentalKey
from wagtail.admin.panels import FieldPanel, InlinePanel
from wagtail.fields import RichTextField
from wagtail.models import Orderable, Page

from content.models import InducteeDetailPage
from wahf.mixins import OpenGraphMixin


class HomePageCard(models.Model):
    heading = models.CharField(max_length=255, blank=True)
    badge_text = models.CharField(max_length=255, blank=True)
    blurb = RichTextField()
    date = models.DateField(blank=True, null=True)
    image = models.ForeignKey(
        "archives.WAHFImage",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    link_page = models.ForeignKey(
        "wagtailcore.Page", on_delete=models.CASCADE, null=True, blank=True
    )
    link_text = models.CharField(max_length=255, blank=True)

    panels = [
        FieldPanel("heading"),
        FieldPanel("badge_text"),
        FieldPanel("blurb"),
        FieldPanel("date"),
        FieldPanel("image"),
        FieldPanel("link_page"),
        FieldPanel("link_text"),
    ]

    class Meta:
        abstract = True


class HomePageCardItem(Orderable, HomePageCard):
    page = ParentalKey(
        "home.HomePage", on_delete=models.CASCADE, related_name="home_page_cards"
    )


class HomePage(OpenGraphMixin, Page):
    content_panels = Page.content_panels + [
        InlinePanel(
            "home_page_cards", heading="Home Page Cards", label="Home Page Card"
        ),
    ]

    parent_page_type = [
        "wagtailcore.Page",
    ]

    subpage_types = [
        "content.InducteeListPage",
        "magazine.MagazineListPage",
        "content.FreeformPage",
        "content.ArticleListPage",
        "content.ScholarshipPage",
        "content.KohnProjectPage",
        "content.FourtyYearsFourtyStoriesListPage",
        "archives.CollectionList",
        "membership.BanquetRSVPPage",
        "membership.BanquetRSVPThanksPage",
    ]

    def get_graph_image(self):
        image = super().get_graph_image()
        if image:
            return image
        return None

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)

        context["inductee_bar"] = (
            InducteeDetailPage.objects.filter(photo__isnull=False)
            .select_related("photo")
            .order_by("?")[0:36]
        )

        return context
