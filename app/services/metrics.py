"""The operator's numbers, in one place.

Two questions, two answers, no overlap:

* ``system_health(db)`` - is the service itself well? Database reachable, which mode the
  AI and the ad platform are in, and when the last real thing happened. It holds no
  product counts, so the console has no reason to print a figure twice.
* ``activity(db)`` - what is the product doing, grouped by area (users, campaigns,
  content, support, advertising, activity log). Every value is a count or a sum over rows
  that exist; nothing is extrapolated, and anything we genuinely cannot know is returned
  as ``None`` and listed under ``unavailable`` with the reason.

Windows are computed in naive UTC because that is how this schema stores timestamps
(``server_default=func.now()`` and ``datetime.utcnow()`` in the app both write naive UTC),
so an aware datetime would be compared as a string with an offset in it and quietly shift
the window.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import Text, func, or_

from app.core.config import settings
from app.core.testdata import is_test_email
from app.db.session import AdAccount, Asset, Boost, Event, Order, Post, SupportTicket, User
from app.services.ad_platforms import is_simulated_account

# A ticket is still the operator's problem until it is resolved or closed; the old metric
# only counted the literal string "open", so a queue of ten in-progress tickets read as 0.
OPEN_TICKET_STATUSES = ("open", "in_progress")
RESOLVED_TICKET_STATUSES = ("resolved", "closed")
ERROR_EVENT = "error"

# Event types the product writes, newest first in the console.
TRACKED_EVENTS = (
    "user_registered",
    "campaign_built",
    "campaign_approved",
    "campaign_launched",
    "post_published",
    "ticket_created",
    "ticket_replied",
    "error",
)


# --------------------------------------------------------------------------- helpers
def _utcnow() -> datetime:
    """Naive UTC 'now', matching how every timestamp in this schema is stored."""
    return datetime.utcnow()


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.replace(microsecond=0).isoformat()


def _days_ago(days: int) -> datetime:
    return _utcnow() - timedelta(days=days)


def _count(db, model, *filters) -> int:
    q = db.query(model)
    for f in filters:
        q = q.filter(f)
    return q.count()


def _test_user_ids(db) -> set:
    """Account ids a test run registered - the rule itself lives in app.core.testdata."""
    return {u.id for u in db.query(User).all() if is_test_email(u.email)}


def _test_post_ids(db, ids) -> set:
    """Post ids belonging to a test account. Posts hang off a campaign, not a user."""
    if not ids:
        return set()
    rows = (db.query(Post.id).join(Boost, Post.boost_id == Boost.id)
              .filter(Boost.user_id.in_(ids)).all())
    return {r[0] for r in rows}


def _test_share(db, model, ids, *filters) -> int:
    """How many of a filtered count were made by a test run (0 when there are no test rows)."""
    if not ids:
        return 0
    return _count(db, model, *filters, model.user_id.in_(ids))


def _test_user_ids(db) -> set:
    """Account ids a test run registered - the rule itself lives in app.core.testdata."""
    return {u.id for u in db.query(User).all() if is_test_email(u.email)}


def _test_post_ids(db, ids) -> set:
    """Post ids belonging to a test account. Posts hang off a campaign, not a user."""
    if not ids:
        return set()
    rows = (db.query(Post.id).join(Boost, Post.boost_id == Boost.id)
              .filter(Boost.user_id.in_(ids)).all())
    return {r[0] for r in rows}


def _test_share(db, model, ids, *filters) -> int:
    """How many of a filtered count were made by a test run (0 when there are no test rows)."""
    if not ids:
        return 0
    return _count(db, model, *filters, model.user_id.in_(ids))


def _app_version() -> str:
    """The running app's version, read lazily so this module never imports main."""
    try:
        from app.main import app  # deferred: main imports the routers, which import us

        return str(getattr(app, "version", "") or "unknown")
    except Exception:  # noqa: BLE001 - a health number is not worth a crash
        return "unknown"


def _ai_mode() -> Dict[str, str]:
    """Whether content generation is real or running on the offline fixtures."""
    if settings.SIMULATE:
        return {"mode": "offline",
                "note": "RESMARA_SIMULATE is set, so the engine answers from its fixtures"}
    if not settings.OPENAI_API_KEY:
        return {"mode": "offline",
                "note": "no OPENAI_API_KEY is configured, so the engine answers from its fixtures"}
    return {"mode": "live",
            "note": f"generating with {settings.research_model} / {settings.OPENAI_MODEL_PLAN}"}


def _live_accounts(db):
    """Accounts whose token is real (the prototype sentinel token does not count)."""
    return [a for a in db.query(AdAccount).all() if not is_simulated_account(a)]


