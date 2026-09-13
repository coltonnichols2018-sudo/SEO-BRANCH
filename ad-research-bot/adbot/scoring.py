"""Inferring what works without any performance data.

Meta publishes no spend, impressions, CTR or ROAS, so every judgement here
rests on three proxies: how long an ad stayed live, how fast a page added
ads, and how quickly an ad disappeared. Each proxy is weak alone; the
cross-market rule is what turns them into a signal.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from . import config
from .models import median, parse_date, today
from .store import Store
from .vision import run_days

STOPWORDS = {"the", "a", "an", "and", "or", "of", "for", "to", "in", "at", "on", "your"}

_OFFER_LABELS = {
    "price_anchor": "Price anchor",
    "financing": "Financing",
    "percent_off": "% off",
    "bogo": "BOGO",
    "free_add_on": "Free add-on",
    "event": "Event",
}
_URGENCY_LABELS = {
    "deadline": "deadline",
    "stock_scarcity": "stock scarcity",
    "event": "event",
    "none": "no urgency",
}


def angle_of(ad_row: dict[str, Any], vision_row: dict[str, Any] | None) -> tuple[str, str] | None:
    """Resolve an ad to an angle key and a human label.

    Vision fields are the real definition of an angle. Before a snapshot has
    been read, the link title is a usable stand-in — it is often blank, and
    those ads simply do not group.
    """
    if vision_row and vision_row.get("offer_type"):
        offer = vision_row["offer_type"]
        urgency = vision_row.get("urgency") or "none"
        label = (
            f"{_OFFER_LABELS.get(offer, offer.replace('_', ' ').title())}"
            f" + {_URGENCY_LABELS.get(urgency, urgency.replace('_', ' '))}"
        )
        return f"{offer}|{urgency}", label
    title = (ad_row.get("link_title") or "").strip()
    if not title:
        return None
    words = [w for w in title.lower().split() if w.strip("-–—") not in STOPWORDS]
    key = "title:" + "_".join(w.strip(".,!?:;\"'") for w in words[:6])
    return key, title


@dataclass
class AngleStat:
    key: str
    label: str
    median_run_days: float
    longest_run_days: int
    store_count: int
    metro_count: int
    stores: list[str] = field(default_factory=list)
    metros: list[str] = field(default_factory=list)
    stores_missing_metro: int = 0
    snapshot_urls: list[str] = field(default_factory=list)
    ad_count: int = 0

    @property
    def cross_confirmed(self) -> bool:
        return (
            self.median_run_days >= config.WINNER_MIN_DAYS
            and self.store_count >= config.CROSS_MARKET_MIN_STORES
            and self.metro_count >= config.CROSS_MARKET_MIN_STORES
        )

    @property
    def provisional(self) -> bool:
        """Long-running at enough stores, but the metros are not all known.

        Reported separately rather than promoted: four stores in one metro is
        one market's situation, which is exactly what the rule exists to
        exclude.
        """
        return (
            not self.cross_confirmed
            and self.median_run_days >= config.WINNER_MIN_DAYS
            and self.store_count >= config.CROSS_MARKET_MIN_STORES
            and self.stores_missing_metro > 0
        )


@dataclass
class ScalingAlert:
    page_id: str
    page_name: str
    metro: str | None
    prior_count: int
    prior_on: dt.date
    current_count: int
    current_on: dt.date
    new_ads: list[dict[str, Any]] = field(default_factory=list)

    @property
    def delta(self) -> int:
        return self.current_count - self.prior_count

    @property
    def ratio(self) -> float:
        return (self.current_count / self.prior_count) if self.prior_count else float("inf")


@dataclass
class LocalWatch:
    page_id: str
    page_name: str
    active_count: int
    observed_on: dt.date | None
    newest_ads: list[dict[str, Any]] = field(default_factory=list)
    longest_run_days: int = 0
    active_angle_keys: list[str] = field(default_factory=list)


def _scoring_pages(store: Store) -> dict[str, Any]:
    """Pages that count toward trends: out-of-market only.

    Local pages are the thing being compared against, and corporate Ashley is
    tagged reference precisely so its national volume cannot drown the signal.
    """
    return {page.page_id: page for page in store.pages(list(config.SCORING_ROLES))}


def _angle_rows(store: Store, page_ids: Iterable[str] | None = None,
                ads: Sequence[dict] | None = None) -> list[tuple[str, str, dict]]:
    allowed = set(page_ids) if page_ids is not None else None
    rows = ads if ads is not None else store.ads()
    resolved: list[tuple[str, str, dict]] = []
    for row in rows:
        if allowed is not None and row["page_id"] not in allowed:
            continue
        angle = angle_of(row, store.vision(row["ad_id"]))
        if angle is None:
            continue
        resolved.append((angle[0], angle[1], row))
    return resolved


def _aggregate(store: Store, entries: list[tuple[str, str, dict]],
               pages: dict[str, Any], asof: dt.date) -> dict[str, AngleStat]:
    """Collapse ads to angles, counting each store once.

    Per-store longest run, then median across stores: a single page running
    twenty variants of one angle should not outvote four independent stores.
    """
    grouped: dict[str, dict[str, Any]] = {}
    for key, label, row in entries:
        bucket = grouped.setdefault(
            key,
            {"label": label, "per_page": {}, "snapshots": [], "ads": 0},
        )
        days = run_days(row, asof)
        page_id = row["page_id"]
        bucket["per_page"][page_id] = max(bucket["per_page"].get(page_id, 0), days)
        bucket["ads"] += 1
        if row.get("snapshot_url") and len(bucket["snapshots"]) < 5:
            bucket["snapshots"].append(row["snapshot_url"])

    stats: dict[str, AngleStat] = {}
    for key, bucket in grouped.items():
        per_page = bucket["per_page"]
        store_names, metros, missing = [], [], 0
        for page_id in per_page:
            page = pages.get(page_id)
            store_names.append(page.page_name if page else page_id)
            if page and page.metro:
                metros.append(page.metro)
            else:
                missing += 1
        stats[key] = AngleStat(
            key=key,
            label=bucket["label"],
            median_run_days=median(list(per_page.values())),
            longest_run_days=max(per_page.values()),
            store_count=len(per_page),
            metro_count=len(set(metros)),
            stores=sorted(store_names, key=str.lower),
            metros=sorted(set(metros)),
            stores_missing_metro=missing,
            snapshot_urls=bucket["snapshots"],
            ad_count=bucket["ads"],
        )
    return stats


def winning_angles(store: Store, asof: dt.date | None = None) -> list[AngleStat]:
    """Proxy 1: run duration. Ranked by median run days, longest first."""
    asof = asof or today()
    pages = _scoring_pages(store)
    entries = _angle_rows(store, pages.keys())
    stats = _aggregate(store, entries, pages, asof)
    return sorted(
        stats.values(),
        key=lambda s: (-s.median_run_days, -s.store_count, s.label.lower()),
    )


def graveyard(store: Store, asof: dt.date | None = None) -> list[AngleStat]:
    """Proxy 3: kill speed. Angles killed fast in more than one market."""
    asof = asof or today()
    pages = _scoring_pages(store)
    dead = [row for row in store.ads() if row.get("ended_on")]
    entries = _angle_rows(store, pages.keys(), ads=dead)
    stats = _aggregate(store, entries, pages, asof)
    # An angle still running somewhere is not dead, whatever died elsewhere.
    live_keys = {
        key for key, _, row in _angle_rows(store, pages.keys())
        if not row.get("ended_on")
    }
    return sorted(
        [
            stat
            for key, stat in stats.items()
            if stat.median_run_days <= config.KILL_MAX_DAYS
            and stat.store_count >= config.GRAVEYARD_MIN_STORES
            and key not in live_keys
        ],
        key=lambda s: (s.median_run_days, -s.store_count),
    )


def scaling_alerts(store: Store, asof: dt.date | None = None,
                   window_days: int = config.VELOCITY_WINDOW_DAYS) -> list[ScalingAlert]:
    """Proxy 2: ad-count velocity — the earliest signal available.

    Fires before the 45-day duration threshold can, which is the point: a page
    going 8 -> 40 active ads in a week has already found something.
    """
    asof = asof or today()
    window_start = asof - dt.timedelta(days=window_days)
    pages = _scoring_pages(store)
    alerts: list[ScalingAlert] = []

    for page_id, page in pages.items():
        history = store.counts(page_id=page_id)
        if len(history) < 2:
            continue
        current = history[-1]
        current_on = parse_date(current["observed_on"])
        prior = None
        for row in history[:-1]:
            observed = parse_date(row["observed_on"])
            if observed and observed <= window_start:
                prior = row  # latest reading at or before the window start
            elif prior is None:
                prior = row  # short history: fall back to the oldest reading
        if prior is None:
            continue
        prior_count = int(prior["active_ad_count"])
        current_count = int(current["active_ad_count"])
        delta = current_count - prior_count
        ratio = (current_count / prior_count) if prior_count else float("inf")
        if delta < config.VELOCITY_MIN_DELTA or ratio < config.VELOCITY_MIN_RATIO:
            continue
        # A burst is usually one angle in twenty variants; listing each variant
        # buries the thing worth looking at. Group by angle, keep one example.
        grouped_new: dict[str, dict[str, Any]] = {}
        for row in store.ads(page_id=page_id):
            if (parse_date(row["first_seen"]) or asof) <= window_start:
                continue
            angle = angle_of(row, store.vision(row["ad_id"]))
            key, label = angle if angle else ("__untitled__", None)
            entry = grouped_new.setdefault(
                key,
                {
                    "angle": label,
                    "ad_count": 0,
                    "ad_id": row["ad_id"],
                    "link_title": row["link_title"],
                    "snapshot_url": row["snapshot_url"],
                    "first_seen": row["first_seen"],
                },
            )
            entry["ad_count"] += 1
            entry["first_seen"] = min(entry["first_seen"], row["first_seen"])
        new_ads = sorted(grouped_new.values(), key=lambda e: -e["ad_count"])
        alerts.append(
            ScalingAlert(
                page_id=page_id,
                page_name=page.page_name,
                metro=page.metro,
                prior_count=prior_count,
                prior_on=parse_date(prior["observed_on"]) or window_start,
                current_count=current_count,
                current_on=current_on or asof,
                new_ads=new_ads[:10],
            )
        )
    return sorted(alerts, key=lambda a: -a.delta)


def local_active_angle_keys(store: Store) -> set[str]:
    local_pages = {page.page_id for page in store.pages([config.ROLE_LOCAL])}
    active = [row for row in store.ads(active_only=True) if row["page_id"] in local_pages]
    return {key for key, _, _ in _angle_rows(store, local_pages, ads=active)}


def gap_list(store: Store, asof: dt.date | None = None) -> list[AngleStat]:
    """Winning angles nobody in Louisville is running. The offense list."""
    local_keys = local_active_angle_keys(store)
    return [
        stat
        for stat in winning_angles(store, asof)
        if (stat.cross_confirmed or stat.provisional) and stat.key not in local_keys
    ]


def local_watch(store: Store, asof: dt.date | None = None) -> list[LocalWatch]:
    asof = asof or today()
    watches: list[LocalWatch] = []
    for page in store.pages([config.ROLE_LOCAL]):
        counts = store.counts(page_id=page.page_id)
        active = store.ads(page_id=page.page_id, active_only=True)
        latest = counts[-1] if counts else None
        # "Newest creative" means newest by delivery start, not by the order we
        # happened to ingest it: a whole page arrives on one first_seen date.
        newest = sorted(
            active,
            key=lambda row: (
                row["ad_delivery_start_time"] or row["ad_creation_time"] or row["first_seen"],
                row["first_seen"],
                row["ad_id"],
            ),
            reverse=True,
        )[:3]
        watches.append(
            LocalWatch(
                page_id=page.page_id,
                page_name=page.page_name,
                active_count=int(latest["active_ad_count"]) if latest else len(active),
                observed_on=parse_date(latest["observed_on"]) if latest else None,
                newest_ads=[
                    {
                        "ad_id": row["ad_id"],
                        "link_title": row["link_title"],
                        "snapshot_url": row["snapshot_url"],
                        "first_seen": row["first_seen"],
                        "run_days": run_days(row, asof),
                    }
                    for row in newest
                ],
                longest_run_days=max((run_days(row, asof) for row in active), default=0),
                active_angle_keys=sorted(
                    {key for key, _, _ in _angle_rows(store, [page.page_id], ads=active)}
                ),
            )
        )
    return watches


def readiness(store: Store, asof: dt.date | None = None) -> dict[str, Any]:
    """How much of the report is trustworthy yet.

    Steps 1-2 produce nothing useful on day one; the value is longitudinal.
    """
    asof = asof or today()
    days = store.history_days()
    scoring_pages = _scoring_pages(store)
    total_ads = len(store.ads())
    with_vision = len(store.vision_ad_ids())
    return {
        "history_days": days,
        "duration_signal_ready": days >= 14,
        "seed_pages_scored": len(scoring_pages),
        "seed_gap": max(0, config.SEED_TARGET_MIN - len(scoring_pages)),
        "ads_tracked": total_ads,
        "ads_with_vision": with_vision,
        "pages_missing_metro": sorted(
            page.page_name for page in scoring_pages.values() if not page.metro
        ),
        "last_poll": store.last_poll_date(),
        "asof": asof,
    }
