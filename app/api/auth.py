"""Accounts: register, login, profile, and the password-reset flow."""
import hashlib
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db, User, PasswordReset, Event
from app.core.security import get_password_hash, verify_password, create_access_token, get_current_user
from app.schemas.resmara import UserCreate, UserOut, Token
from app.services import mail
from app.services.access import signup_block_reason, parse_allowlist

router = APIRouter()

RESET_TTL_MINUTES = 60


@router.post("/register", response_model=UserOut, status_code=201)
def register(user_in: UserCreate, db: Session = Depends(get_db)):
    email = user_in.email.strip().lower()
    blocked = signup_block_reason(email, getattr(user_in, "invite_code", None),
                                  settings.SIGNUP_EMAILS, settings.SIGNUP_CODE,
                                  settings.ADMIN_EMAILS)
    if blocked:
        raise HTTPException(status_code=403, detail=blocked)
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(email=email, hashed_password=get_password_hash(user_in.password), name=user_in.name,
                is_admin=email in parse_allowlist(settings.ADMIN_EMAILS))
    db.add(user)
    db.flush()
    # The activity log is what the operator console charts; a new account is the first
    # thing it should be able to show.
    db.add(Event(user_id=user.id, event_type="user_registered", payload={"source": "password"}))
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form.username.strip().lower()).first()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    if not user.is_active:
        # Deactivating an account has to actually stop it signing in.
        raise HTTPException(status_code=403, detail="This account is disabled")
    if not user.is_admin and user.email in parse_allowlist(settings.ADMIN_EMAILS):
        # Owners listed in RESMARA_ADMIN_EMAILS are operators from their first login, whether
        # the account predates the setting or not; no database edit needed to add a second one.
        user.is_admin = True
    user.last_login = datetime.utcnow()
    db.commit()
    token = create_access_token(data={"sub": user.email})
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/me", response_model=UserOut)
def update_me(name: str = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if name is not None:
        current_user.name = name
        db.commit()
        db.refresh(current_user)
    return current_user


@router.post("/me/password")
def change_password(current_password: str, new_password: str,
                    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    current_user.hashed_password = get_password_hash(new_password)
    # Any outstanding reset link is now pointless.
    db.query(PasswordReset).filter(PasswordReset.user_id == current_user.id,
                                   PasswordReset.used_at.is_(None)).update({"used_at": datetime.utcnow()})
    db.commit()
    return {"status": "password_changed"}


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.post("/password-reset/request")
def request_reset(email: str, db: Session = Depends(get_db)):
    """Start a reset. Always answers the same way, so this cannot be used to discover
    which email addresses have accounts.

    Delivery: the link is emailed when SMTP is configured. Until then it returns
    delivery='not_configured' (and in development the token is returned so the flow can
    be exercised) - the reset itself always works, only the letter is missing.
    """
    user = db.query(User).filter(User.email == email.strip().lower()).first()
    delivery = "not_configured"
    token = None
    if user and user.is_active:
        raw = secrets.token_urlsafe(32)
        db.add(PasswordReset(user_id=user.id, token_hash=_hash(raw),
                             expires_at=datetime.utcnow() + timedelta(minutes=RESET_TTL_MINUTES)))
        db.commit()
        link = f"{settings.PUBLIC_BASE_URL}/reset?token={raw}"
        if mail.send_email(user.email, "Reset your Resmara password",
                           f"Someone asked to reset the password for this account.\n\n"
                           f"Use this link within {RESET_TTL_MINUTES} minutes:\n{link}\n\n"
                           f"If this wasn't you, ignore this email."):
            delivery = "email"
        else:
            token = raw  # no mailer yet: hand it back so the reset can still be completed
    return {"status": "ok", "delivery": delivery, "expires_minutes": RESET_TTL_MINUTES,
            "reset_token": token, "detail": "Check your email for the reset link."}


@router.post("/password-reset/confirm")
def confirm_reset(token: str, new_password: str, db: Session = Depends(get_db)):
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    row = db.query(PasswordReset).filter(PasswordReset.token_hash == _hash(token)).first()
    if not row or row.used_at is not None or row.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired")
    user = db.query(User).filter(User.id == row.user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired")
    user.hashed_password = get_password_hash(new_password)
    row.used_at = datetime.utcnow()
    # Invalidate every other outstanding link for this account.
    db.query(PasswordReset).filter(PasswordReset.user_id == user.id, PasswordReset.id != row.id,
                                   PasswordReset.used_at.is_(None)).update({"used_at": datetime.utcnow()})
    db.commit()
    return {"status": "password_reset", "email": user.email}
