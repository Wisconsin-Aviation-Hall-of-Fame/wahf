from django.contrib import admin
from django.utils.html import format_html
from wagtail.admin.panels import FieldPanel, MultiFieldPanel
from wagtail_modeladmin.options import ModelAdmin, modeladmin_register

from .models import MagazineIssuePage, MagazinePage


class MagazineIssuePageAdmin(ModelAdmin):
    """
    Provides a list view in the admin for MagazineIssuePage models.
    """

    model = MagazineIssuePage
    menu_label = "Magazine Issues"
    menu_icon = "folder-open-inverse"
    menu_order = 199  # show before Magazine Pages
    add_to_settings_menu = False
    exclude_from_explorer = False
    list_display = ("title", "date", "volume_number", "issue_number", "live")
    list_filter = ("live",)
    search_fields = ("title", "headline")
    ordering = ("-date",)


class IssueDateFilter(admin.SimpleListFilter):
    """
    A custom list filter for MagazinePageAdmin that allows filtering by issue,
    but sorts the issue choices by date (newest first) instead of alphabetically.
    """

    title = "issue"
    parameter_name = "issue_id"  # Use a specific parameter name to avoid conflicts

    def lookups(self, request, model_admin):
        """
        Returns a list of tuples. The first element in each
        tuple is the coded value for the option that will
        appear in the URL query. The second element is the
        human-readable name for the option that will appear
        in the right sidebar.
        """
        issues = MagazineIssuePage.objects.order_by("-date")
        return [(issue.pk, str(issue)) for issue in issues]

    def queryset(self, request, queryset):
        """
        Returns the filtered queryset based on the value
        provided in the query string and retrievable via
        `self.value()`.
        """
        if self.value():
            return queryset.filter(issue__pk=self.value())
        return queryset


class MagazinePageAdmin(ModelAdmin):
    """
    Admin interface for the MagazinePage model, with filtering, searching,
    and custom panel layouts.
    """

    model = MagazinePage
    menu_label = "Magazine Pages"
    menu_icon = "doc-full-inverse"
    menu_order = 200
    add_to_settings_menu = False
    exclude_from_explorer = True
    list_display = (
        "admin_thumbnail",
        "issue",
        "page",
        "story_title",
        "story_author",
        "story_article_page",
    )
    list_filter = (IssueDateFilter,)
    search_fields = ("text", "ai_page_title", "ai_story_title", "issue__title")
    ordering = ("-issue__date", "page")

    def get_queryset(self, request):
        """
        Optimize the queryset by prefetching the related issue to avoid
        N+1 query problems in the list view.
        """
        qs = super().get_queryset(request)
        return qs.select_related("issue")

    def admin_thumbnail(self, obj):
        """
        Renders a thumbnail of the magazine page for the list view.
        """
        return format_html(
            '<img src="{}" style="max-width: 100px; max-height: 100px;" />',
            obj.get_thumbnail_url,
        )

    admin_thumbnail.short_description = "Page"

    def page_image_display(self, obj):
        """
        Renders a larger preview of the magazine page for the edit view.
        """
        if obj and obj.pk:
            return format_html(
                '<img src="{}" style="max-width: 400px; height: auto;" />',
                obj.get_small_url,
            )
        return "Save the page to see a preview."

    page_image_display.short_description = "Page Preview"

    panels = [
        MultiFieldPanel(
            [
                FieldPanel("issue"),
                FieldPanel("page"),
            ],
            heading="Core Information",
        ),
        MultiFieldPanel(
            [
                FieldPanel("story_title"),
                FieldPanel("story_heading"),
                FieldPanel("story_author"),
                FieldPanel("story_article_page"),
            ],
            heading="Story Details (Frontpage/Related Articles)",
        ),
        MultiFieldPanel(
            [
                FieldPanel("text"),
            ],
            heading="Search Text / Article Text",
            classname="collapsed",
        ),
        MultiFieldPanel(
            [
                FieldPanel("ai_page_title"),
                FieldPanel("ai_story_title"),
                FieldPanel("ai_story_author"),
                FieldPanel("ai_story_summary"),
            ],
            heading="AI Generated Content",
        ),
    ]


# Register your ModelAdmin classes
modeladmin_register(MagazineIssuePageAdmin)
modeladmin_register(MagazinePageAdmin)
