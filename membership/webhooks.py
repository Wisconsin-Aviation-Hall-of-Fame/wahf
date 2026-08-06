import json
from datetime import datetime

import pytz
import stripe
from django.core.mail import EmailMultiAlternatives
from django.db.models import Q
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from html2text import html2text

from membership.models import (
    BanquetPayment,
    Member,
    MembershipEmailTemplateSnippet,
    MembershipLevel,
    MemberSignupLog,
)
from membership.utils import (
    get_stripe_secret_key,
    send_email,
    send_membership_error_email,
)

stripe.api_key = get_stripe_secret_key()


@csrf_exempt
def process_stripe_webhook(request):
    if request.method != "POST":
        return HttpResponse("Not POST", status=400)

    payload = request.body
    event = None

    try:
        event = stripe.Event.construct_from(json.loads(payload), stripe.api_key)
    except ValueError:
        return HttpResponse(status=400)

    if event.type == "checkout.session.completed":
        session = stripe.checkout.Session.retrieve(
            event.data.object["id"],
            expand=["line_items", "subscription"],
        )

        action = session.metadata.get("action", None)
        success_url = event.data.object.get("success_url", None)

        if action == "signup":
            process_membership_signup(event.data.object, session)
        # elif action == "renewal":
        #    # this is currently unused and does nothing
        #    process_membership_renewal(event.data.object, session)
        elif action == "donation":
            process_donation_payment(event.data.object, session)
        elif success_url and "rsvp" in success_url:  # action == "banquet":
            process_banquet_tickets(event.data.object, session)
        # Kohn used to be on the main membership account, it is now separated into its
        # own stripe account, but still exists here in posterity
        elif action == "kohn":
            process_kohn_donation(event.data.object, session)

    elif event.type in [
        "customer.subscription.created",
        "customer.subscription.updated",
    ]:
        # Update the subscription dates and status
        # This one might fire before the subscription is there, so we can delay it and tell stripe to come back
        return process_subscription_create_update(event.data.object)

    elif event.type == "customer.subscription.deleted":
        # Update the status of the subscription
        process_subscription_delete(event.data.object)

    return HttpResponse(status=200)


def process_banquet_tickets(obj, session):
    # Total amount paid
    amount_total = session["amount_total"] / 100.0

    # Name
    # Phone
    # Zip Code
    name = session["customer_details"]["name"]
    phone = session["customer_details"]["phone"].replace("+1", "")
    email = session["customer_details"]["email"]

    # Item they purchased
    item = session["line_items"]["data"][0]["description"]
    quantity = session["line_items"]["data"][0]["quantity"]

    stripe_id = session["id"]

    attendee_names = "(no names supplied at checkout)"
    docent_tour = "Was not selected during checkout"

    paid_date = datetime.utcfromtimestamp(session["created"]).replace(tzinfo=pytz.utc)

    item_type = "ticket"
    if "table" in item.lower():
        item_type = "table"

    if quantity > 1:
        item_type = f"{item_type}s"

    if "table" in item.lower():
        item_type = f"{item_type} of 8 attendees"

    for cf in session["custom_fields"]:
        if cf["key"] == "attendeenames":
            attendee_names = (
                cf["text"]["value"] if cf["text"]["value"] else attendee_names
            )
        elif cf["key"] == "eaamuseumdocentguidedtour":
            docent_tour = (
                "Yes, will attend the docent tour."
                if cf["dropdown"]["value"] and cf["dropdown"]["value"].startswith("yes")
                else "No, we will not attend the docent tour."
            )

    confirmation_body = render_to_string(
        "emails/banquet_confirmation.html",
        {
            "amount_total": amount_total,
            "name": name,
            "email": email,
            "phone": phone,
            "item": item,
            "item_type": item_type,
            "quantity": quantity,
            "attendee_names": attendee_names,
            "docent_tour": docent_tour,
            "paid_date": paid_date,
            "stripe_id": stripe_id,
        },
    )

    msg = EmailMultiAlternatives(
        f"WAHF 2026 Investiture Dinner and Ceremony - RSVP Confirmation - {name}",
        html2text(confirmation_body),
        "Rose Dorcey <rose@wahf.org>",
        [email],
        cc=["dan@wahf.org", "rose@wahf.org", "president@wahf.org"],
    )
    msg.attach_alternative(confirmation_body, "text/html")
    msg.send()

    BanquetPayment.objects.create(
        stripe_id=stripe_id,
        amount_total=amount_total,
        name=name,
        email=email,
        phone=phone,
        item=item,
        quantity=quantity,
        attendee_names=attendee_names,
        docent_tour=docent_tour,
        signup_date=paid_date,
    )

    return