def _platform_mode(db) -> Dict[str, Any]:
    """Whether an ad account here can really spend, or the client is simulating."""
    if settings.SIMULATE:
        return {"mode": "simulated",
                "note": "RESMARA_SIMULATE is set, so platform calls are answered locally"}
    live = _live_accounts(db)
    if live:
        return {"mode": "live",
                "note": f"{len(live)} ad account(s) carry a real access token; campaigns still launch PAUSED"}
    return {"mode": "simulated",
            "note": "no ad account carries a real access token yet, so platform calls are simulated"}


def _last_event_at(db, event_type: str) -> Optional[str]:
    row = (db.query(func.max(Event.created_at))
             .filter(Event.event_type == event_type)
             .scalar())
    return _iso(row)


# --------------------------------------------------------------------------- system
def system_health(db) -> Dict[str, Any]:
    """Service-level status only - deliberately free of product counts."""
    from sqlalchemy import text

    try:
        db.execute(text("SELECT 1")).fetchone()
        db_ok = True
    except Exception:  # noqa: BLE001 - the failure IS the answer
        db_ok = False

    now = _utcnow()
    errors_24h = (db.query(Event)
                    .filter(Event.event_type == ERROR_EVENT)
                    .filter(Event.created_at >= now - timedelta(hours=24))
                    .count())
    last_error = (db.query(func.max(Event.created_at))
                    .filter(Event.event_type == ERROR_EVENT)
                    .scalar())

    ai = _ai_mode()
    platform = _platform_mode(db)

    return {
        "status": "healthy" if db_ok else "degraded",
        "db_ok": db_ok,
        "version": _app_version(),
        "env": settings.ENV,
        "errors_24h": errors_24h,
        "last_error_at": _iso(last_error),
        "last_build_at": _last_event_at(db, "campaign_built"),
        "last_launch_at": _last_event_at(db, "campaign_launched"),
        "ai_mode": ai["mode"],
        "ai_note": ai["note"],
        "platform_mode": platform["mode"],
        "platform_note": platform["note"],
        "checked_at": _iso(now),
    }


# --------------------------------------------------------------------------- activity
def _users(db, ids) -> Dict[str, Any]:
    # Never silently dropped from the totals: ``total`` stays every row that exists, and the
    # test share is named next to it so the console can show "4 real - 71 test" rather than
    # pretending the database holds four accounts.
    total, test = _count(db, User), len(ids)
    return {
        "total": total,
        "real": total - test,
        "test_accounts": test,
        "active": _count(db, User, User.is_active == True),  # noqa: E712
        "admins": _count(db, User, User.is_admin == True),  # noqa: E712
        "new_7d": _count(db, User, User.created_at >= _days_ago(7)),
        # last_login is written on every successful sign-in, so this really is "signed in
        # in the last day" - not "has an account", which is what it used to report.
        "active_24h": _count(db, User, User.last_login >= _utcnow() - timedelta(hours=24)),
        "never_signed_in": _count(db, User, User.last_login.is_(None)),
    }


def empty_plan_clause():
    """A campaign with no plan yet: nothing stored, or an empty container.

    ``Boost.plan`` is a JSON column. Comparing it with ``== {}`` renders ``plan = '{}'::JSON``,
    and Postgres has no equality operator for ``json`` (only ``jsonb``), so that predicate
    raised ``operator does not exist: json = json`` on the live database while passing on
    SQLite -- which blanked every square of the admin console with a 500. Compare the text
    form instead; it means the same thing on both dialects.
    """
    plan_text = func.coalesce(func.cast(Boost.plan, Text), "")
    return or_(Boost.plan.is_(None), plan_text.in_(("", "{}", "null", '""', "[]")))


def _campaigns(db, ids) -> Dict[str, Any]:
    by_stage: Dict[str, int] = {}
    for stage, n in db.query(Boost.stage, func.count(Boost.id)).group_by(Boost.stage).all():
        by_stage[str(stage or "UNKNOWN")] = int(n)
    empty_plan = empty_plan_clause()
    total, test = _count(db, Boost), _test_share(db, Boost, ids)
    return {
        "total": total,
        "real": total - test,
        "test_campaigns": test,
        "by_stage": by_stage,
        "live": _count(db, Boost, Boost.stage == "LIVE"),
        "launched": _count(db, Boost, Boost.launched_at.isnot(None)),
        "awaiting_build": _count(db, Boost, empty_plan),
        "awaiting_build_test": _test_share(db, Boost, ids, empty_plan),
        "budget_configured_usd": round(
            float(db.query(func.coalesce(func.sum(Boost.ad_budget_usd), 0.0)).scalar() or 0.0), 2),
    }


