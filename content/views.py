import json
from datetime import date, timedelta

from django.contrib.auth.decorators import user_passes_test
from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Q
from django.http import Http404, HttpResponsePermanentRedirect
from django.shortcuts import get_object_or_404, render
from django.views.generic import TemplateView
from taggit.models import Tag
from user_agents import parse
from wagtail.documents import get_document_model
from wagtail.documents.views.serve import serve as wagtail_serve

from content.models import (
    ArticlePage,
    DocumentDownloadLog,
    InducteeDetailPage,
    LocationTag,
    PageTag,
)

Document = get_document_model()


def superuser_required(user):
    return user.is_superuser


def old_website_inductee_redirect(request, slug):
    inductee = InducteeDetailPage.objects.filter(last_name__iexact=slug).first()

    if inductee:
        return HttpResponsePermanentRedirect(inductee.full_url)
    else:
        raise Http404("Inductee not found")


class TagView(TemplateView):
    template_name = "content/tag_page.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        article_page_content_type = ContentType.objects.get_for_model(ArticlePage)
        inductee_page_content_type = ContentType.objects.get_for_model(
            InducteeDetailPage
        )

        tag = get_object_or_404(Tag, slug=kwargs.get("slug"))

        article_page_pks = PageTag.objects.filter(
            tag=tag, content_object__content_type=article_page_content_type
        ).values_list("content_object__pk", flat=True)[0:100]
        inductee_page_pks = PageTag.objects.filter(
            tag=tag, content_object__content_type=inductee_page_content_type
        ).values_list("content_object__pk", flat=True)[0:100]

        context["articles"] = ArticlePage.objects.filter(
            pk__in=article_page_pks, live=True
        )
        context["inductees"] = InducteeDetailPage.objects.filter(
            pk__in=inductee_page_pks,
        )

        context["articles_found"] = context["articles"].exists()
        context["inductees_found"] = context["inductees"].exists()

        context["tag"] = tag

        context["page_title"] = f"Inductees and Articles - {tag.name}"

        return context


def log_document_download_and_serve(request, document_id, document_filename):
    """
    Logs the download event, including user, IP, and browser information,
    then serves the file.
    """
    document = get_object_or_404(Document, id=document_id)

    # 1. Capture and Parse User Agent
    user_agent_string = request.META.get("HTTP_USER_AGENT", "")
    user_agent = parse(user_agent_string)

    if user_agent.is_bot:
        browser_info = "Bot/Crawler"
    else:
        browser = user_agent.browser.family
        os = user_agent.os.family
        device = user_agent.device.family

        info_parts = [browser, os, device]
        browser_info = " on ".join(
            part for part in info_parts if part and part != "Other"
        )

    # 2. Capture User and IP
    user = request.user if request.user.is_authenticated else None
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    ip = (
        x_forwarded_for.split(",")[0]
        if x_forwarded_for
        else request.META.get("REMOTE_ADDR")
    )

    # 3. Log the Event
    DocumentDownloadLog.objects.create(
        document=document, user=user, ip_address=ip, browser_info=browser_info
    )

    # 4. Serve the Document (Hands off to Wagtail's original view)
    return wagtail_serve(request, document_id, document_filename)


@user_passes_test(superuser_required)
def download_stats_view(request):
    """
    Fetches all documents and annotates them with download counts for
    specific time windows (30, 90, 365 days) and total downloads.
    """

    # Calculate cutoff dates
    today = date.today()
    days_30_ago = today - timedelta(days=30)
    days_90_ago = today - timedelta(days=90)
    days_365_ago = today - timedelta(days=365)

    # Use Django's annotation with conditional filtering (Q objects)
    document_stats = Document.objects.annotate(
        # Total Downloads (same as before, using the default Count on the related field)
        total_downloads=Count("downloads"),
        # Downloads in the last 30 days
        downloads_30d=Count(
            "downloads",
            filter=Q(downloads__download_date__gte=days_30_ago),
            distinct=True,  # Use distinct to ensure accurate counting if join is complex
        ),
        # Downloads in the last 90 days
        downloads_90d=Count(
            "downloads",
            filter=Q(downloads__download_date__gte=days_90_ago),
            distinct=True,
        ),
        # Downloads in the last 365 days
        downloads_365d=Count(
            "downloads",
            filter=Q(downloads__download_date__gte=days_365_ago),
            distinct=True,
        ),
    ).order_by("-created_at", "title")

    context = {
        "document_stats": document_stats,
        "has_downloads": document_stats.filter(total_downloads__gt=0).exists(),
    }

    return render(request, "content/download_stats.html", context)


def inductee_map_view(request):
    locations_qs = LocationTag.objects.filter(
        latitude__isnull=False,
        longitude__isnull=False,
    ).prefetch_related("tagged_locations__content_object")

    inductee_data = {}
    for inductee in InducteeDetailPage.objects.select_related("page_ptr", "photo"):
        inductee_data[inductee.pk] = inductee

    data = []
    tagged_uniques = []  # prevent duplicate inductee and map points

    # { lat: 45.5, lon: -91.5, title: "name", imagePath: "photo/1.jpg", description: "desc" },
    for location in locations_qs.all():
        for tagged_location in location.tagged_locations.all():
            inductee = tagged_location.content_object
            inductee_fields = inductee_data.get(inductee.pk)
            unique = f"{location.pk}x{inductee.pk}"
            if (
                unique not in tagged_uniques
                and inductee_fields
                and inductee_fields.photo
                and inductee.name
            ):
                tagged_uniques.append(unique)

                data.append(
                    {
                        "lat": float(location.latitude),
                        "lon": float(location.longitude),
                        "location": location.location_name,
                        "name": inductee.name,
                        "tagline": inductee.tagline,
                        "link": inductee_fields.url,
                        "image": inductee_fields.photo.get_rendition(
                            "fill-100x100"
                        ).url,
                        "image_large": inductee_fields.photo.get_rendition(
                            "fill-350x350"
                        ).url,
                    }
                )

    context = {"inductee_json": json.dumps(data)}

    return render(request, "content/inductee_map.html", context)
