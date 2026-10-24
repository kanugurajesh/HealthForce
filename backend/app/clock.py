from datetime import date

_override: date | None = None


def today() -> date:
    """The as-of date for all expiration and readiness rules (overridable in tests)."""
    return _override or date.today()


def set_today(value: date | None) -> None:
    global _override
    _override = value
