import os
from sqlalchemy import create_engine, Column, Integer, String, Text, Float, Boolean, DateTime, ForeignKey, func, JSON, LargeBinary
from sqlalchemy.orm import sessionmaker, declarative_base

from app.db.urls import normalize_database_url

SQLALCHEMY_DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL", "sqlite:///./resmara.db"))
if "sqlite" in SQLALCHEMY_DATABASE_URL:
    connect_args = {"check_same_thread": False}
else:
    connect_args = {}

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- User/Agent ---
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    subscription_status = Column(String, default="inactive")
    last_login = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# --- Ad Account (OAuth) ---
class AdAccount(Base):
    __tablename__ = "ad_accounts"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    platform = Column(String, nullable=False)  # meta, tiktok, google-ads
    advertiser_id = Column(String, nullable=False)
    account_name = Column(String, nullable=True)
    currency = Column(String, default="USD")
    budget = Column(Float, default=0.0)
    # Stored encrypted (see app/core/crypto.py). The underscore attribute is what SQLAlchemy
    # maps; the public `access_token` property below transparently decrypts on read and
    # encrypts on write, so every existing caller keeps working unchanged while the
    # database file alone no longer hands over a customer's ad account.
    _access_token = Column("access_token", Text, nullable=True)
    _refresh_token = Column("refresh_token", Text, nullable=True)
    token_expires_at = Column(DateTime(timezone=True), nullable=True)
    # Token/account health, refreshed by app/services/token_health.py. A client-billed
    # account is the customer's own ad account with the customer's own card on it, so both
    # "is our token still good" and "can this account actually spend" have to be answerable.
    token_status = Column(String, nullable=True)        # healthy | expiring | needs_reconnect | simulated
    token_checked_at = Column(DateTime(timezone=True), nullable=True)
    token_note = Column(Text, nullable=True)            # Meta's own wording, never invented
    token_refreshed_at = Column(DateTime(timezone=True), nullable=True)  # last refresh attempt
    # What the last refresh actually achieved. Meta sometimes returns a new token with the
    # SAME expiry, and saying "renewed" there would be a lie the client only discovers when
    # the ads stop.
    token_refresh_note = Column(Text, nullable=True)
    funding_status = Column(String, nullable=True)      # has_funding | no_funding
    funding_note = Column(Text, nullable=True)
    account_status = Column(Integer, nullable=True)     # Meta account_status enum (1 = ACTIVE)
    account_checked_at = Column(DateTime(timezone=True), nullable=True)
    # Publishing targets: the FB Page and the IG business account this boost posts to.
    page_id = Column(String, nullable=True)
    ig_user_id = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # --- token access: plaintext to the app, ciphertext in the database ---
    @property
    def access_token(self):
        from app.core.crypto import decrypt
        return decrypt(self._access_token)

    @access_token.setter
    def access_token(self, value):
        from app.core.crypto import encrypt
        self._access_token = encrypt(value)

    @property
    def refresh_token(self):
        from app.core.crypto import decrypt
        return decrypt(self._refresh_token)

    @refresh_token.setter
    def refresh_token(self, value):
        from app.core.crypto import encrypt
        self._refresh_token = encrypt(value)

# --- Creative ---
class Creative(Base):
    __tablename__ = "creatives"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    asset_url = Column(Text, nullable=False)
    asset_type = Column(String, nullable=False)
    asset_name = Column(String, nullable=True)
    render_status = Column(String, default="PENDING")  # PENDING, APPROVED
    copy_text = Column(Text, nullable=True)
    cta_text = Column(String, nullable=True)
    landing_page_url = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# --- Boost (Campaign) ---