def _due_now_query(db, now):
    """The publisher's own rule: approved + scheduled + due + the account still active."""
    return (db.query(Post)
              .join(Boost, Post.boost_id == Boost.id)
              .join(AdAccount, Boost.ad_account_id == AdAccount.id)
              .filter(Post.client_status == "approved")
              .filter(Post.publish_status == "scheduled")
              .filter(Post.publish_at.isnot(None))
              .filter(Post.publish_at <= now.isoformat())
              .filter(AdAccount.is_active == True))  # noqa: E712


def _content(db, ids) -> Dict[str, Any]:
    now = _utcnow()
    post_ids = _test_post_ids(db, ids)
    posts = _count(db, Post)
    test_posts = _count(db, Post, Post.id.in_(post_ids)) if post_ids else 0
    # Same rule the publisher runs on (approved + scheduled + due + account still active),
    # so this number is the work its next pass will actually pick up.
    due_now = _due_now_query(db, now).count()
    upcoming = (db.query(func.min(Post.publish_at))
                  .filter(Post.publish_status == "scheduled")
                  .filter(Post.publish_at.isnot(None))
                  .filter(Post.publish_at > now.isoformat())
                  .scalar())
    return {
        "posts_total": posts,
        "real_posts": posts - test_posts,
        "test_posts": test_posts,
        "approved": _count(db, Post, Post.client_status == "approved"),
        "awaiting_approval": _count(db, Post, Post.client_status == "pending"),
        "changes_requested": _count(db, Post, Post.client_status == "change_requested"),
        "published": _count(db, Post, Post.publish_status == "posted"),
        "scheduled": _count(db, Post, Post.publish_status == "scheduled"),
        "failed": _count(db, Post, Post.publish_status == "failed"),
        "failed_test": _count(db, Post, Post.publish_status == "failed", Post.id.in_(post_ids)) if post_ids else 0,
        "due_now": due_now,
        "due_now_test": _due_now_query(db, now).filter(Post.id.in_(post_ids)).count() if post_ids else 0,
        "next_publish_at": _iso(upcoming),
        "photos": _count(db, Asset, Asset.kind == "photo"),
        "photos_test": _test_share(db, Asset, ids, Asset.kind == "photo"),
        "photos_tagged": _count(db, Asset, Asset.kind == "photo", Asset.tagged_by != "none"),
        "photos_untagged": _count(db, Asset, Asset.kind == "photo",
                                  or_(Asset.tagged_by.is_(None), Asset.tagged_by == "none")),
        "designs": _count(db, Asset, Asset.kind == "design"),
    }


def _support(db, ids) -> Dict[str, Any]:
    tickets = db.query(SupportTicket).all()
    test_tickets = [t for t in tickets if t.user_id in ids]
    open_tickets = [t for t in tickets if (t.status or "open") in OPEN_TICKET_STATUSES]
    waiting = []
    for t in open_tickets:
        msgs = t.messages or []
        last_from = (msgs[-1] or {}).get("from", "") if msgs else ""
        if str(last_from).lower() != "admin":
            waiting.append(t)
    newest = max((t.created_at for t in tickets if t.created_at), default=None)
    oldest_waiting = max((t.created_at for t in waiting if t.created_at), default=None)
    return {
        "tickets_total": len(tickets),
        "test_tickets": len(test_tickets),
        "real": len(tickets) - len(test_tickets),
        "open": len(open_tickets),
        "waiting_on_us": len(waiting),
        # The console's "needs an answer" tile must not count a test run's ticket: those are
        # answered by nobody and would otherwise read as real work waiting on a human.
        "waiting_on_us_test": len([t for t in waiting if t.user_id in ids]),
        "resolved": len([t for t in tickets if (t.status or "") in RESOLVED_TICKET_STATUSES]),
        "newest_at": _iso(newest),
        "oldest_waiting_at": _iso(oldest_waiting),
    }


def _advertising(db) -> Dict[str, Any]:
    platforms: Dict[str, int] = {}
    for platform, n in db.query(AdAccount.platform, func.count(AdAccount.id)).group_by(AdAccount.platform).all():
        platforms[str(platform or "unknown")] = int(n)
    # Token state is written by token_health on every sweep, so this is the last thing we
    # actually asked Meta - not a guess about whether a token is still good.
    statuses: Dict[str, int] = {}
    for status, n in db.query(AdAccount.token_status, func.count(AdAccount.id)).group_by(AdAccount.token_status).all():
        statuses[str(status or "not checked yet")] = int(n)
    live = len(_live_accounts(db))
    return {
        "accounts": _count(db, AdAccount),
        "by_token_status": statuses,
        "needs_reconnect": statuses.get("needs_reconnect", 0),
        "expiring": statuses.get("expiring", 0),
        "active": _count(db, AdAccount, AdAccount.is_active == True),  # noqa: E712
        "live_accounts": live,
        "simulated": _count(db, AdAccount) - live,
        "platforms": platforms,
        "budget_configured_usd": round(
            float(db.query(func.coalesce(func.sum(AdAccount.budget), 0.0)).scalar() or 0.0), 2),
    }


