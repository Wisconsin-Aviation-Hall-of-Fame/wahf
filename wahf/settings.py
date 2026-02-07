import os
from pathlib import Path

import environ
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

BASE_DIR = Path(__file__).resolve(strict=True).parent.parent
ENV_FILE = BASE_DIR / ".env"

env = environ.Env()
env.read_env(ENV_FILE)

PRODUCTION = env.bool("PRODUCTION", default=False)
DEBUG = env.bool("DJANGO_DEBUG", default=False)
SECRET_KEY = env("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

ENVIRONMENT_NAME = env("ENVIRONMENT_NAME", default="production")


SENTRY_DSN = env("SENTRY_DSN", default=None)
if not DEBUG and SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[
            DjangoIntegration(),
        ],
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for performance monitoring.
        # We recommend adjusting this value in production.
        traces_sample_rate=0.0,
        # If you wish to associate users to errors (assuming you are using
        # django.contrib.auth) you may enable sending PII data.
        send_default_pii=True,
    )


GEMINI_API_KEY = env("GEMINI_API_KEY", default=None)

EMAIL_BACKEND = env(
    "EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend"
)

DEFAULT_FROM_EMAIL = "WAHF <info@wahf.org>"
SERVER_EMAIL = "info@wahf.org"
# EMAIL_SUBJECT_PREFIX = "[CX] "

EMAIL_CONFIG = env.email_url("EMAIL_URL", default="smtp://@localhost:1025")
vars().update(EMAIL_CONFIG)

WAHF_SIGNUP_BCC = [
    DEFAULT_FROM_EMAIL,
]


INSTALLED_APPS = [
    "archives",
    "content",
    "home",
    "magazine",
    "users",
    "membership",
    "dashboard",  # used mostly to override the wagtail admin templates
    "wagtail.contrib.forms",
    "wagtail.contrib.redirects",
    "wagtail.embeds",
    "wagtail.sites",
    "wagtail.users",
    "wagtail.snippets",
    "wagtail.documents",
    "wagtail.images",
    "wagtail.search",
    "wagtail.admin",
    "wagtail_modeladmin",
    "wagtail",
    "modelcluster",
    "taggit",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sitemaps",
    "django_extensions",
    "crispy_forms",
    "crispy_bootstrap5",
    "localflavor",
    "django.contrib.postgres",
]

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "wagtail.contrib.redirects.middleware.RedirectMiddleware",
    "wahf.middleware.AdminDraftPreviewMiddleware",
]

ROOT_URLCONF = "wahf.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            os.path.join(BASE_DIR, "templates"),
        ],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "content.context_processors.environment_name",
            ],
        },
    },
]

WSGI_APPLICATION = "wahf.wsgi.application"


# Database
# https://docs.djangoproject.com/en/4.1/ref/settings/#databases
DATABASES = {"default": env.db("DATABASE_URL")}


CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://{}:6379/0".format(env("REDIS_HOST", default="127.0.0.1")),
    },
    "renditions": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://{}:6379/1".format(env("REDIS_HOST", default="127.0.0.1")),
    },
}


# Password validation
# https://docs.djangoproject.com/en/4.1/ref/settings/#auth-password-validators
AUTH_USER_MODEL = "users.User"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/4.1/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "America/Chicago"  # "UTC"

USE_I18N = True

USE_L10N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.1/howto/static-files/

STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
]

STATICFILES_DIRS = [
    os.path.join(BASE_DIR, "static"),
]

# ManifestStaticFilesStorage is recommended in production, to prevent outdated
# JavaScript / CSS assets being served from cache (e.g. after a Wagtail upgrade).
# See https://docs.djangoproject.com/en/4.1/ref/contrib/staticfiles/#manifeststaticfilesstorage
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"

STATIC_ROOT = os.path.join(BASE_DIR, "static-collected")
STATIC_URL = "/static/"

MEDIA_ROOT = os.path.join(BASE_DIR, "media")
MEDIA_URL = "/media/"

MAGAZINE_ROOT = f"{MEDIA_ROOT}/magazines"
MAGAZINE_URL = f"{MEDIA_URL}/magazines/"


# Wagtail settings

WAGTAIL_SITE_NAME = "Wisconsin Aviation Hall of Fame"

