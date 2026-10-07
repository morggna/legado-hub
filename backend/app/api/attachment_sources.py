"""Personal account-gated attachment sources; debit requires an explicit token."""
import asyncio
from collections import Counter
from contextlib import asynccontextmanager

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.services.txtnovel_import import txtnovel_import
from app.services.user_auth import auth_service

router = APIRouter(prefix="/attachments/txtnovel")
_active = Counter()


@asynccontextmanager
async def one_operation(user_id):
    if _active[user_id]:
        raise HTTPException(429, "书源正在处理请求，请稍后再试")
    _active[user_id] += 1
    try:
        yield
    finally:
        del _active[user_id]


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=128)


class DownloadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmationToken: str = Field(min_length=1, max_length=3000)


@router.get("/account")
def account(request: Request):
    user = auth_service.require_user(request)
    return txtnovel_import.status(user.user_id)


@router.post("/account")
async def bind(payload: LoginRequest, request: Request):
    user = auth_service.require_user(request)
    async with one_operation(user.user_id):
        return await txtnovel_import.login(user.user_id, payload.username, payload.password.get_secret_value())


@router.delete("/account")
async def unbind(request: Request):
    user = auth_service.require_user(request)
    async with one_operation(user.user_id):
        await asyncio.to_thread(txtnovel_import.store.remove, user.user_id)
    return {"ok": True}


@router.get("/preview")
async def preview(request: Request, threadId: str = Query(pattern=r"^[1-9]\d{0,11}$")):
    user = auth_service.require_user(request)
    async with one_operation(user.user_id):
        return await txtnovel_import.preview(user.user_id, threadId)


@router.post("/download")
async def download(payload: DownloadRequest, request: Request):
    user = auth_service.require_user(request)
    async with one_operation(user.user_id):
        return await txtnovel_import.download(user.user_id, payload.confirmationToken)
