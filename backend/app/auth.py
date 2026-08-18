"""校验 Mac AI Worker 的访问令牌。"""

from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings, get_settings


BEARER_SCHEME = HTTPBearer(auto_error=False)


def require_ai_worker(
    credentials: HTTPAuthorizationCredentials | None = Depends(BEARER_SCHEME),
    settings: Settings = Depends(get_settings),
) -> None:
    """验证 AI Worker 请求。

    功能说明：要求请求携带与后端配置一致的 Bearer Token；服务端未配置令牌时拒绝开放任务接口。
    参数 credentials：FastAPI 从 Authorization 请求头解析出的认证信息。
    参数 settings：后端运行配置。
    返回值：验证成功时无返回值；失败时抛出 HTTP 异常。
    """

    if not settings.ai_worker_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI Worker 访问令牌尚未配置",
        )
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not hmac.compare_digest(credentials.credentials, settings.ai_worker_token)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AI Worker 认证失败",
            headers={"WWW-Authenticate": "Bearer"},
        )
