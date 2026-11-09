"""Start-up costs: what the project cost to get here, who paid, and what keeps charging.

The business has no bank account yet, so every cost so far came off a personal card.
That is exactly the thing a founder loses track of: five small subscriptions, three
one-off purchases, two different payers, and by month four nobody can say what the
project actually costs to run. This router is the ledger:

  * a cost is one purchase — date, who paid, vendor, what for, amount
  * kind="one_off" counts once; kind="recurring" counts once per month (or year) from
    started_on, so the running total keeps rising without anyone retyping it
  * a cancelled subscription gets ended_on and stops counting from that month
  * a receipt (photo or PDF) attaches to the row and is served back ONLY to an admin,
    because a receipt images somebody's card

Nothing here touches customer money: this is the company's own spending, which is why
it lives beside the console's Money band rather than in billing.
"""
from __future__ import annotations

import os
import uuid
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security import get_admin_user
from app.db.session import Cost, CostReceipt, get_db

router = APIRouter()

CADENCES = ("monthly", "yearly")
KINDS = ("one_off", "recurring")
RECEIPT_TYPES = ("image/jpeg", "image/png", "image/webp", "image/heic", "application/pdf")
MAX_RECEIPT_BYTES = 10 * 1024 * 1024


# ── dates ────────────────────────────────────────────────────────────────────────────
def add_months(d: date, n: int) -> date:
    """Day-of-month is kept where the month allows it, clamped at the end (31 Jan → 28 Feb)."""
    y = d.year + (d.month - 1 + n) // 12
    m = (d.month - 1 + n) % 12 + 1
    return date(y, m, min(d.day, monthrange(y, m)[1]))


def _step(cadence: str) -> int:
    return 12 if cadence == "yearly" else 1


def charges_to_date(cost: Cost, today: Optional[date] = None) -> tuple[int, Optional[date]]:
    """How many times this has been charged by ``today``, and when the next one lands.

    A one-off is one charge on the day it was paid. A recurring cost charges on its start
    date and every cadence after, stopping at ended_on. The next charge is the first one
    strictly in the future, or None once the subscription has ended.
    """
    today = today or date.today()
    if cost.kind != "recurring":
        return (1 if cost.paid_on <= today else 0), None

    cadence = cost.cadence if cost.cadence in CADENCES else "monthly"
    start = cost.started_on or cost.paid_on
    if start > today:
        return 0, start

    step = _step(cadence)
    n = 0
    while True:
        when = add_months(start, n * step)
        if when > today:
            break
        if cost.ended_on and when > cost.ended_on:
            return n, None
        n += 1
        if n > 1200:  # a hundred years of months: a guard, not a business rule
            break

    if cost.ended_on and add_months(start, n * step) > cost.ended_on:
        return n, None
    return n, add_months(start, n * step)


def _money(cents: int) -> float:
    return round((cents or 0) / 100.0, 2)


# ── shapes ───────────────────────────────────────────────────────────────────────────
class CostIn(BaseModel):
    paid_on: Optional[date] = None
    paid_by: str
    vendor: str
    description: Optional[str] = None
    amount_cents: int
    currency: str = "usd"
    kind: str = "one_off"
    cadence: Optional[str] = None
    started_on: Optional[date] = None
    ended_on: Optional[date] = None
    notes: Optional[str] = None


class CostPatch(BaseModel):
    paid_on: Optional[date] = None
    paid_by: Optional[str] = None
    vendor: Optional[str] = None
    description: Optional[str] = None
    amount_cents: Optional[int] = None
    kind: Optional[str] = None
    cadence: Optional[str] = None
    started_on: Optional[date] = None
    ended_on: Optional[date] = None
    notes: Optional[str] = None


class CostOut(BaseModel):
    id: int
    paid_on: Optional[date]
    paid_by: str
    vendor: str
    description: Optional[str]
    amount_cents: int
    amount_usd: float
    currency: str
    kind: str
    cadence: Optional[str]
    started_on: Optional[date]
    ended_on: Optional[date]
    notes: Optional[str]
    charges: int
    charged_to_date_usd: float
    next_charge_on: Optional[date]
    receipts: list


