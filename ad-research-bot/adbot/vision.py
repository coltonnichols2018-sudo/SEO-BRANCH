"""Stage 2: read the creative, because the API will not hand it over.

The Ad Library response carries no body copy — only an ad id, page id, page
name, an often-blank link title, timestamps and a snapshot URL. Everything
the scoring stage groups on has to be read off the snapshot by a vision pass.

Snapshots are the expensive step, so the queue is deliberately narrow:
newly appeared ads and ads crossing the 30-day mark, each processed once.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Any, Iterable

from . import config
from .models import parse_date, today
from .store import Store

TRIGGER_NEW = "new"
TRIGGER_DAY30 = "day30"

OFFER_TYPES = (
    "price_anchor", "financing", "percent_off", "bogo", "free_add_on", "event",
)
URGENCY = ("deadline", "stock_scarcity", "event", "none")
FORMATS = ("single_image", "carousel", "video", "collection")
STYLES = ("real_room_photo", "studio_white_bg", "graphic_text_overlay", "ugc")
DESTINATIONS = ("messenger", "website", "call", "directions")

# Vision output is free text no matter how firmly you ask for an enum, so
# normalise on the way in. Grouping is worthless if "0% APR" and "financing"
# land in different buckets.
_ALIASES = {
    "offer_type": {
        "price_anchor": ("price anchor", "price point", "priced at", "anchor", "$"),
        "financing": ("financing", "finance", "apr", "payment", "lease", "no credit"),
        "percent_off": ("percent off", "% off", "percent", "discount", "off sale"),
        "bogo": ("bogo", "buy one", "buy 1", "2 for", "twofer"),
        "free_add_on": ("free add", "free gift", "free delivery", "free mattress", "free"),
        "event": ("event", "sale event", "labor day", "holiday", "anniversary", "grand opening"),
    },
    "urgency": {
        "deadline": ("deadline", "ends", "today only", "this week", "last day", "hurry"),
        "stock_scarcity": ("scarcity", "stock", "limited quantity", "while supplies", "sold out"),
        "event": ("event",),
        "none": ("none", "no urgency", "n/a", "-"),
    },
    "ad_format": {
        "single_image": ("single image", "single-image", "static", "image"),
        "carousel": ("carousel",),
        "video": ("video", "reel"),
        "collection": ("collection",),
    },
    "creative_style": {
        "real_room_photo": ("real room", "room photo", "lifestyle", "in-store", "showroom"),
        "studio_white_bg": ("studio", "white background", "white-bg", "cutout"),
        "graphic_text_overlay": ("graphic", "text overlay", "overlay", "banner"),
        "ugc": ("ugc", "user generated", "selfie", "phone video"),
    },
    "destination": {
        "messenger": ("messenger", "message us", "dm", "chat"),
        "website": ("website", "site", "shop now", "landing", "link"),
        "call": ("call", "phone", "tel"),
        "directions": ("directions", "get directions", "map", "visit us", "store"),
    },
}


def canonical(field: str, value: Any) -> str | None:
    """Map a vision answer onto the spec's vocabulary, or keep it as a slug."""
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    aliases = _ALIASES.get(field, {})
    if text in aliases:
        return text
    for canon, needles in aliases.items():
        if text == canon:
            return canon
        for needle in needles:
            if needle in text:
                return canon
    return text.replace(" ", "_")[:48]


@dataclass
class VisionTask:
    ad_id: str
    page_id: str
    page_name: str
    snapshot_url: str | None
    trigger: str
    run_days: int

    def as_json(self) -> dict[str, Any]:
        return {
            "ad_id": self.ad_id,
            "page_id": self.page_id,
            "page_name": self.page_name,
            "ad_snapshot_url": self.snapshot_url,
            "trigger": self.trigger,
            "run_days": self.run_days,
        }


def run_days(ad_row: dict[str, Any], asof: dt.date | None = None) -> int:
    """Days the ad has been live, ended ads frozen at their end date.

    Falls back to first_seen when Meta omits a delivery start, which keeps a
    missing timestamp from inventing a multi-year runner.
    """
    asof = asof or today()
    start = (
        parse_date(ad_row.get("ad_delivery_start_time"))
        or parse_date(ad_row.get("ad_creation_time"))
        or parse_date(ad_row.get("first_seen"))
    )
    if start is None:
        return 0
    end = parse_date(ad_row.get("ended_on")) or asof
    return max(0, (end - start).days)


