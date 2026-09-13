"""Two ways to reach the Ad Library, one shared response shape.

`plan_*` emits the exact `ads_library_search` calls to run when a human or an
agent holds the API access (the MCP path). `GraphApiClient` makes the same
calls directly when an access token is available for unattended cron. Both
end at `models.normalize_pull`, so downstream stages never learn which ran.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable, Sequence

from . import config
from .models import Pull, normalize_pull

TOOL_NAME = "ads_library_search"


def plan_poll(page_ids: Iterable[str], limit: int = config.POLL_LIMIT,
              countries: Sequence[str] = config.POLL_COUNTRIES) -> list[dict[str, Any]]:
    """Stage 1 calls: one per seed page. Never batch page_ids together.

    A batched call shares a single `limit` across pages, so a page running 40
    ads can silently crowd out a page running 3 and fake an ending for it.
    """
    return [
        {
            "tool": TOOL_NAME,
            "arguments": {
                "page_ids": [str(page_id)],
                "ad_active_status": "ACTIVE",
                "countries": list(countries),
                "limit": limit,
            },
        }
        for page_id in page_ids
    ]


def plan_harvest(phrases: Iterable[str], limit: int = config.HARVEST_LIMIT,
                 countries: Sequence[str] = config.HARVEST_COUNTRIES) -> list[dict[str, Any]]:
    """Stage 0 calls: phrase search, to be filtered by page_name afterwards."""
    return [
        {
            "tool": TOOL_NAME,
            "arguments": {
                "search_terms": phrase,
                "ad_active_status": "ACTIVE",
                "countries": list(countries),
                "limit": limit,
            },
        }
        for phrase in phrases
    ]


class GraphApiClient:
    """Direct Ad Library access. Optional: only needed for unattended runs."""

    def __init__(self, token: str | None = None, version: str = config.GRAPH_API_VERSION,
                 base: str = config.GRAPH_API_BASE, timeout: int = 30):
        self.token = token or os.environ.get(config.TOKEN_ENV, "")
        self.version = version
        self.base = base.rstrip("/")
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.token)

    def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self.available:
            raise RuntimeError(
                f"no Ad Library token; set {config.TOKEN_ENV} or use the plan/ingest flow"
            )
        query = dict(params)
        query["access_token"] = self.token
        url = f"{self.base}/{self.version}/ads_archive?" + urllib.parse.urlencode(
            query, doseq=True
        )
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:  # surface Meta's own message
            body = error.read().decode("utf-8", "replace")
            raise RuntimeError(f"Ad Library HTTP {error.code}: {body[:400]}") from error

    def poll_page(self, page_id: str, limit: int = config.POLL_LIMIT,
                  countries: Sequence[str] = config.POLL_COUNTRIES) -> Pull:
        payload = self._get(
            {
                "search_page_ids": json.dumps([str(page_id)]),
                "ad_active_status": "ACTIVE",
                "ad_reached_countries": json.dumps(list(countries)),
                "fields": ",".join(config.AD_FIELDS),
                "limit": limit,
            }
        )
        return normalize_pull(payload, page_id=str(page_id))

    def search_phrase(self, phrase: str, limit: int = config.HARVEST_LIMIT,
                      countries: Sequence[str] = config.HARVEST_COUNTRIES) -> Pull:
        payload = self._get(
            {
                "search_terms": phrase,
                "ad_active_status": "ACTIVE",
                "ad_reached_countries": json.dumps(list(countries)),
                "fields": ",".join(config.AD_FIELDS),
                "limit": limit,
            }
        )
        pull = normalize_pull(payload)
        pull.search_terms = phrase
        return pull
