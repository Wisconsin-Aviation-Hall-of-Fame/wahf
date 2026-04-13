from datetime import date, timedelta

from django.contrib.auth.decorators import user_passes_test
from django.db.models import Count, Q
from django.http import HttpResponseRedirect
from django.shortcuts import render
from user_agents import parse

from .models import LinkClickLog, ShortLink
from .utils import send_broken_link_alert


def redirect_short_link(request, slug=None, pk=None):
    """
    Resolves a short link by slug or PK, logs the click, and redirects (302).
    """
    if pk is not None:
        try:
            link = ShortLink.objects.get(pk=pk)
        except ShortLink.DoesNotExist:
            send_broken_link_alert(pk, lookup_type="pk")
            return HttpResponseRedirect("https://wahf.org")
    else:
        try:
            link = ShortLink.objects.get(slug=slug)
        except ShortLink.DoesNotExist:
            send_broken_link_alert(slug, lookup_type="slug")
            return HttpResponseRedirect("https://wahf.org")

    # Parse user agent
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

    # Extract IP address (respecting X-Forwarded-For for proxied requests)
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    ip = (
        x_forwarded_for.split(",")[0]
        if x_forwarded_for
        else request.META.get("REMOTE_ADDR")
    )

    LinkClickLog.objects.create(link=link, ip_address=ip, browser_info=browser_info)

    return HttpResponseRedirect(link.destination_url)


def superuser_required(user):
    return user.is_active and user.is_superuser


@user_passes_test(superuser_required)
def link_stats_view(request):
    """
    Annotates each ShortLink with click counts for 30d / 90d / 365d / all-time.
    Superuser-only.
    """
    today = date.today()
    days_30_ago = today - timedelta(days=30)
    days_90_ago = today - timedelta(days=90)
    days_365_ago = today - timedelta(days=365)

    link_stats = ShortLink.objects.annotate(
        total_clicks=Count("clicks"),
        clicks_30d=Count(
            "clicks",
            filter=Q(clicks__click_date__gte=days_30_ago),
            distinct=True,
        ),
        clicks_90d=Count(
            "clicks",
            filter=Q(clicks__click_date__gte=days_90_ago),
            distinct=True,
        ),
        clicks_365d=Count(
            "clicks",
            filter=Q(clicks__click_date__gte=days_365_ago),
            distinct=True,
        ),
    ).order_by("name")

    context = {
        "link_stats": link_stats,
    }

    return render(request, "links/link_stats.html", context)
