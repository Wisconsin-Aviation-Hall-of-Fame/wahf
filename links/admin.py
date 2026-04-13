from django.contrib import admin
from django.db.models import Count
from django.utils.html import format_html

from .models import LinkClickLog, ShortLink


@admin.register(ShortLink)
class ShortLinkAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "slug",
        "short_url",
        "pk_url_display",
        "destination_url",
        "total_clicks",
        "created_at",
    )
    search_fields = ("name", "slug", "destination_url")
    readonly_fields = (
        "created_at",
        "modified_at",
        "short_url",
        "pk_url_display",
        "total_clicks",
    )
    prepopulated_fields = {"slug": ("name",)}
    fields = (
        "name",
        "slug",
        "short_url",
        "pk_url_display",
        "destination_url",
        "notes",
        "total_clicks",
        "created_at",
        "modified_at",
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(click_count=Count("clicks"))

    @admin.display(description="Short URL")
    def short_url(self, obj):
        return format_html(
            '<a href="{}" target="_blank">{}</a>', obj.short_url, obj.short_url
        )

    @admin.display(description="PK URL")
    def pk_url_display(self, obj):
        return format_html(
            '<a href="{}" target="_blank">{}</a>', obj.pk_url, obj.pk_url
        )

    @admin.display(description="Total Clicks", ordering="click_count")
    def total_clicks(self, obj):
        return obj.click_count


@admin.register(LinkClickLog)
class LinkClickLogAdmin(admin.ModelAdmin):
    list_display = ("link", "click_date", "ip_address", "browser_info")
    list_filter = ("link",)
    readonly_fields = ("link", "click_date", "ip_address", "browser_info")
    date_hierarchy = "click_date"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
