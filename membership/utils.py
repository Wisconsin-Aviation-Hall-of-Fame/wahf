from django.conf import settings
from django.core import mail
from django.template import Context, Template
from django.template.loader import render_to_string
from django.utils.html import strip_tags


def get_stripe_public_key():
    if settings.STRIPE_LIVE_MODE:
        if not settings.STRIPE_LIVE_PUBLIC_KEY:
            raise Exception("STRIPE_LIVE_PUBLIC_KEY not set")
        return settings.STRIPE_LIVE_PUBLIC_KEY

    if not settings.STRIPE_TEST_PUBLIC_KEY:
        raise Exception("STRIPE_TEST_PUBLIC_KEY not set")
    return settings.STRIPE_TEST_PUBLIC_KEY


def get_stripe_secret_key():
    if settings.STRIPE_LIVE_MODE:
        if not settings.STRIPE_LIVE_SECRET_KEY:
            raise Exception("STRIPE_LIVE_SECRET_KEY not set")
        return settings.STRIPE_LIVE_SECRET_KEY

    if not settings.STRIPE_TEST_SECRET_KEY:
        raise Exception("STRIPE_TEST_SECRET_KEY not set")
    return settings.STRIPE_TEST_SECRET_KEY


def get_stripe_public_key_donations():
    if settings.STRIPE_LIVE_MODE:
        if not settings.STRIPE_LIVE_PUBLIC_KEY_DONATIONS:
            raise Exception("STRIPE_LIVE_PUBLIC_KEY_DONATIONS not set")
        return settings.STRIPE_LIVE_PUBLIC_KEY_DONATIONS

    if not settings.STRIPE_TEST_PUBLIC_KEY_DONATIONS:
        raise Exception("STRIPE_TEST_PUBLIC_KEY_DONATIONS not set")
    return settings.STRIPE_TEST_PUBLIC_KEY_DONATIONS


def get_stripe_secret_key_donations():
    if settings.STRIPE_LIVE_MODE:
        if not settings.STRIPE_LIVE_SECRET_KEY_DONATIONS:
            raise Exception("STRIPE_LIVE_SECRET_KEY_DONATIONS not set")
        return settings.STRIPE_LIVE_SECRET_KEY_DONATIONS

    if not settings.STRIPE_TEST_SECRET_KEY_DONATIONS:
        raise Exception("STRIPE_TEST_SECRET_KEY_DONATIONS not set")
    return settings.STRIPE_TEST_SECRET_KEY_DONATIONS


def send_membership_error_email(subject, error):
    alert_body = render_to_string("emails/membership_error.html", {"error": error})

    send_email(
        to=["membership@wahf.org", "dan@wahf.org"],
        subject=subject,
        body=None,
        body_html=alert_body,
    )


def send_email(
    to,
    subject,
    body,
    context={},
    body_html=None,
    from_email=settings.DEFAULT_FROM_EMAIL,
):
    if type(to) is str:
        to = [to]

    if not body_html:
        body_template = Template(body)
        body_context = Context(context)
        body_html = body_template.render(body_context)

    html_message = render_to_string(
        "emails/base.html",
        {"body": body_html, "environment_name": settings.ENVIRONMENT_NAME},
    )
    plain_message = strip_tags(html_message)

    mail.send_mail(
        subject,
        plain_message,
        from_email,
        to,
        html_message=html_message,
        fail_silently=False,
    )
