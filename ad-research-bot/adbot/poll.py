"""Stage 1 orchestration: plan the day's calls, ingest the day's responses.

One poll per seed page per day. The diff against yesterday is what creates
the end dates that every duration number later depends on, so a day that is
ingested twice must be idempotent and a day that is missed must not look
like a mass ad death.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Iterable

from . import client, config, seeds as seeds_module
from .models import Pull, normalize_file, today
from .store import Store, ingest_pull


def plan(store: Store, roles: Iterable[str] | None = None) -> dict[str, Any]:
    """The exact `ads_library_search` calls to run for today's poll."""
    pages = store.pages(list(roles) if roles else None)
    calls = client.plan_poll(page.page_id for page in pages)
    for call, page in zip(calls, pages):
        call["page_id"] = page.page_id
        call["page_name"] = page.page_name
    return {
        "observed_on": today().isoformat(),
        "pages": len(pages),
        "calls": calls,
        "ingest_with": "adbot poll ingest <file.json>",
        "response_format": {
            "pulls": [
                {"page_id": "<page id>", "response": "<raw ads_library_search result>"}
            ]
        },
    }


def ingest(store: Store, payload: Any, observed_on: dt.date | None = None,
           source: str = "ingest") -> dict[str, Any]:
    """Apply one day's responses: record, diff, log counts."""
    observed_on = observed_on or today()
    pulls = normalize_file(payload, observed_on=observed_on)
    return apply_pulls(store, pulls, observed_on, source=source)


def apply_pulls(store: Store, pulls: Iterable[Pull], observed_on: dt.date | None = None,
                source: str = "ingest") -> dict[str, Any]:
    observed_on = observed_on or today()
    results = []
    skipped_unattributed = 0
    for pull in pulls:
        if pull.page_id is None:
            # Without a page id there is nothing to diff against: recording the
            # ads is safe, ending the page's other ads is not.
            for ad in pull.ads:
                store.record_ad(ad, pull.observed_on or observed_on)
            store.commit()
            skipped_unattributed += 1
            continue
        results.append(ingest_pull(store, pull, pull.observed_on or observed_on))

    summary = {
        "observed_on": observed_on.isoformat(),
        "pages": len(results),
        "ads_seen": sum(r["ads_seen"] for r in results),
        "new_ads": sum(r["new_ads"] for r in results),
        "ended_ads": sum(r["ended_ads"] for r in results),
        "unattributed_pulls": skipped_unattributed,
        "per_page": results,
    }
    if results:
        store.record_poll(
            observed_on,
            pages=summary["pages"],
            ads_seen=summary["ads_seen"],
            new_ads=summary["new_ads"],
            ended_ads=summary["ended_ads"],
            source=source,
        )
    return summary


def ingest_path(store: Store, path: Path | str, observed_on: dt.date | None = None,
                source: str = "ingest") -> dict[str, Any]:
    payload = json.loads(Path(path).read_text())
    return ingest(store, payload, observed_on=observed_on, source=source)


def run_live(store: Store, api: client.GraphApiClient | None = None,
             observed_on: dt.date | None = None,
             roles: Iterable[str] | None = None) -> dict[str, Any]:
    """Unattended poll. Requires an Ad Library token."""
    api = api or client.GraphApiClient()
    pages = store.pages(list(roles) if roles else None)
    pulls = [api.poll_page(page.page_id) for page in pages]
    return apply_pulls(store, pulls, observed_on, source="graph_api")


def sync_seeds(store: Store, path: Path | str = config.SEEDS_PATH) -> int:
    return store.sync_seeds(seeds_module.load(path).pages)
