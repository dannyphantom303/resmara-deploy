from pydantic import BaseModel, EmailStr, Field
from typing import Optional, Any
from datetime import datetime

# --- Auth ---
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: Optional[str] = None
    # Only needed while the beta gate is on (RESMARA_SIGNUP_CODE); ignored when signup is open.
    invite_code: Optional[str] = None

class UserOut(BaseModel):
    id: int
    email: EmailStr
    name: Optional[str] = None
    is_admin: bool = False
    subscription_status: str = "inactive"
    last_login: Optional[datetime] = None
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

# --- Ad Account ---
class AdAccountCreate(BaseModel):
    platform: str = "meta"
    advertiser_id: str
    account_name: Optional[str] = None
    budget: float = 50.0
    currency: str = "USD"
    # The long-lived Page/system token. Leave it out to stay in simulated mode.
    access_token: Optional[str] = None
    page_id: Optional[str] = None       # the Facebook Page the boost posts to
    ig_user_id: Optional[str] = None    # the Instagram business account

class AdAccountOut(BaseModel):
    id: int
    platform: str
    advertiser_id: str
    account_name: Optional[str] = None
    currency: str = "USD"
    budget: float
    is_active: bool = True
    # Connection health for a client-billed account: whose card pays Meta, whether our
    # access is still good, and whether the account is in a state that can spend.
    token_status: Optional[str] = None          # healthy | expiring | needs_reconnect | simulated
    token_expires_at: Optional[datetime] = None
    token_note: Optional[str] = None            # Meta's own wording when there is a problem
    token_refresh_note: Optional[str] = None    # what the last token refresh actually achieved
    needs_reconnect: bool = False
    funding_status: Optional[str] = None        # has_funding | no_funding | None (unknown)
    funding_note: Optional[str] = None
    account_status: Optional[int] = None        # Meta account_status enum
    account_status_label: Optional[str] = None
    health_checked_at: Optional[datetime] = None
    page_id: Optional[str] = None
    ig_user_id: Optional[str] = None
    class Config:
        from_attributes = True

# --- Creative ---
class CreativeCreate(BaseModel):
    asset_url: str
    asset_type: str = "image"
    asset_name: Optional[str] = None
    copy_text: Optional[str] = None
    cta_text: Optional[str] = None
    landing_page_url: Optional[str] = None

class CreativeOut(BaseModel):
    id: int
    asset_url: str
    asset_type: str
    asset_name: Optional[str] = None
    render_status: str = "PENDING"
    copy_text: Optional[str] = None
    cta_text: Optional[str] = None
    landing_page_url: Optional[str] = None
    class Config:
        from_attributes = True

# --- Boost ---
class BoostCreate(BaseModel):
    address: str
    ad_account_id: Optional[int] = None
    tier: str = "bap_shoot_499"
    go_live_date: Optional[str] = None
    campaign_days: int = 14
    ad_budget_usd: float = 50.0
    property_facts: Optional[str] = None

class BoostOut(BaseModel):
    id: int
    user_id: int
    address: str
    tier: str
    main_status: str
    go_live_date: Optional[str] = None
    campaign_days: int = 14
    ad_budget_usd: float = 50.0
    stage: str = "PENDING"
    meta_campaign_id: Optional[str] = None
    created_at: Optional[datetime] = None
    launched_at: Optional[datetime] = None
    # Real post counts, filled by list_boosts. Zero means "no posts built yet", which is a
    # measured fact - never a placeholder.
    posts_total: int = 0
    posts_approved: int = 0
    posts_published: int = 0
    # The campaign's own first gallery photo, so a card shows the property instead of stock
    # art. Empty means no photo imported yet - the UI has to say that, not fake one.
    image: Optional[str] = None
    class Config:
        from_attributes = True

# --- Launch Payload ---
class LaunchPayload(BaseModel):
    platform: str = "meta"
    source: str = "scratch"
    medias: list = Field(default_factory=list)
    meta_account_id: Optional[str] = None
    # Launch the campaign that was already built for this boost. Without it we have no
    # plan, no approved posts and no street to name the campaign after, so it is required.
    boost_id: Optional[int] = None
    meta_custom_configs: Optional[dict] = None
    auto_approve: bool = False

# --- Support ---
class SupportTicketCreate(BaseModel):
    subject: str
    message: str

class SupportTicketOut(BaseModel):
    id: int
    user_id: int
    subject: str
    status: str
    messages: list = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Only the operator list fills this in, so an operator can see who is writing
    # without a second lookup per row.
    client_email: Optional[str] = None
    # Written by a test run, not a person. The console hides these by default and says how
    # many it hid, so the queue an operator reads is their customers' and nobody else's.
    is_test: bool = False
    class Config:
        from_attributes = True

# --- Admin ---
class AdminUserOut(BaseModel):
    id: int
    email: str
    name: Optional[str] = None
    is_active: bool
    subscription_status: str
    last_login: Optional[datetime] = None
    created_at: Optional[datetime] = None
    campaign_count: int = 0
    # See SupportTicketOut.is_test: test artefacts are flagged, not deleted.
    is_test: bool = False
    # Whether this account can open /admin.html. Without it the console cannot answer
    # "why does my login say I am not an admin" -- the flag is the answer.
    is_admin: bool = False
    class Config:
        from_attributes = True

class SystemHealth(BaseModel):
    """Service status only. Product counts live in MetricsOut, so the two never overlap."""

    status: str
    db_ok: bool
    version: str
    env: str
    errors_24h: int
    last_error_at: Optional[datetime] = None
    last_build_at: Optional[datetime] = None
    last_launch_at: Optional[datetime] = None
    ai_mode: str
    ai_note: str
    platform_mode: str
    platform_note: str
    checked_at: Optional[datetime] = None

class MetricsOut(BaseModel):
    """Product activity, grouped. Anything unmeasurable is None and named in ``unavailable``."""

    users: dict
    campaigns: dict
    content: dict
    support: dict
    advertising: dict
    revenue: dict = {}
    activity: dict
    unavailable: list
    generated_at: Optional[datetime] = None
