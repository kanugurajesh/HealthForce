"""Deterministic date parsing for extracted date text.

The extraction model returns dates exactly as printed; only this module turns them into
dates. Ambiguous or unrecognized text yields None (→ manual review) instead of a guess.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

Precision = Literal["day", "month", "year"]

_MONTHS = {name.lower(): i for i in range(1, 13) for name in (calendar.month_name[i], calendar.month_abbr[i], calendar.month_abbr[i] + ".")}
_MONTHS["sept"] = 9
_MONTHS["sept."] = 9

PRESENT_WORDS = {"present", "current", "now", "today", "currently"}


@dataclass(frozen=True)
class ParsedDate:
    value: date
    precision: Precision


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def parse_date_text(text: str | None, *, period_end: bool = False) -> ParsedDate | None:
    """Parse a printed date.

    `period_end=True` resolves partial dates to the end of the period (an expiration of
    "03/2027" means valid through 31 Mar 2027 — the convention on life-support cards);
    otherwise partial dates resolve to the start of the period.
    """
    if not text:
        return None
    s = text.strip().strip(".,;:()").strip()
    if not s:
        return None

    def build(y: int, m: int, d: int | None, precision: Precision) -> ParsedDate | None:
        try:
            if d is not None:
                return ParsedDate(date(y, m, d), precision)
            if precision == "month":
                return ParsedDate(_month_end(y, m) if period_end else date(y, m, 1), "month")
            return ParsedDate(date(y, 12, 31) if period_end else date(y, 1, 1), "year")
        except ValueError:
            return None

    if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s):  # 2027-03-31
        return build(int(m[1]), int(m[2]), int(m[3]), "day")
    if m := re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", s):  # 03/31/2027 (US order)
        return build(int(m[3]), int(m[1]), int(m[2]), "day")
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})", s):  # 2027-03
        return build(int(m[1]), int(m[2]), None, "month")
    if m := re.fullmatch(r"(\d{1,2})[/-](\d{4})", s):  # 03/2027
        return build(int(m[2]), int(m[1]), None, "month")
    if m := re.fullmatch(r"([A-Za-z]{3,9}\.?)\s+(\d{1,2}),?\s+(\d{4})", s):  # March 31, 2027
        month = _MONTHS.get(m[1].lower())
        return build(int(m[3]), month, int(m[2]), "day") if month else None
    if m := re.fullmatch(r"(\d{1,2})\s+([A-Za-z]{3,9}\.?)\s+(\d{4})", s):  # 31 March 2027
        month = _MONTHS.get(m[2].lower())
        return build(int(m[3]), month, int(m[1]), "day") if month else None
    if m := re.fullmatch(r"([A-Za-z]{3,9}\.?)\s+(\d{4})", s):  # March 2027
        month = _MONTHS.get(m[1].lower())
        return build(int(m[2]), month, None, "month") if month else None
    if m := re.fullmatch(r"(\d{4})", s):  # 2027
        return build(int(m[1]), 1, None, "year")
    return None


def is_present(text: str | None) -> bool:
    return bool(text) and text.strip().strip(".").lower() in PRESENT_WORDS  # type: ignore[union-attr]