# Search
# https://docs.wagtail.org/en/stable/topics/search/backends.html
WAGTAILSEARCH_BACKENDS = {
    "default": {
        "BACKEND": "wagtail.search.backends.database",
    }
}

# Base URL to use when referring to full URLs within the Wagtail admin backend -
# e.g. in notification emails. Don't include '/admin' or a trailing slash
WAGTAILADMIN_BASE_URL = "https://www.wahf.org"

# WAGTAIL_USER_TIME_ZONES = ['America/Chicago']

# https://docs.wagtail.org/en/stable/advanced_topics/images/custom_image_model.html
WAGTAILIMAGES_IMAGE_MODEL = "archives.WAHFImage"
WAGTAILIMAGES_IMAGE_FORM_BASE = "archives.forms.WAHFImageAdminForm"

# WAGTAILIMAGES_FEATURE_DETECTION_ENABLED = True

WAGTAILIMAGES_MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB

WAGTAILADMIN_RECENT_EDITS_LIMIT = 5

WAGTAILADMIN_COMMENTS_ENABLED = False
WAGTAIL_ALLOW_UNICODE_SLUGS = False
WAGTAILEMBEDS_RESPONSIVE_HTML = True

TAGGIT_CASE_INSENSITIVE = True

WAGTAIL_FRONTEND_LOGIN_TEMPLATE = "auth/login.html"
WAGTAIL_FRONTEND_LOGIN_URL = "/accounts/login/"

CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

# https://django-phonenumber-field.readthedocs.io/en/latest/reference.html#settings
PHONENUMBER_DEFAULT_REGION = "US"
PHONENUMBER_DB_FORMAT = "NATIONAL"
PHONENUMBER_DEFAULT_FORMAT = "NATIONAL"

if DEBUG and not PRODUCTION:
    INSTALLED_APPS += ["debug_toolbar"]
    MIDDLEWARE = [
        "debug_toolbar.middleware.DebugToolbarMiddleware",
    ] + MIDDLEWARE

    import socket  # only if you haven't already imported this

    hostname, _, ips = socket.gethostbyname_ex(socket.gethostname())
    INTERNAL_IPS = [ip[: ip.rfind(".")] + ".1" for ip in ips] + [
        "127.0.0.1",
        "10.0.2.2",
    ]

# Stripe/djstripe
STRIPE_LIVE_SECRET_KEY = env("STRIPE_LIVE_SECRET_KEY", default=None)
STRIPE_LIVE_PUBLIC_KEY = env("STRIPE_LIVE_PUBLIC_KEY", default=None)

STRIPE_TEST_SECRET_KEY = env("STRIPE_TEST_SECRET_KEY", default=None)
STRIPE_TEST_PUBLIC_KEY = env("STRIPE_TEST_PUBLIC_KEY", default=None)

# Stripe Donations account
STRIPE_LIVE_SECRET_KEY_DONATIONS = env("STRIPE_LIVE_SECRET_KEY_DONATIONS", default=None)
STRIPE_LIVE_PUBLIC_KEY_DONATIONS = env("STRIPE_LIVE_PUBLIC_KEY_DONATIONS", default=None)

STRIPE_TEST_SECRET_KEY_DONATIONS = env("STRIPE_TEST_SECRET_KEY_DONATIONS", default=None)
STRIPE_TEST_PUBLIC_KEY_DONATIONS = env("STRIPE_TEST_PUBLIC_KEY_DONATIONS", default=None)


STRIPE_LIVE_MODE = env.bool(
    "STRIPE_LIVE_MODE", default=False
)  # Change to True in production

# USPS Address Validation
USPS_USERNAME = env("USPS_USERNAME", default=None)
USPS_PASSWORD = env("USPS_PASSWORD", default=None)


SESSION_COOKIE_SECURE = DEBUG
CSRF_COOKIE_SECURE = False

USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

CSRF_TRUSTED_ORIGINS = [
    "https://www.wahf.org",
    "https://wahf.org",
    "http://localhost:8000",
    "http://localhost:9006",
]

# CSRF_COOKIE_DOMAIN = [
#    "*.wahf.org",
#    "localhost",
#    "127.0.0.1",
# ]