def queue(store: Store, asof: dt.date | None = None,
          roles: Iterable[str] | None = None) -> list[VisionTask]:
    """Ads awaiting a vision pass, newest-to-oldest within each trigger."""
    asof = asof or today()
    processed = store.vision_ad_ids()
    allowed_pages = None
    if roles is not None:
        allowed_pages = {page.page_id for page in store.pages(list(roles))}

    # "Newly appeared" means we watched it show up — first_seen after the very
    # first poll. Keying off the *latest* poll instead would silently skip every
    # ad that launched between two vision runs, which matters as soon as the
    # vision pass runs weekly rather than daily. Ads already live at the first
    # poll are backfill: they enter at the 30-day mark instead.
    first_poll = store.first_poll_date()
    tasks: list[VisionTask] = []
    for row in store.ads(active_only=False):
        if row["ad_id"] in processed:
            continue  # never re-process
        if allowed_pages is not None and row["page_id"] not in allowed_pages:
            continue
        days = run_days(row, asof)
        first_seen = parse_date(row["first_seen"])
        is_new = bool(first_poll and first_seen and first_seen > first_poll)
        if is_new:
            trigger = TRIGGER_NEW
        elif days >= config.VISION_MATURITY_DAYS:
            trigger = TRIGGER_DAY30
        else:
            continue
        tasks.append(
            VisionTask(
                ad_id=row["ad_id"],
                page_id=row["page_id"],
                page_name=row["page_name"],
                snapshot_url=row["snapshot_url"],
                trigger=trigger,
                run_days=days,
            )
        )
    tasks.sort(key=lambda task: (task.trigger != TRIGGER_DAY30, -task.run_days))
    return tasks


EXTRACTION_PROMPT = """\
Open the ad snapshot URL and extract these fields. Answer with JSON only.

{{
  "ad_id": "{ad_id}",
  "offer_type": one of {offer_types},
  "price_points": ["$498", ...]  // prices named in the creative, [] if none
  "hook": "first line of the primary text, verbatim",
  "urgency": one of {urgency},
  "ad_format": one of {formats},
  "creative_style": one of {styles},
  "cta": "button label, verbatim",
  "destination": one of {destinations}
}}

Snapshot: {snapshot_url}
Page: {page_name}

If the snapshot will not load, return {{"ad_id": "{ad_id}", "error": "unavailable"}}.
"""


def prompt_for(task: VisionTask) -> str:
    return EXTRACTION_PROMPT.format(
        ad_id=task.ad_id,
        snapshot_url=task.snapshot_url or "(missing)",
        page_name=task.page_name,
        offer_types=json.dumps(list(OFFER_TYPES)),
        urgency=json.dumps(list(URGENCY)),
        formats=json.dumps(list(FORMATS)),
        styles=json.dumps(list(STYLES)),
        destinations=json.dumps(list(DESTINATIONS)),
    )


def ingest_vision(store: Store, payload: Any, asof: dt.date | None = None) -> dict[str, int]:
    """Apply vision results; already-processed ads and errors are skipped."""
    rows: list[dict[str, Any]]
    if isinstance(payload, list):
        rows = [row for row in payload if isinstance(row, dict)]
    elif isinstance(payload, dict):
        inner = payload.get("results") or payload.get("vision") or payload.get("data")
        rows = [row for row in inner if isinstance(row, dict)] if isinstance(inner, list) else [payload]
    else:
        rows = []

    processed = store.vision_ad_ids()
    tasks = {task.ad_id: task for task in queue(store, asof)}
    applied = skipped = errored = 0
    for row in rows:
        ad_id = str(row.get("ad_id") or "").strip()
        if not ad_id or ad_id in processed:
            skipped += 1
            continue
        if row.get("error"):
            errored += 1
            continue
        fields = {
            "offer_type": canonical("offer_type", row.get("offer_type")),
            "price_points": row.get("price_points") or [],
            "hook": (row.get("hook") or None),
            "urgency": canonical("urgency", row.get("urgency")),
            "ad_format": canonical("ad_format", row.get("ad_format") or row.get("format")),
            "creative_style": canonical("creative_style", row.get("creative_style")),
            "cta": (row.get("cta") or None),
            "destination": canonical("destination", row.get("destination")),
        }
        trigger = tasks[ad_id].trigger if ad_id in tasks else row.get("trigger") or TRIGGER_NEW
        store.record_vision(ad_id, trigger, fields, processed_on=asof)
        processed.add(ad_id)
        applied += 1
    return {"applied": applied, "skipped": skipped, "errored": errored}
