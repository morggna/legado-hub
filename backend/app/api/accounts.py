"""Password accounts and invitation-only self registration."""
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import _check_rate_limit, _rate_limit_keys, _set_private_response, _user_payload
from app.core.public_security import request_uses_https
from app.services.invitations import invitation_service
from app.services.user_auth import auth_service, auth_rate_limiter
from fastapi import HTTPException

router = APIRouter()


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    invitationCode: str = Field(min_length=1, max_length=128)


class InviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    maxUses: int = Field(default=1, ge=1, le=100)
    expiresDays: int = Field(default=7, ge=1, le=90)


@router.post("/api/auth/register")
def register(payload: RegisterRequest, request: Request, response: Response):
    keys = _rate_limit_keys(request, "register", invitation_service.digest(payload.invitationCode))
    _check_rate_limit(keys)
    try:
        user = invitation_service.register(payload.username, payload.password, payload.invitationCode)
    except HTTPException:
        auth_rate_limiter.record_failure(*keys)
        raise
    token = auth_service.create_session(user)
    auth_service.set_session_cookie(response, token, secure=request_uses_https(request))
    _set_private_response(response)
    return {"ok": True, "user": _user_payload(user)}


@router.get("/api/accounts/invitations")
def list_invites(request: Request):
    auth_service.require_admin(request)
    return {"items": invitation_service.list()}


@router.post("/api/accounts/invitations")
def create_invite(payload: InviteRequest, request: Request):
    admin = auth_service.require_admin(request)
    return invitation_service.create(admin.user_id, payload.maxUses, payload.expiresDays)


@router.delete("/api/accounts/invitations/{invitation_id}")
def revoke_invite(invitation_id: str, request: Request):
    auth_service.require_admin(request)
    invitation_service.revoke(invitation_id)
    return {"ok": True}
