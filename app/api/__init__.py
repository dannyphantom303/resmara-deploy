from fastapi import APIRouter

api_router = APIRouter()

from app.api import auth
from app.api import resmara
from app.api import oauth
from app.api import content
from app.api import engine
from app.api import billing
from app.api import costs

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(resmara.router, prefix="", tags=["resmara"])
api_router.include_router(oauth.router, prefix="/oauth", tags=["oauth"])
api_router.include_router(content.router, prefix="/content", tags=["content"])
# Campaign engine: /api/boosts/{id}/build|approve|launch, /api/adflow/credits/precheck/
api_router.include_router(engine.router, prefix="", tags=["engine"])
# Billing: /api/billing/config|checkout|webhook|orders. A campaign is $49, bought outright.
api_router.include_router(billing.router, prefix="", tags=["billing"])
# Start-up costs: /api/admin/costs — what the project cost, who paid, receipts, subscriptions.
api_router.include_router(costs.router, prefix="", tags=["costs"])
