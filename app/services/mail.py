"""Transactional email: password resets, invitations, receipts.

Two providers, tried in this order:

1. **Resend** (``RESEND_API_KEY``, optional ``MAIL_FROM``) — an HTTP API, so it works on hosts
   that block outbound SMTP (Render's free tier silently drops port 587, which is how "email is
   broken" looks from the outside).
2. **SMTP** (``SMTP_HOST``/``SMTP_USER``/``SMTP_PASSWORD``) — Gmail app password or any relay.

Nothing is faked: with no provider the call returns ``not_configured`` and the caller tells the
person so. A reset link that was never sent must never be reported as sent, and no password or
token is ever logged.
"""
import os
import smtplib
from email.message import EmailMessage

import httpx

RESEND_ENDPOINT = "https://api.resend.com/emails"


def resend_key() -> str:
    return (os.getenv("RESEND_API_KEY") or "").strip()


def smtp_configured() -> bool:
    return bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_USER") and os.getenv("SMTP_PASSWORD"))


def provider() -> str:
    """Which provider a send would use: 'resend', 'smtp' or '' (nothing configured)."""
    if resend_key():
        return "resend"
    if smtp_configured():
        return "smtp"
    return ""


def mail_configured() -> bool:
    return bool(provider())


def default_sender() -> str:
    """Who the mail comes from. Resend needs a verified domain or its onboarding address."""
    return (os.getenv("MAIL_FROM") or os.getenv("SMTP_FROM") or "Resmara <noreply@resmara.com>").strip()


def _send_via_resend(to: str, subject: str, body: str) -> bool:
    try:
        resp = httpx.post(RESEND_ENDPOINT, timeout=20,
                          headers={"Authorization": "Bearer %s" % resend_key()},
                          json={"from": default_sender(), "to": [to],
                                "subject": subject, "text": body})
    except httpx.HTTPError:
        return False
    return resp.status_code in (200, 201, 202)


def _send_via_smtp(to: str, subject: str, body: str) -> bool:
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    sender = os.getenv("SMTP_FROM", user)
    use_ssl = (os.getenv("SMTP_SSL", "").lower() in ("1", "true", "yes")) or port == 465
    # A relay on the same host may speak plain SMTP; public providers require TLS.
    use_tls = (os.getenv("SMTP_STARTTLS", "1").lower() not in ("0", "false", "no"))

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=20) as s:
                s.login(user, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                if use_tls:
                    s.starttls()
                s.login(user, password)
                s.send_message(msg)
        return True
    except Exception:  # noqa: BLE001 - any transport failure means "not sent"
        return False


def send_email(to: str, subject: str, body: str) -> bool:
    """Send one plain-text email. True only when the provider accepted it."""
    kind = provider()
    if kind == "resend":
        return _send_via_resend(to, subject, body)
    if kind == "smtp":
        return _send_via_smtp(to, subject, body)
    return False


def delivery_state() -> dict:
    """What the operator console should say about email, without revealing a credential."""
    kind = provider()
    return {
        "configured": bool(kind),
        "provider": kind or None,
        "from": default_sender() if kind else None,
        "note": ("email works" if kind else
                 "no email provider: set RESEND_API_KEY (recommended) or SMTP_HOST/SMTP_USER/SMTP_PASSWORD"),
    }