class Boost(Base):
    __tablename__ = "boosts"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    ad_account_id = Column(Integer, ForeignKey("ad_accounts.id"), nullable=True)
    address = Column(String, nullable=False)
    tier = Column(String, default="bap_shoot_499")
    main_status = Column(String, default="In Progress")
    go_live_date = Column(String, nullable=True)
    campaign_days = Column(Integer, default=14)
    ad_budget_usd = Column(Float, default=50.0)
    property_facts = Column(Text, nullable=True)
    brand_profile = Column(JSON, default={})
    plan = Column(JSON, default={})
    ad_brief = Column(JSON, default={})
    meta_campaign_id = Column(String, nullable=True)
    stage = Column(String, default="PENDING")  # PENDING, LIVE, COMPLETE
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    launched_at = Column(DateTime(timezone=True), nullable=True)

# --- Post ---
class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True, index=True)
    boost_id = Column(Integer, ForeignKey("boosts.id", ondelete="CASCADE"), nullable=False)
    day = Column(Integer, nullable=False)
    slot = Column(Integer, default=1)
    kind = Column(String, default="static")
    caption = Column(Text, nullable=True)
    hashtags = Column(Text, nullable=True)
    cta = Column(String, nullable=True)
    image_url = Column(Text, nullable=True)
    design_asset_id = Column(Integer, nullable=True)
    client_status = Column(String, default="pending")  # pending, approved, change_requested
    publish_at = Column(String, nullable=True)      # set by the engine, acted on by the publisher
    publish_status = Column(String, default="scheduled")  # scheduled | posting | posted | failed | skipped
    publish_target = Column(String, default="both")  # facebook | instagram | both
    fb_post_id = Column(String, nullable=True)
    ig_media_id = Column(String, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# --- Ad ---
class Ad(Base):
    __tablename__ = "ads"
    id = Column(Integer, primary_key=True, index=True)
    boost_id = Column(Integer, ForeignKey("boosts.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String, nullable=False)  # photo, video
    primary_text = Column(Text, nullable=True)
    headline = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    cta_button = Column(String, default="Learn More")
    creative_asset_ids = Column(JSON, default=[])
    meta_ad_id = Column(String, nullable=True)
    meta_adset_id = Column(String, nullable=True)
    meta_creative_id = Column(String, nullable=True)
    reach = Column(Integer, nullable=True)     # last pulled from the Insights API
    last_error = Column(Text, nullable=True)
    status = Column(String, default="draft")  # draft, submitted, live, paused
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# --- Photo / design asset (the PHOTO INDEX behind the content engine) ---
class Asset(Base):
    __tablename__ = "assets"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    boost_id = Column(Integer, ForeignKey("boosts.id", ondelete="CASCADE"), nullable=True)
    filename = Column(String, nullable=False)      # stored file name under uploads/
    url = Column(Text, nullable=False)             # /uploads/<file>
    original_name = Column(String, nullable=True)  # the name the agent uploaded
    kind = Column(String, default="photo")         # photo | design | reference | headshot
    room = Column(String, nullable=True)
    social_score = Column(String, nullable=True)
    shape = Column(String, nullable=True)          # landscape | portrait | square
    see = Column(Text, nullable=True)              # what is visible
    story = Column(Text, nullable=True)            # the STORY detail the caption is built from
    tags = Column(JSON, default=[])                # POST, ROOM, FEATURE, SCALE, SOCIAL, WHY
    # The image itself. A free-tier container has no persistent disk, so a photo that lives
    # only in uploads/ becomes a 404 at the next deploy; the bytes ride along in the row.
    data = Column(LargeBinary, nullable=True)
    content_type = Column(String, nullable=True)
    tagged_by = Column(String, default="none")     # none | ai | human
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# --- Support Ticket ---
class SupportTicket(Base):
    __tablename__ = "support_tickets"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    subject = Column(String, nullable=False)
    status = Column(String, default="open")  # open, in_progress, resolved, closed
    messages = Column(JSON, default=[])
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())

# --- Password reset (customer accounts) ---
class PasswordReset(Base):
    __tablename__ = "password_resets"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String, nullable=False, index=True)   # only the hash is stored
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# --- Event Log (audit) ---
class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=True)
    boost_id = Column(Integer, nullable=True)
    event_type = Column(String, nullable=False)
    payload = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
