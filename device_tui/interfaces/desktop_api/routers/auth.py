"""Internal inventory authentication routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from device_tui.application import ApplicationError
from device_tui.domain.devices.repository import RepositoryError

from ..dependencies import authorize, get_context
from ..models import InternalAuthLoginRequest, InternalAuthPasswordModel, InternalAuthStatusModel
from ..serializers import internal_auth_status_model

INTERNAL_AUTH_USERNAME_SETTING = "internal_auth.username"
INTERNAL_AUTH_CID_SETTING = "internal_auth.cid"
INTERNAL_AUTH_AUTO_LOGIN_SETTING = "internal_auth.auto_login"
INTERNAL_AUTH_AUTO_LOGIN_ERROR_SETTING = "internal_auth.auto_login_error"


def _setting_key(base: str, source_id: str) -> str:
    return f"{base}.{source_id}"


def _secret_key(source_id: str) -> str:
    return f"internal-auth/{source_id}/password"


router = APIRouter(prefix="/api/v1", tags=["internal-auth"], dependencies=[Depends(authorize)])


@router.get("/internal-auth", response_model=InternalAuthStatusModel)
async def internal_auth_status(ctx=Depends(get_context)) -> InternalAuthStatusModel:
    try:
        return internal_auth_status_model(ctx.repository, ctx.desktop.settings, ctx.desktop.secrets, source_id=ctx.repository.active_source)
    except RepositoryError as exc:
        raise ApplicationError(str(exc)) from exc


@router.get("/internal-auth/password", response_model=InternalAuthPasswordModel)
async def internal_auth_password(ctx=Depends(get_context)) -> InternalAuthPasswordModel:
    return InternalAuthPasswordModel(password=ctx.desktop.secrets.get(_secret_key(ctx.repository.active_source)) or "")


@router.post("/internal-auth/login", response_model=InternalAuthStatusModel)
async def internal_auth_login(request: InternalAuthLoginRequest, ctx=Depends(get_context)) -> InternalAuthStatusModel:
    repo = ctx.repository
    desktop = ctx.desktop
    source_id = repo.active_source
    username_key = _setting_key(INTERNAL_AUTH_USERNAME_SETTING, source_id)
    cid_key = _setting_key(INTERNAL_AUTH_CID_SETTING, source_id)
    auto_key = _setting_key(INTERNAL_AUTH_AUTO_LOGIN_SETTING, source_id)
    error_key = _setting_key(INTERNAL_AUTH_AUTO_LOGIN_ERROR_SETTING, source_id)
    password_key = _secret_key(source_id)
    username = request.username.strip()
    cid = request.cid.strip()
    if not username or not cid:
        raise ApplicationError("账号和 CID 不能为空。")
    password = request.password
    if not password and request.use_saved_password:
        password = desktop.secrets.get(password_key) or ""
    if not password:
        raise ApplicationError("请输入密码，或先启用记住登录。")
    try:
        status = repo.login_internal(username, password, cid)
    except RepositoryError as exc:
        raise ApplicationError(str(exc)) from exc
    desktop.settings.set(username_key, username)
    desktop.settings.set(cid_key, cid)
    remember = request.remember or request.auto_login
    warning = ""
    try:
        if remember:
            desktop.secrets.set(password_key, password)
        else:
            desktop.secrets.delete(password_key)
    except ApplicationError as exc:
        remember = False
        warning = exc.message
    desktop.settings.set(auto_key, bool(request.auto_login and remember))
    desktop.settings.delete(error_key)
    return internal_auth_status_model(repo, desktop.settings, desktop.secrets, status, credential_warning=warning, source_id=source_id)


@router.delete("/internal-auth/session", response_model=InternalAuthStatusModel)
async def internal_auth_logout(ctx=Depends(get_context)) -> InternalAuthStatusModel:
    repo = ctx.repository
    desktop = ctx.desktop
    source_id = repo.active_source
    auto_key = _setting_key(INTERNAL_AUTH_AUTO_LOGIN_SETTING, source_id)
    error_key = _setting_key(INTERNAL_AUTH_AUTO_LOGIN_ERROR_SETTING, source_id)
    try:
        status = repo.logout_internal()
    except RepositoryError as exc:
        raise ApplicationError(str(exc)) from exc
    desktop.settings.set(auto_key, False)
    desktop.settings.delete(error_key)
    return internal_auth_status_model(repo, desktop.settings, desktop.secrets, status, source_id=source_id)
