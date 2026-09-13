"""Record shapes shared across stages, plus response normalisation.

The Ad Library returns slightly different envelopes depending on whether a
pull came from the Graph API directly or from an MCP tool result, so every
inbound payload lands here first and leaves as a list of `Ad`.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from . import config


def today() -> dt.date:
    return dt.date.today()


def parse_date(value: Any) -> dt.date | None:
    """Accept the several date shapes Meta mixes into one response."""
    if value in (None, "", False):
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    text = str(value).strip()
    if not text:
        return None
    # "2026-09-03T12:41:22+0000", "2026-09-03 12:41:22", "2026-09-03"
    text = text.replace("Z", "+00:00")
    for candidate in (text, text.split("T")[0], text.split(" ")[0]):
        try:
            return dt.date.fromisoformat(candidate)
        except ValueError:
            continue
    try:
        return dt.datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S").date()
    except ValueError:
        return None


def iso(value: dt.date | None) -> str | None:
    return value.isoformat() if value else None


@dataclass
class PageSeed:
    page_id: str
    page_name: str
    role: str = config.ROLE_OUT_OF_MARKET
    metro: str | None = None
    note: str | None = None
    verified: bool = True

    def as_json(self) -> dict[str, Any]:
        return {
            "page_id": self.page_id,
            "page_name": self.page_name,
            "role": self.role,
            "metro": self.metro,
            "note": self.note,
            "verified": self.verified,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "PageSeed":
        return cls(
            page_id=str(raw["page_id"]).strip(),
            page_name=str(raw.get("page_name", "")).strip(),
            role=raw.get("role") or config.ROLE_OUT_OF_MARKET,
            metro=raw.get("metro") or None,
            note=raw.get("note") or None,
            verified=bool(raw.get("verified", True)),
        )


@dataclass
class Ad:
    ad_id: str
    page_id: str
    page_name: str = ""
    link_title: str | None = None
    ad_creation_time: dt.date | None = None
    ad_delivery_start_time: dt.date | None = None
    snapshot_url: str | None = None

    def start_date(self) -> dt.date | None:
        return self.ad_delivery_start_time or self.ad_creation_time


@dataclass
class Pull:
    """One `ads_library_search` response, already normalised."""

    ads: list[Ad] = field(default_factory=list)
    page_id: str | None = None
    estimated_total_count: int | None = None
    search_terms: str | None = None
    observed_on: dt.date | None = None


def _first_title(raw: dict[str, Any]) -> str | None:
    for key in ("ad_creative_link_title", "ad_creative_link_titles", "link_title"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, str) and item.strip():
                    return item.strip()
    return None


def ad_from_json(raw: dict[str, Any]) -> Ad | None:
    ad_id = raw.get("ad_id") or raw.get("id") or raw.get("ad_archive_id")
    page_id = raw.get("page_id") or raw.get("pageId")
    if not ad_id or not page_id:
        return None
    return Ad(
        ad_id=str(ad_id),
        page_id=str(page_id),
        page_name=str(raw.get("page_name") or raw.get("pageName") or "").strip(),
        link_title=_first_title(raw),
        ad_creation_time=parse_date(raw.get("ad_creation_time")),
        ad_delivery_start_time=parse_date(raw.get("ad_delivery_start_time")),
        snapshot_url=raw.get("ad_snapshot_url") or raw.get("snapshot_url"),
    )


def _ad_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "ads", "results", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def _count(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    for key in ("estimated_total_count", "total_count", "estimated_ad_count", "count"):
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def normalize_pull(payload: Any, *, page_id: str | None = None,
                   observed_on: dt.date | None = None) -> Pull:
    """Turn one raw response into a `Pull`, whatever envelope it arrived in."""
    rows = _ad_rows(payload)
    ads = [ad for ad in (ad_from_json(row) for row in rows) if ad is not None]
    meta = payload if isinstance(payload, dict) else {}
    resolved_page = page_id or meta.get("page_id")
    if resolved_page is None and len({ad.page_id for ad in ads}) == 1:
        resolved_page = ads[0].page_id
    return Pull(
        ads=ads,
        page_id=str(resolved_page) if resolved_page else None,
        estimated_total_count=_count(meta),
        search_terms=meta.get("search_terms"),
        observed_on=parse_date(meta.get("observed_on")) or observed_on,
    )


def normalize_file(payload: Any, *, observed_on: dt.date | None = None) -> list[Pull]:
    """A drop file may hold one response or a batch of them under `pulls`."""
    if isinstance(payload, dict) and isinstance(payload.get("pulls"), list):
        batch_date = parse_date(payload.get("observed_on")) or observed_on
        pulls: list[Pull] = []
        for entry in payload["pulls"]:
            if not isinstance(entry, dict):
                continue
            body = entry.get("response", entry)
            pulls.append(
                normalize_pull(
                    body,
                    page_id=entry.get("page_id"),
                    observed_on=parse_date(entry.get("observed_on")) or batch_date,
                )
            )
        return pulls
    return [normalize_pull(payload, observed_on=observed_on)]


def median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("median of empty sequence")
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def dedupe(items: Iterable[str]) -> list[str]:
    seen: dict[str, None] = {}
    for item in items:
        if item:
            seen.setdefault(item, None)
    return list(seen)