def _out(cost: Cost, receipts: list, today: Optional[date] = None) -> CostOut:
    charges, nxt = charges_to_date(cost, today)
    return CostOut(
        id=cost.id, paid_on=cost.paid_on, paid_by=cost.paid_by, vendor=cost.vendor,
        description=cost.description, amount_cents=cost.amount_cents,
        amount_usd=_money(cost.amount_cents), currency=cost.currency or "usd",
        kind=cost.kind, cadence=cost.cadence, started_on=cost.started_on,
        ended_on=cost.ended_on, notes=cost.notes, charges=charges,
        charged_to_date_usd=_money((cost.amount_cents or 0) * charges),
        next_charge_on=nxt, receipts=receipts,
    )


def _receipt_meta(r: CostReceipt) -> dict:
    return {"id": r.id, "name": r.original_name or r.filename, "size": r.size,
            "content_type": r.content_type,
            "url": "/api/admin/costs/receipts/%d" % r.id}


def _summary(costs: list, today: Optional[date] = None) -> dict:
    """The numbers a founder actually asks: what have I spent, what repeats, who paid.

    ``spent_to_date`` is one-offs plus every recurring charge that has already landed —
    the same arithmetic the rows show, summed, so a row and the total cannot disagree.
    """
    today = today or date.today()
    one_off = 0
    monthly = 0
    to_date = 0
    by_payer: dict[str, int] = {}
    next_due = None
    active_recurring = 0

    for c in costs:
        out = _out(c, [], today)
        spent = (c.amount_cents or 0) * out.charges
        to_date += spent
        by_payer[c.paid_by] = by_payer.get(c.paid_by, 0) + spent
        if c.kind == "recurring":
            if not c.ended_on:
                active_recurring += 1
                if c.cadence == "yearly":
                    monthly += round((c.amount_cents or 0) / 12.0)
                else:
                    monthly += c.amount_cents or 0
                if out.next_charge_on and (next_due is None or out.next_charge_on < next_due):
                    next_due = out.next_charge_on
            continue
        one_off += c.amount_cents or 0

    return {
        "spent_to_date_usd": _money(to_date),
        "one_off_usd": _money(one_off),
        "recurring_to_date_usd": _money(to_date - one_off),
        "monthly_recurring_usd": _money(monthly),
        "yearly_run_rate_usd": _money(monthly * 12),
        "active_subscriptions": active_recurring,
        "next_renewal_on": next_due,
        "by_payer_usd": {k: _money(v) for k, v in sorted(by_payer.items())},
        "cost_rows": len(costs),
        "as_of": today,
    }


# ── routes ───────────────────────────────────────────────────────────────────────────
@router.get("/admin/costs")
def list_costs(current_user=Depends(get_admin_user), db: Session = Depends(get_db)):
    costs = db.query(Cost).order_by(Cost.paid_on.desc(), Cost.id.desc()).all()
    receipt_rows: dict[int, list] = {}
    for r in db.query(CostReceipt).all():
        receipt_rows.setdefault(r.cost_id, []).append(_receipt_meta(r))
    items = [_out(c, receipt_rows.get(c.id, [])) for c in costs]
    summary = _summary(costs)
    summary["with_receipt"] = sum(1 for i in items if i.receipts)
    summary["without_receipt"] = sum(1 for i in items if not i.receipts)
    return {"items": items, "summary": summary}


@router.post("/admin/costs", status_code=201)
def create_cost(payload: CostIn, current_user=Depends(get_admin_user), db: Session = Depends(get_db)):
    kind = payload.kind if payload.kind in KINDS else "one_off"
    cadence = payload.cadence if payload.cadence in CADENCES else ("monthly" if kind == "recurring" else None)
    if kind == "recurring" and cadence not in CADENCES:
        raise HTTPException(status_code=422, detail="A recurring cost needs a cadence of monthly or yearly")
    if payload.amount_cents is None or payload.amount_cents < 0:
        raise HTTPException(status_code=422, detail="The amount has to be zero or more, in cents")

    paid_on = payload.paid_on or date.today()
    cost = Cost(
        paid_on=paid_on, paid_by=(payload.paid_by or "").strip() or "unknown",
        vendor=(payload.vendor or "").strip(), description=payload.description,
        amount_cents=int(payload.amount_cents), currency=(payload.currency or "usd").lower()[:8],
        kind=kind, cadence=cadence,
        started_on=payload.started_on or (paid_on if kind == "recurring" else None),
        ended_on=payload.ended_on, notes=payload.notes, created_by=current_user.id,
    )
    if not cost.vendor:
        raise HTTPException(status_code=422, detail="Say what the money was paid to (the vendor)")
    db.add(cost)
    db.commit()
    db.refresh(cost)
    return _out(cost, [])


