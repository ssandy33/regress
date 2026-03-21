import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.logging_config import request_id_ctx

logger = logging.getLogger(__name__)

_REQUEST_ID_RE = re.compile(r"^[\w\-]{1,128}$")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs every request with method, path, status, duration, and request_id."""

    async def dispatch(self, request: Request, call_next) -> Response:
        raw_id = request.headers.get("X-Request-ID", "")
        request_id = raw_id if _REQUEST_ID_RE.match(raw_id) else str(uuid.uuid4())
        token = request_id_ctx.set(request_id)

        try:
            start = time.perf_counter()
            response = await call_next(request)
            duration_ms = round((time.perf_counter() - start) * 1000, 2)

            client_ip = request.client.host if request.client else "-"

            logger.info(
                "%s %s %s %.2fms",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                    "client_ip": client_ip,
                },
            )

            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            request_id_ctx.reset(token)
