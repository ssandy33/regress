import contextvars
import logging
import sys

from pythonjsonlogger.json import JsonFormatter

request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


class RequestIdFilter(logging.Filter):
    """Injects request_id from context var into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()  # type: ignore[attr-defined]
        return True


def setup_logging(json_output: bool = True) -> None:
    """Configure root logger with JSON or plain text output.

    Args:
        json_output: Use JSON formatter (True) or plain text (False, for dev/tests).
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Remove existing handlers to avoid duplicate output
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIdFilter())

    if json_output:
        formatter = JsonFormatter(
            fmt="%(asctime)s %(levelname)s %(module)s %(message)s %(request_id)s",
            rename_fields={"levelname": "level", "asctime": "timestamp"},
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s",
            defaults={"request_id": "-"},
        )

    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Suppress uvicorn access logs — our middleware replaces them
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
