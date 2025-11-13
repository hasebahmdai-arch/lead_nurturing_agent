from __future__ import annotations

from ninja import NinjaAPI
from django.contrib.auth import authenticate
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja_jwt.tokens import RefreshToken

from agents.api import router as agent_router
from campaigns.api import router as campaigns_router
from crm.api import router as crm_router


api = NinjaAPI(
    title="Lead Nurturing Agent API",
    version="1.0.0",
    docs_url="/docs",
)


class TokenObtainPairPayload(Schema):
    username: str
    password: str


class TokenRefreshPayload(Schema):
    refresh: str


class TokenResponse(Schema):
    access: str
    refresh: str


auth_router = Router(tags=["auth"])


@auth_router.post("/token", response=TokenResponse, auth=None)
def obtain_token(request, payload: TokenObtainPairPayload):
    user = authenticate(request, username=payload.username, password=payload.password)
    if not user:
        raise HttpError(401, "Invalid credentials")
    refresh = RefreshToken.for_user(user)
    return TokenResponse(access=str(refresh.access_token), refresh=str(refresh))


@auth_router.post("/token/refresh", response=TokenResponse, auth=None)
def refresh_token(request, payload: TokenRefreshPayload):
    try:
        refresh = RefreshToken(payload.refresh)
    except Exception as exc:  # noqa: BLE001
        raise HttpError(401, "Invalid refresh token") from exc
    return TokenResponse(access=str(refresh.access_token), refresh=payload.refresh)


api.add_router("/auth/", auth_router)
api.add_router("/leads/", crm_router)
api.add_router("/campaigns/", campaigns_router)
api.add_router("/agent/", agent_router)


@api.get("/health", tags=["health"])
def health_check(request):
    return {"status": "ok"}

