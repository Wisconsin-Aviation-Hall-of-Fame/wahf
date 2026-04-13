from membership.utils import send_email

ALERT_EMAIL = "dan@wahf.org"


def send_broken_link_alert(lookup_value, lookup_type="slug"):
    subject = f"Broken short link: /q/{lookup_value}"
    body = (
        f"<p>A visitor tried to follow a short link that does not exist.</p>"
        f"<p><strong>Lookup type:</strong> {lookup_type}<br>"
        f"<strong>Value:</strong> {lookup_value}<br>"
        f"<strong>URL:</strong> /q/{lookup_value}</p>"
    )
    send_email(to=ALERT_EMAIL, subject=subject, body="", body_html=body)
