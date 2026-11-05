"""Minimal transactional email. Used for password-reset links.

Delivery is opt-in: when SMTP_HOST/SMTP_USER/SMTP_PASSWORD are set the message is sent
over SMTP (works with a Gmail app password or any provider); otherwise the call returns
False and the caller reports delivery='not_configured' rather than pretending it sent
mail. Nothing here ever logs a password or a token.
"""
import os
import smtplib
from email.message import EmailMessage


def smtp_configured() -> bool:
    return bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_USER") and os.getenv("SMTP_PASSWORD"))


def send_email(to: str, subject: str, body: str) -> bool:
    """Send one plain-text email. Returns True only when the server accepted it."""
    if not smtp_configured():
        return False
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    sender = os.getenv("SMTP_FROM", user)

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.starttls()
            s.login(user, password)
            s.send_message(msg)
        return True
    except Exception:
        return False