@router.patch("/admin/costs/{cost_id}")
def patch_cost(cost_id: int, payload: CostPatch, current_user=Depends(get_admin_user),
               db: Session = Depends(get_db)):
    cost = db.query(Cost).filter(Cost.id == cost_id).first()
    if not cost:
        raise HTTPException(status_code=404, detail="No such cost")
    # A cleared field is a real instruction — "this subscription is running again" arrives
    # as ended_on: null — so an explicit null is applied for the fields that may be cleared,
    # while a null on a required field is ignored rather than blanking it.
    clearable = {"ended_on", "notes", "description", "started_on", "cadence"}
    data = payload.dict(exclude_unset=True)
    for field, value in data.items():
        if value is None and field not in clearable:
            continue
        setattr(cost, field, value)
    if cost.kind not in KINDS:
        cost.kind = "one_off"
    if cost.kind == "recurring":
        cost.cadence = cost.cadence if cost.cadence in CADENCES else "monthly"
        cost.started_on = cost.started_on or cost.paid_on
    else:
        cost.cadence = None
        cost.ended_on = None
    db.commit()
    db.refresh(cost)
    rows = db.query(CostReceipt).filter(CostReceipt.cost_id == cost.id).all()
    return _out(cost, [_receipt_meta(r) for r in rows])


@router.delete("/admin/costs/{cost_id}")
def delete_cost(cost_id: int, current_user=Depends(get_admin_user), db: Session = Depends(get_db)):
    cost = db.query(Cost).filter(Cost.id == cost_id).first()
    if not cost:
        raise HTTPException(status_code=404, detail="No such cost")
    db.query(CostReceipt).filter(CostReceipt.cost_id == cost_id).delete()
    db.delete(cost)
    db.commit()
    return {"ok": True, "deleted": cost_id}


@router.post("/admin/costs/{cost_id}/receipt", status_code=201)
async def upload_receipt(cost_id: int, file: UploadFile = File(...),
                         current_user=Depends(get_admin_user), db: Session = Depends(get_db)):
    cost = db.query(Cost).filter(Cost.id == cost_id).first()
    if not cost:
        raise HTTPException(status_code=404, detail="No such cost")
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".pdf"):
        raise HTTPException(status_code=415, detail="A receipt has to be a photo (jpg, png, webp, heic) or a PDF")
    blob = await file.read()
    if not blob:
        raise HTTPException(status_code=422, detail="That file is empty")
    if len(blob) > MAX_RECEIPT_BYTES:
        raise HTTPException(status_code=413, detail="That receipt is over 10 MB")
    ctype = (file.content_type or "").split(";")[0].strip().lower()
    if ctype not in RECEIPT_TYPES:
        ctype = "application/pdf" if ext == ".pdf" else "image/" + ("jpeg" if ext in (".jpg", ".jpeg") else ext.lstrip("."))
    row = CostReceipt(cost_id=cost.id, filename=uuid.uuid4().hex + ext,
                      original_name=os.path.basename(file.filename or "receipt" + ext),
                      content_type=ctype, size=len(blob), data=blob)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _receipt_meta(row)


@router.get("/admin/costs/receipts/{receipt_id}")
def get_receipt(receipt_id: int, current_user=Depends(get_admin_user), db: Session = Depends(get_db)):
    """Admin only, no cache: a receipt shows the card somebody paid with."""
    row = db.query(CostReceipt).filter(CostReceipt.id == receipt_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="No such receipt")
    headers = {
        "Cache-Control": "no-store",
        "Content-Disposition": 'inline; filename="%s"' % (row.original_name or row.filename),
    }
    return Response(content=row.data, media_type=row.content_type or "application/octet-stream",
                    headers=headers)


@router.delete("/admin/costs/receipts/{receipt_id}")
def delete_receipt(receipt_id: int, current_user=Depends(get_admin_user), db: Session = Depends(get_db)):
    row = db.query(CostReceipt).filter(CostReceipt.id == receipt_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="No such receipt")
    db.delete(row)
    db.commit()
    return {"ok": True, "deleted": receipt_id}
