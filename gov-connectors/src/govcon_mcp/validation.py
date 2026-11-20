"""Reusable, strict input types and output shaping.

Tool parameters are declared with these ``Annotated`` types so the MCP SDK
publishes tight JSON Schemas *and* pydantic rejects bad input before any
network call. Free text is length-capped and stripped of characters SAM.gov
and SoQL treat as operators.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Any, Iterable

from pydantic import Field

from .errors import InvalidInput

IsoDate = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="Date as YYYY-MM-DD")]
StateCode = Annotated[str, Field(pattern=r"^[A-Z]{2}$", description="Two-letter USPS state/territory code, e.g. VA")]
Naics = Annotated[str, Field(pattern=r"^\d{2,6}$", description="NAICS code (2-6 digits)")]
Psc = Annotated[str, Field(pattern=r"^[A-Z0-9]{1,4}$", description="Product/Service Code (1-4 chars)")]
Uei = Annotated[str, Field(pattern=r"^[A-Z0-9]{12}$", description="12-character SAM Unique Entity ID")]
Cage = Annotated[str, Field(pattern=r"^[A-Z0-9]{5}$", description="5-character CAGE code")]
ShortText = Annotated[str, Field(min_length=2, max_length=200)]

# Characters SAM.gov rejects in parameter values, plus control chars.
_SAM_FORBIDDEN = re.compile(r"[&|{}^\\\x00-\x1f]")


def clean_text(value: str | None, *, max_len: int = 200) -> str | None:
    """Trim, cap length, and remove operator/control characters from free text."""
    if value is None:
        return None
    value = _SAM_FORBIDDEN.sub(" ", value).strip()
    return value[:max_len] or None


def parse_iso(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise InvalidInput(f"{field} must be a real date in YYYY-MM-DD format") from None


def check_range(start: date, end: date, *, max_days: int | None = None, label: str = "date range") -> None:
    if end < start:
        raise InvalidInput(f"{label}: end date is before start date")
    if max_days is not None and (end - start).days > max_days:
        raise InvalidInput(f"{label}: span may not exceed {max_days} days")


def to_mmddyyyy(d: date) -> str:
    return d.strftime("%m/%d/%Y")


def project(record: dict[str, Any], keep: Iterable[str], *, max_text: int = 1500) -> dict[str, Any]:
    """Keep only allowlisted fields (data minimisation) and truncate long text."""
    out: dict[str, Any] = {}
    for key in keep:
        if key in record and record[key] not in (None, ""):
            value = record[key]
            if isinstance(value, str) and len(value) > max_text:
                value = value[:max_text] + "...[truncated]"
            out[key] = value
    return out


def envelope(source: str, results: list[Any], *, total: Any = None, source_url: str | None = None,
             notes: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    """Standard tool response wrapper with provenance.

    ``untrusted_content`` reminds the calling agent that text fields come from
    third-party records and must be treated as data, never as instructions.
    """
    body: dict[str, Any] = {
        "source": source,
        "returned": len(results),
        "total_available": total,
        "results": results,
        "untrusted_content": True,
    }
    if source_url:
        body["source_url"] = source_url
    if notes:
        body["notes"] = notes
    body.update(extra)
    return body
