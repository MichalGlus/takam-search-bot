"""Validity (in force / expired) computed from dates.

The API's `isvalid` flag is not usable (it is false for every instruction), and
`versionnumber` does not match the number of versions returned, so neither is used.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def is_in_force(valid_from: date | None, valid_to: date | None, today: date) -> bool:
    if valid_from and valid_from > today:
        return False
    if valid_to and valid_to < today:
        return False
    return True


def current_version(versions: list[dict[str, Any]], today: date) -> dict[str, Any] | None:
    """Pick the version whose content should be indexed.

    Prefer a version in force today (highest version number wins); otherwise the
    most recent one, so expired documents can still be shown when asked for.
    Versions without a content id cannot be downloaded and are ignored.
    """
    usable = [v for v in versions if v.get("rtn_contentversionid__c")]
    if not usable:
        return None
    in_force = [
        v
        for v in usable
        if is_in_force(parse_date(v.get("rtn_validfrom__c")), parse_date(v.get("rtn_validto__c")), today)
    ]
    pool = in_force or usable
    return max(
        pool,
        key=lambda v: (
            v.get("rtn_versionnumber__c") or 0,
            parse_date(v.get("rtn_validfrom__c")) or date.min,
        ),
    )