def process_donation_payment(obj, session):
    # Send them the donation receipt
    name = session["customer_details"]["name"]
    if name.lower() == name:
        name = name.title()

    line2 = session["customer_details"]["address"]["line2"] or ""
    line1 = session["customer_details"]["address"]["line1"]
    city = session["customer_details"]["address"]["city"]
    state = session["customer_details"]["address"]["state"]
    zip = session["customer_details"]["address"]["postal_code"]

    email = obj["customer_details"]["email"].lower()

    donation_amount = obj["amount_total"] / 100.0
    donation_amount_str = f"{donation_amount:.2f}"

    date_str = timezone.now().strftime("%B %-d, %Y")

    replacements = [
        ("%DATE%", date_str),
        ("%EMAIL%", email),
        ("%NAME%", name),
        ("%LINE1%", line1),
        ("%LINE2%", line2),
        ("%CITY%", city),
        ("%STATE%", state),
        ("%ZIP%", zip),
        ("%AMOUNT%", donation_amount_str),
    ]

    snippet = MembershipEmailTemplateSnippet.objects.get(slug="donation_thanks")
    snippet_body = snippet.body

    for replacement_key, replacement_value in replacements:
        snippet_body = snippet_body.replace(replacement_key, replacement_value)

    send_email(
        to=email,
        subject=snippet.subject,
        body=snippet_body,
        context={},
    )

    return


def process_membership_signup(obj, session):
    MemberSignupLog.objects.create(data=obj)

    #################################
    # Process signup
    email = obj["customer_details"]["email"].lower()

    line_item_ids = []
    for line in session["line_items"]["data"]:
        try:
            line_item_ids.append(line["price"]["id"])
        except KeyError:
            continue

    try:
        membership_level = MembershipLevel.objects.get(
            Q(stripe_price_id__in=line_item_ids)
            | Q(stripe_price_id_one_time__in=line_item_ids)
        )
    except MembershipLevel.DoesNotExist:
        raise Exception("Membership level does not exist")

    full_name = session["customer_details"]["name"]

    snippet = MembershipEmailTemplateSnippet.objects.get(slug="join_thanks")

    send_email(
        to=email,
        subject=snippet.subject,
        body=snippet.body,
        context={
            "member": full_name,
        },
    )

    # Send a membership alert to ourselves
    alert_body = render_to_string(
        "emails/membership_alert_signup.html",
        {
            "name": full_name,
            "level": membership_level,
            "email": email,
        },
    )

    send_email(
        to=["membership@wahf.org", "dan@wahf.org"],
        subject=f"WAHF Membership Signup - {full_name}",
        body=None,
        body_html=alert_body,
        context={},
    )

    return


def process_subscription_ending(obj):
    member = Member.objects.filter(stripe_subscription_id=obj["id"])

    snippet = MembershipEmailTemplateSnippet.objects.get(slug="membership_expired")

    send_email(
        to=member.email,
        subject=snippet.subject,
        body=snippet.body,
        context={
            "member": member,
        },
    )


def process_membership_renewal(obj, session):
    return
    """
    # Expired renewals where the subscription is dead and needs to be recreated
    email = obj["customer_details"]["email"].lower()
    member_pk = session.metadata.get("member_pk", None)
    member = Member.objects.filter(pk=member_pk).first() if member_pk else None

    if not member_pk or not member:
        send_membership_error_email(
            f"WAHF Membership Renewal Error - Unable to find member #{member_pk}",
            f"A renewal was submitted for member with ID# {member_pk}, but we are not finding that ID in our WAHF database.",
        )
        raise Exception("Member PK not found")

    # Process renewal
    start_date = datetime.utcfromtimestamp(obj["current_period_start"]).date()
    end_date = datetime.utcfromtimestamp(obj["current_period_end"]).date()

    member.last_payment_date = start_date
    member.membership_expiry_date = end_date
    member.stripe_subscription_id = obj["id"]
    member.stripe_subscription_active = obj["status"] == "active"
    member.save()

    # Send a membership alert to ourselves
    alert_body = render_to_string(
        "emails/membership_alert_signup.html", {"member": member, "renewal": True}
    )

    send_email(
        to=["membership@wahf.org", "dan@wahf.org"],
        subject=f"WAHF Membership Renewal - {member}",
        body=None,
        body_html=alert_body,
        context={
            "member": member,
        },
    )

    return
    """


