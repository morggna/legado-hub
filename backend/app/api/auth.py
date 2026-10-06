"""User auth APIs for subscription/library/admin pages.

Copyright (c) 2026 moo. All rights reserved.
"""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from app.services.audit import audit_service
from app.services.user_auth import (
    AuthRateLimitError,
    auth_rate_limiter,
    auth_service,
)
from app.core.public_security import request_client_ip, request_uses_https

_common_router = APIRouter(prefix="/api/auth")
_access_router = APIRouter(prefix="/api/auth")
_admin_router = APIRouter(prefix="/api/auth")


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdminLoginRequest(_StrictRequest):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class AccessCodeRequest(_StrictRequest):
    access_code: str = Field(alias="accessCode", min_length=1, max_length=256)


class ChangePasswordRequest(_StrictRequest):
    current_password: str = Field(alias="currentPassword", min_length=1, max_length=128)
    new_password: str = Field(alias="newPassword", min_length=8, max_length=128)


def _client_ip(request: Request) -> str:
    return request_client_ip(request)


def _rate_limit_keys(request: Request, kind: str, identifier: str) -> tuple[str, str]:
    return f"{kind}:ip:{_client_ip(request)}", f"{kind}:id:{identifier}"


def _check_rate_limit(keys: tuple[str, str]) -> None:
    try:
        auth_rate_limiter.check(*keys)
    except AuthRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(exc.retry_after_seconds)},
            detail={
                "code": "auth_rate_limited",
                "message": "认证尝试过于频繁",
                "retryable": True,
                "retryAfterSeconds": exc.retry_after_seconds,
            },
        ) from exc


def _user_payload(user) -> dict:
    return {
        "userId": user.user_id,
        "username": user.username,
        "role": user.role,
        "disabled": user.disabled,
    }


def _set_private_response(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@_common_router.get("/entrypoint")
def entrypoint(request: Request, response: Response):
    """Return the network entrypoint serving the current request."""
    _set_private_response(response)
    return {"entrypoint": str(getattr(request.app.state, "entrypoint", "combined")), "authMode": str(getattr(request.app.state, "auth_mode", "account_invite"))}


@_admin_router.post("/login")
def login(payload: AdminLoginRequest, request: Request, response: Response):
    username = payload.username.strip()
    keys = _rate_limit_keys(request, "admin", username)
    _check_rate_limit(keys)
    try:
        user = auth_service.authenticate(username=username, password=payload.password)
        if (str(getattr(request.app.state, "entrypoint", "combined")) == "admin" or getattr(request.app.state, "auth_mode", "account_invite") == "legacy") and not user.is_admin:
            raise HTTPException(status_code=401, detail="用户名或密码错误")
    except HTTPException as exc:
        if exc.status_code in {401, 403}:
            auth_rate_limiter.record_failure(*keys)
        raise
    session_id = auth_service.create_session(user)
    auth_service.set_session_cookie(response, session_id, secure=request_uses_https(request))
    _set_private_response(response)
    return {"ok": True, "user": _user_payload(user)}


def _safe_next_path(value: str | None) -> str:
    """Allow only same-site relative paths (block open redirects)."""
    raw = str(value or "").strip() or "/console/subscription"
    if not raw.startswith("/") or raw.startswith("//"):
        return "/console/subscription"
    parsed = urlparse(raw)
    if parsed.scheme or parsed.netloc:
        return "/console/subscription"
    path = parsed.path or "/console/subscription"
    if not path.startswith("/"):
        return "/console/subscription"
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{path}{query}"


def _authenticate_access_code(access_code: str, request: Request) -> tuple[object, str]:
    """Validate access code and create a session. Returns (user, session_id)."""
    identifier = auth_service.access_code_identifier(access_code)
    keys = _rate_limit_keys(request, "access", identifier)
    _check_rate_limit(keys)
    try:
        user = auth_service.authenticate_access_code(access_code)
    except HTTPException as exc:
        if exc.status_code in {401, 403}:
            auth_rate_limiter.record_failure(*keys)
        raise
    session_id = auth_service.create_session(user)
    audit_service.record(
        action="user.access_code.redeem",
        actor_user_id=user.user_id,
        actor_role=user.role,
        target_type="user",
        target_id=user.user_id,
        summary={"authenticated": True},
    )
    return user, session_id


@_access_router.post("/access/redeem")
def redeem_access_code(payload: AccessCodeRequest, request: Request, response: Response):
    user, session_id = _authenticate_access_code(payload.access_code, request)
    auth_service.set_session_cookie(response, session_id, secure=request_uses_https(request))
    _set_private_response(response)
    return {
        "ok": True,
        "token": session_id,
        "expiresAt": auth_service.session_expires_at(session_id),
        "user": _user_payload(user),
    }


@_access_router.get("/access/enter")
def enter_with_access_code(
    request: Request,
    code: str = "",
    next: str = "/console/subscription",
):
    """Browser entry: exchange access code for session cookie and redirect.

    Used by personal subscription links and the Reading「订阅管理」button so
    users do not re-type the access code in the web console.
    """
    access_code = str(code or "").strip()
    target = _safe_next_path(next)
    if not access_code:
        return RedirectResponse(url=f"/login?next={target}", status_code=302)
    try:
        _user, session_id = _authenticate_access_code(access_code, request)
    except HTTPException:
        return RedirectResponse(url=f"/login?next={target}&error=invalid_code", status_code=302)
    redirect = RedirectResponse(url=target, status_code=302)
    auth_service.set_session_cookie(redirect, session_id, secure=request_uses_https(request))
    redirect.headers["Cache-Control"] = "no-store"
    return redirect


@_common_router.post("/logout")
def logout(request: Request, response: Response):
    session_id = auth_service.session_token_from_request(request)
    auth_service.destroy_session(session_id)
    auth_service.clear_session_cookie(response)
    _set_private_response(response)
    return {"ok": True}


@_access_router.post("/access/logout")
def access_logout(request: Request, response: Response):
    return logout(request, response)


@_admin_router.post("/change-password")
def change_password(payload: ChangePasswordRequest, request: Request, response: Response):
    user = auth_service.require_user(request) if getattr(request.app.state, "auth_mode", "legacy") == "account_invite" else auth_service.require_admin(request)
    auth_service.change_password(
        user=user,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    auth_service.clear_session_cookie(response)
    _set_private_response(response)
    return {"ok": True, "reauthenticationRequired": True}


@_common_router.get("/me")
def me(request: Request, response: Response):
    _set_private_response(response)
    user = auth_service.current_user(request)
    entrypoint_name = str(getattr(request.app.state, "entrypoint", "combined"))
    if not user or (entrypoint_name == "admin" and not user.is_admin):
        return {"authenticated": False, "user": None}
    return {
        "authenticated": True,
        "user": _user_payload(user),
    }


@_access_router.get("/access/me")
def access_me(request: Request, response: Response):
    _set_private_response(response)
    user = auth_service.require_user(request)
    return {"authenticated": True, "user": _user_payload(user)}


router = APIRouter()
router.include_router(_common_router)
router.include_router(_access_router)
router.include_router(_admin_router)

public_router = APIRouter()
public_router.include_router(_common_router)
public_router.include_router(_access_router)

admin_router = APIRouter()
admin_router.include_router(_common_router)
admin_router.include_router(_admin_router)

account_router = APIRouter()
account_router.include_router(_common_router)
account_router.include_router(_admin_router)
