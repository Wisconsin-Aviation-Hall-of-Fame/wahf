from django.db.models import Count
from django.urls import reverse
from django.utils.html import format_html
from wagtail import hooks
from wagtail.admin.menu import MenuItem
from wagtail_modeladmin.helpers import ButtonHelper
from wagtail_modeladmin.options import ModelAdmin, modeladmin_register

from .models import ShortLink


class ShortLinkButtonHelper(ButtonHelper):
    def get_buttons_for_obj(
        self, obj, exclude=None, classnames_add=None, classnames_exclude=None
    ):
        exclude = list(exclude or []) + ["delete"]
        return super().get_buttons_for_obj(
            obj,
            exclude=exclude,
            classnames_add=classnames_add,
            classnames_exclude=classnames_exclude,
        )


class ShortLinkAdmin(ModelAdmin):
    button_helper_class = ShortLinkButtonHelper
    model = ShortLink
    menu_label = "Short Links"
    menu_icon = "link"
    menu_order = 900
    base_url_path = "shortlinks"
    search_fields = ("name", "slug", "destination_url")
    list_display = (
        "name",
        "slug",
        "short_url_display",
        "pk_url_display",
        "total_clicks",
        "destination_url",
    )
    inspect_view_enabled = True
    inspect_view_fields = [
        "name",
        "slug",
        "short_url",
        "pk_url",
        "destination_url",
        "notes",
        "created_at",
        "modified_at",
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(click_count=Count("clicks"))

    def short_url_display(self, obj):
        return format_html(
            '<a href="{}" target="_blank">{}</a>', obj.short_url, obj.short_url
        )

    short_url_display.short_description = "Short URL (slug)"
    short_url_display.admin_order_field = "slug"

    def pk_url_display(self, obj):
        return format_html(
            '<a href="{}" target="_blank">{}</a>', obj.pk_url, obj.pk_url
        )

    pk_url_display.short_description = "Short URL (PK)"
    pk_url_display.admin_order_field = "pk"

    def total_clicks(self, obj):
        return obj.click_count

    total_clicks.short_description = "Total Clicks"
    total_clicks.admin_order_field = "click_count"


modeladmin_register(ShortLinkAdmin)


@hooks.register("register_admin_menu_item")
def register_link_stats_menu_item():
    return MenuItem(
        "Link Stats",
        reverse("link_stats"),
        icon_name="view",
        order=901,
    )
