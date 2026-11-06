import os
from pathlib import Path
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Load this app's own .env first, whatever directory uvicorn was started from.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")
load_dotenv()

class Settings(BaseSettings):
    SECRET_KEY: str = os.getenv("SECRET_KEY", "resmara-dev-secret-key-change-in-prod")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./resmara.db")
    ENV: str = os.getenv("RESMARA_ENV", "development")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("RESMARA_OPENAI_MODEL", "gpt-4.1-mini")
    # Content-engine models, verbatim from the handoff spec (docs 10/11/12):
    # R1/R3 research + R4 plan = responses/chat on the big model, R2 brand = the mini model,
    # D1 design = image edit, C1 check = vision. Each is overridable without a code change.
    OPENAI_MODEL_RESEARCH: str = os.getenv("RESMARA_MODEL_RESEARCH", "gpt-5.5")
    OPENAI_MODEL_PLAN: str = os.getenv("RESMARA_MODEL_PLAN", "gpt-5.5")
    OPENAI_MODEL_BRAND: str = os.getenv("RESMARA_MODEL_BRAND", "gpt-5.4-mini")
    OPENAI_MODEL_DESIGN: str = os.getenv("RESMARA_MODEL_DESIGN", "gpt-image-1")
    OPENAI_MODEL_CHECK: str = os.getenv("RESMARA_MODEL_CHECK", "gpt-5.4-mini")
    # Offline/mock mode: no outbound OpenAI or Meta calls, deterministic fixtures.
    # Never silently on in production — the engine reports source="offline" when it is.
    SIMULATE: bool = os.getenv("RESMARA_SIMULATE", "").lower() in ("1", "true", "yes")

    # Private beta: the site is on a public domain before launch, so creating an account is
    # gated. Either the address is on the allowlist, or the caller knows SIGNUP_CODE. Both
    # unset = open signup (local development and tests). See app/services/access.py.
    SIGNUP_EMAILS: str = os.getenv("RESMARA_SIGNUP_EMAILS", "")
    SIGNUP_CODE: str = os.getenv("RESMARA_SIGNUP_CODE", "")

    # Where this app is publicly reachable. Needed for Meta callbacks AND for Instagram,
    # which fetches post media by URL (Graph has no direct file upload for IG feed posts).
    # Hosts that inject their own public origin need no configuration at all: Render sets
    # RENDER_EXTERNAL_URL, Railway RAILWAY_PUBLIC_DOMAIN. A reverse-proxied box sets the var.
    PUBLIC_BASE_URL: str = (
        os.getenv("RESMARA_PUBLIC_BASE_URL")
        or os.getenv("RENDER_EXTERNAL_URL")
        or (os.getenv("RAILWAY_PUBLIC_DOMAIN") and "https://" + os.getenv("RAILWAY_PUBLIC_DOMAIN"))
        or "https://sport.taila73942.ts.net/resmara"
    ).rstrip("/")

    # Graph API. Base is overridable so tests can point at a local mock server.
    META_API_VERSION: str = os.getenv("META_API_VERSION", "v19.0")
    GRAPH_API_BASE: str = os.getenv("GRAPH_API_BASE", "")
    # Page + IG account the Boost posts to when the ad account row doesn't carry them.
    META_PAGE_ID: str = os.getenv("META_PAGE_ID", "")
    META_IG_ID: str = os.getenv("META_IG_ID", "")
    # Bearer for the scheduler-triggered publisher/report entrypoints.
    PUBLISH_TOKEN: str = os.getenv("RESMARA_PUBLISH_TOKEN", "")
    TIKTOK_CLIENT_ID: str = os.getenv("TIKTOK_CLIENT_ID", "")
    TIKTOK_CLIENT_SECRET: str = os.getenv("TIKTOK_CLIENT_SECRET", "")
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")

    @property
    def graph_base(self) -> str:
        return self.GRAPH_API_BASE or f"https://graph.facebook.com/{self.META_API_VERSION}"

    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "./uploads")
    META_CLIENT_ID: str = os.getenv("META_CLIENT_ID", "")
    META_CLIENT_SECRET: str = os.getenv("META_CLIENT_SECRET", "")
    # The app is mounted behind the router at /resmara/, so the callback must carry
    # that prefix or Meta's redirect 404s. Override with META_REDIRECT_URI for a real domain.
    META_REDIRECT_URI: str = os.getenv("META_REDIRECT_URI") or PUBLIC_BASE_URL + "/api/oauth/meta/callback"
    TIKTOK_CLIENT_ID: str = os.getenv("TIKTOK_CLIENT_ID", "")
    TIKTOK_CLIENT_SECRET: str = os.getenv("TIKTOK_CLIENT_SECRET", "")
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")

settings = Settings()
