from typing import Optional


def to_float(value, default: Optional[float] = 0.0) -> Optional[float]:
    """Null-safe float coercion for sparse API responses."""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def to_int(value, default: int = 0) -> int:
    """Null-safe int coercion for sparse API responses."""
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default