def process_subscription_create_update(obj):
    subscription_id = obj["id"]

    member = Member.objects.filter(stripe_subscription_id=subscription_id).first()
    if not member:
        # possibly a new subscription for someone without an existing one?
        customer = stripe.Customer.retrieve(obj["customer"])
        email = customer["email"]

        member = Member.objects.filter(email__iexact=email).first()

        if not member:
            print(
                f"Unknown member from subscription ID {subscription_id} or email address"
            )
            return HttpResponse("Unknown Member")

        if member.stripe_customer_id and member.stripe_customer_id != obj["customer"]:
            # Customer is new and does not match, something weird happened
            print(
                f"Unknown customer created this subscription, one already exists with that email {email}"
            )
            return HttpResponse("Duplicate email account")

        member.stripe_customer_id = obj["customer"]
        member.stripe_subscription_id = subscription_id

    # Update dates on subscription
    previous_end_date = member.membership_expiry_date
    # previous_status = member.stripe_subscription_active

    start_date = datetime.utcfromtimestamp(obj["current_period_start"]).date()
    end_date = datetime.utcfromtimestamp(obj["current_period_end"]).date()

    member.last_payment_date = start_date
    member.membership_expiry_date = end_date
    member.stripe_subscription_active = obj["status"] == "active"
    member.save()

    if end_date > previous_end_date and member.stripe_subscription_active:
        # Renewed?

        # Email member
        snippet = MembershipEmailTemplateSnippet.objects.get(
            slug="renew_thanks_automatic"
        )
        send_email(
            to=[member.email],
            subject=snippet.subject,
            body=snippet.body,
            context={
                "member": member,
            },
        )

        # Email administration
        alert_body = render_to_string(
            "emails/membership_alert_signup.html", {"member": member, "renewal": True}
        )
        send_email(
            to=["membership@wahf.org", "dan@wahf.org"],
            subject=f"WAHF Membership Auto Renewal - {member}",
            body=None,
            body_html=alert_body,
            context={
                "member": member,
            },
        )

    return HttpResponse("OK")


def process_subscription_delete(obj):
    subscription_id = obj["id"]

    member = Member.objects.filter(stripe_subscription_id=subscription_id).first()
    if not member:
        print(f"Unknown member from subscription ID {subscription_id}")
        return

    member.stripe_subscription_active = False
    member.save()

    send_membership_error_email(
        f"WAHF Membership Subscription Cancelled - {member} {member.email}",
        f"Stripe notified us that payments failed or subscription was cancelled for {member.pk} {member} {member.email}",
    )


def process_kohn_donation(obj, session):
    # Total amount paid
    amount_total = session["amount_total"] / 100.0

    name = session["customer_details"]["name"]
    email = session["customer_details"]["email"]

    stripe_id = session["id"]

    confirmation_body = render_to_string(
        "emails/kohn_thanks.html",
        {
            "amount": amount_total,
            "name": name,
            "transaction_id": stripe_id,
        },
    )

    send_email(
        to=[email],
        subject="Thanks for your support - Leo J. Kohn Photograph Collection",
        body=None,
        body_html=confirmation_body,
        context={
            "email": email,
        },
        from_email="WAHF/Kohn <kohn@wahf.org>",
    )

    send_email(
        to=["kohn@wahf.org"],
        subject="Thanks for your support - Leo J. Kohn Photograph Collection",
        body=None,
        body_html=confirmation_body,
        context={
            "email": email,
        },
        from_email="WAHF/Kohn <kohn@wahf.org>",
    )

    return
