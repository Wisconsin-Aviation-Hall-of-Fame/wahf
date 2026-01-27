from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView
from wagtail import urls as wagtail_urls
from wagtail.admin import urls as wagtailadmin_urls
from wagtail.contrib.sitemaps.views import sitemap
from wagtail.documents import get_document_model

from content import views as content_views
from content.views import log_document_download_and_serve
from membership import views as membership_views
from membership import views_donations as membership_views_donations
from membership import webhooks as membership_webhook_views
from membership import webhooks_donations as membership_webhook_views_donations

document_url_slug = get_document_model()._meta.app_label


urlpatterns = [
    path("django-admin/", admin.site.urls),
    # WAGTAIL ADMIN
    path("cms/", include(wagtailadmin_urls)),
    # WAGTAIL DOCUMENT VIEWER
    # path("documents/", include(wagtaildocs_urls)),
    # WAGTAIL DOCUMENT VIEWER WITH DOWNLOAD LOGGING
    path(
        "documents/<int:document_id>/<str:document_filename>",
        log_document_download_and_serve,
        name="wagtaildocs_serve",
    ),
    path("download-stats/", content_views.download_stats_view, name="download_stats"),
    path(
        "kohn/donate",
        membership_views_donations.KohnDonateRedirect.as_view(),
        name="kohn_donate_redirect",
    ),
    path(
        "kohn/donate/<int:price>",
        membership_views_donations.KohnDonateRedirect.as_view(),
        name="kohn_donate_redirect",
    ),
    path(
        "kohn/thanks",
        TemplateView.as_view(template_name="kohn/kohn-thanks.html"),
        name="kohn_thanks",
    ),
    path(
        "articles/leo-kohn-capturing-aviation/",
        TemplateView.as_view(template_name="kohn/leo-kohn-article.html"),
        name="leo_kohn_capturing_aviation",
    ),
    path(
        "articles/stories-that-soared/",
        TemplateView.as_view(template_name="articles/stories-that-soared.html"),
        name="article_stories_that_soared",
    ),
    path(
        "hall-of-fame/inductees-map/",
        content_views.inductee_map_view,
        name="inductees_map",
    ),
    path(
        "tag/<slug:slug>/",
        content_views.TagView.as_view(),
        name="tag",
    ),
    # MEMBERSHIP
    # ACCOUNT UPDATES
    path(
        "membership/", membership_views.MemberJoinView.as_view(), name="membership-join"
    ),
    path(
        "renew/<uuid:uuid>/",
        membership_views.MemberRenewPublicPaymentView.as_view(),
        name="renew-public",
    ),
    path(
        "membership/thanks/",
        membership_views.MemberJoinThanks.as_view(),
        name="membership-join-thanks",
    ),
    path("stripe-webhooks/", membership_webhook_views.process_stripe_webhook),
    path(
        "stripe-webhooks-donations/",
        membership_webhook_views_donations.process_stripe_webhook,
    ),
    # SEARCH ENGINE STUFF
    path(
        "robots.txt",
        TemplateView.as_view(template_name="robots.txt", content_type="text/plain"),
        name="robots.txt",
    ),
    path("sitemap.xml", sitemap),
    # OLD WEBSITE REDIRECTS
    path(
        "inductees/<slug:slug>.htm",
        content_views.old_website_inductee_redirect,
        name="old_inductee_redirect",
    ),
]


if settings.DEBUG and not settings.PRODUCTION:
    from django.conf.urls.static import static  # noqa
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns  # noqa

    # Serve static and media files from development server
    urlpatterns += staticfiles_urlpatterns()
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

    urlpatterns = urlpatterns + [
        path("__debug__/", include("debug_toolbar.urls")),
    ]

urlpatterns = urlpatterns + [
    # For anything not caught by a more specific rule above, hand over to
    # Wagtail's page serving mechanism. This should be the last pattern in
    # the list:
    path("", include(wagtail_urls)),
]