def _revenue(db) -> Dict[str, Any]:
    """What was actually bought, in money. Empty until a Stripe key exists - and says so.

    The console used to print "revenue is not measured" on a page whose product costs $49 a
    campaign. The truth is narrower: the price is set, the order rows exist, and nothing can
    be charged until STRIPE_SECRET_KEY is on the service.
    """
    from app.services.billing import price_cents, secret_key

    orders = db.query(Order).all()
    paid = [o for o in orders if (o.status or "") == "paid"]
    paid_cents = sum(int(o.amount_cents or 0) for o in paid)
    return {
        "orders": len(orders),
        "paid_orders": len(paid),
        "pending_orders": len([o for o in orders if (o.status or "") == "pending"]),
        "paid_cents": paid_cents,
        "paid_usd": round(paid_cents / 100.0, 2),
        "currency": (orders[0].currency if orders else "usd"),
        "price_cents": price_cents(),
        "price_usd": round(price_cents() / 100.0, 2),
        "stripe_configured": bool(secret_key()),
        "newest_at": _iso(max((o.created_at for o in orders if o.created_at), default=None)),
    }


def _activity_log(db, days: int = 14) -> Dict[str, Any]:
    """Event counts per day and per type - the closest thing to history this app keeps."""
    start = (_utcnow() - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = (db.query(Event.created_at, Event.event_type)
              .filter(Event.created_at >= start)
              .all())
    buckets: Dict[str, int] = {}
    for offset in range(days):
        buckets[(start + timedelta(days=offset)).date().isoformat()] = 0
    by_type: Dict[str, int] = {}
    for created, event_type in rows:
        stamp = created.date().isoformat() if isinstance(created, datetime) else str(created)[:10]
        if stamp in buckets:
            buckets[stamp] += 1
        else:
            buckets[stamp] = buckets.get(stamp, 0) + 1
        by_type[event_type] = by_type.get(event_type, 0) + 1
    return {
        "days": days,
        "per_day": [{"date": d, "events": n} for d, n in sorted(buckets.items())],
        "by_type_14d": {k: by_type[k] for k in sorted(by_type, key=lambda k: -by_type[k])},
        "total_14d": sum(buckets.values()),
    }


def stripe_ready() -> bool:
    """Whether a purchase could actually be charged right now."""
    from app.services.billing import secret_key

    return bool(secret_key())


def price_hint() -> int:
    """The configured campaign price, read without importing a router."""
    from app.services.billing import price_cents

    return price_cents()


def activity(db) -> Dict[str, Any]:
    """Everything the product is doing, grouped, with the unmeasurable named."""
    ad_spend_live = _platform_mode(db)["mode"] == "live"
    # Counted once: every group reports the same test share, and a customer's row must never
    # be hidden by a different rule in a different card.
    test_ids = _test_user_ids(db)
    failures: List[Dict[str, str]] = []

    def group(name, fn, *args):
        """One broken query must not blank the other five sections of the console."""
        try:
            return fn(db, *args)
        except Exception as exc:  # noqa: BLE001 - the console needs the reason, not a stack
            reason = f"the {name} query failed: {type(exc).__name__}: {exc}"
            failures.append({"metric": name, "reason": reason[:400]})
            return {"error": reason[:400]}

    groups = {
        "users": group("users", _users, test_ids),
        "campaigns": group("campaigns", _campaigns, test_ids),
        "content": group("content", _content, test_ids),
        "support": group("support", _support, test_ids),
        "advertising": group("advertising", _advertising),
        "revenue": group("revenue", _revenue),
        "activity": group("activity", _activity_log),
    }
    return {
        **groups,
        "unavailable": [
            {
                "metric": "ad_spend",
                "reason": ("no ad account carries an access token, so nothing has been spent "
                           "and nothing can be measured")
                if not ad_spend_live else
                ("spend is only known once the ad platform's Insights API answers; open a "
                 "campaign report to pull it for a specific campaign"),
            },
        ] + ([
            {
                "metric": "revenue",
                "reason": ("the price is $%.2f per campaign but no Stripe key is set, so nothing "
                           "can be bought yet and no money has moved" % (price_hint() / 100.0)),
            }
        ] if not stripe_ready() else []) + failures,
        "generated_at": _iso(_utcnow()),
    }
