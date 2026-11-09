"""Email delivery tests: the send path is exercised against a real SMTP conversation.

A tiny in-process SMTP server accepts the connection, so the test proves the client actually
speaks the protocol, logs in and hands over a message — not just that a function returned True.
Resend (the HTTP provider) is checked with a stubbed httpx.post.

Run:  cd /Users/dan/resmara && PYTHONPATH=/Users/dan/resmara venv/bin/python tests/test_mail.py
"""
import socket
import sys
import threading

import httpx

from app.services import mail

PASSED = 0
FAILED = 0


def check(label, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print("  [PASS] %s" % label)
    else:
        FAILED += 1
        print("  [FAIL] %s  %s" % (label, detail))


class FakeSMTPServer(threading.Thread):
    """Accepts one session, records the message, answers just enough of RFC 5321."""

    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.credentials = None
        self.message = ""

    def run(self):
        conn, _ = self.sock.accept()
        conn.settimeout(10)
        f = conn.makefile("rwb", buffering=0)

        def say(line):
            f.write((line + "\r\n").encode())

        say("220 test.local SMTP")
        in_data = False
        try:
            while True:
                raw = f.readline()
                if not raw:
                    break
                line = raw.decode(errors="replace").rstrip("\r\n")
                if in_data:
                    if line == ".":
                        in_data = False
                        say("250 2.0.0 queued")
                    else:
                        self.message += line + "\n"
                    continue
                upper = line.upper()
                if upper.startswith("EHLO") or upper.startswith("HELO"):
                    say("250-test.local")
                    say("250 AUTH PLAIN LOGIN")
                elif upper.startswith("AUTH"):
                    self.credentials = line
                    say("235 2.7.0 authenticated")
                elif upper.startswith("MAIL FROM") or upper.startswith("RCPT TO"):
                    say("250 2.1.0 ok")
                elif upper == "DATA":
                    in_data = True
                    say("354 send it")
                elif upper == "QUIT":
                    say("221 bye")
                    break
                else:
                    say("250 ok")
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass


def main():
    global PASSED, FAILED
    import os
    saved = {k: os.environ.get(k) for k in
             ("RESEND_API_KEY", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_PORT",
              "SMTP_SSL", "SMTP_STARTTLS", "SMTP_FROM", "MAIL_FROM")}

    for k in saved:
        os.environ.pop(k, None)

    print("[no provider]")
    check("nothing configured is reported as such", mail.mail_configured() is False)
    check("and a send honestly fails", mail.send_email("a@b.c", "s", "b") is False)
    state = mail.delivery_state()
    check("the state explains what to set", "RESEND_API_KEY" in state["note"], state["note"])

    print("\n[smtp]")
    server = FakeSMTPServer()
    server.start()
    os.environ.update({
        "SMTP_HOST": "127.0.0.1", "SMTP_PORT": str(server.port),
        "SMTP_USER": "postmaster@resmara.test", "SMTP_PASSWORD": "not-a-real-password",
        "SMTP_STARTTLS": "0", "SMTP_FROM": "Resmara <noreply@resmara.test>",
    })
    check("smtp is detected", mail.provider() == "smtp", mail.provider())
    sent = mail.send_email("owner@resmara.test", "Reset your Resmara password",
                           "Use this link: https://resmara.com/reset?t=abc")
    server.join(timeout=5)
    check("the message is accepted over a real conversation", sent is True)
    check("the body reached the server", "https://resmara.com/reset?t=abc" in server.message,
          server.message[:200])
    check("the recipient was addressed", "owner@resmara.test" in server.message, server.message[:200])
    check("the subject was set", "Reset your Resmara password" in server.message, server.message[:200])
    check("a login was attempted", bool(server.credentials), server.credentials)
    check("the credential never appears in the transcript",
          "not-a-real-password" not in (server.credentials or ""), server.credentials)

    print("\n[failure path]")
    os.environ["SMTP_PORT"] = "1"  # nothing is listening
    check("a dead relay returns False, not an exception", mail.send_email("a@b.c", "s", "b") is False)

    print("\n[resend]")
    os.environ.update({"RESEND_API_KEY": "re_test_123", "MAIL_FROM": "Resmara <hello@resmara.com>"})
    check("resend wins when both are configured", mail.provider() == "resend")
    captured = {}

    def fake_post(url, **kwargs):
        captured.update({"url": url, "kwargs": kwargs})
        return httpx.Response(200, json={"id": "re_123"}, request=httpx.Request("POST", url))

    original = mail.httpx.post
    mail.httpx.post = fake_post
    try:
        ok = mail.send_email("owner@resmara.test", "Your receipt", "$49 paid")
    finally:
        mail.httpx.post = original
    check("resend send reports success", ok is True)
    check("it posts to the Resend API", captured.get("url") == mail.RESEND_ENDPOINT, captured.get("url"))
    body = (captured.get("kwargs") or {}).get("json") or {}
    check("the bearer is the key", (captured["kwargs"]["headers"]["Authorization"] or "").endswith("re_test_123"))
    check("from/to/subject/body are right",
          body.get("from") == "Resmara <hello@resmara.com>" and body.get("to") == ["owner@resmara.test"]
          and body.get("subject") == "Your receipt" and body.get("text") == "$49 paid", body)

    print("\n[restore env]")
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    print("  restored")

    print("\n" + "=" * 60)
    print("%d passed, %d failed" % (PASSED, FAILED))
    if FAILED:
        print("MAIL TESTS FAILED")
        sys.exit(1)
    print("ALL MAIL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
