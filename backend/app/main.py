from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app import auth, profile, records
from app.config import get_settings

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class OriginCheckMiddleware(BaseHTTPMiddleware):
    """CSRF 防护：改变数据的请求必须来自允许的来源。"""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in UNSAFE_METHODS and request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            if origin is None:
                referer = request.headers.get("referer", "")
                origin = "/".join(referer.split("/")[:3]) if referer else None
            if origin is None or origin.rstrip("/") not in get_settings().allowed_origins:
                return JSONResponse({"detail": "请求来源不被允许"}, status_code=403)
        return await call_next(request)


app = FastAPI(
    title="HealthOS API",
    version="0.2.0",
    description="HealthOS 家庭版后端 API。所有健康数据接口都使用 HttpOnly 会话 Cookie，并从认证主体派生所有者。",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(OriginCheckMiddleware)
app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(records.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
