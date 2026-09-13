"""Stage 0 seed registry: the only place geography enters the system.

The API has no city or region filter, so the metro of an ad is the metro of
the page that ran it. That makes `seeds.json` the geographic index, and an
unset `metro` a real gap rather than a cosmetic one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import config
from .models import PageSeed


@dataclass
class SeedFile:
    path: Path
    pages: list[PageSeed]
    pending: list[dict[str, Any]]
    target_metros: list[str]
    raw: dict[str, Any]

    def by_role(self, role: str) -> list[PageSeed]:
        return [page for page in self.pages if page.role == role]

    def coverage(self) -> dict[str, Any]:
        metros = sorted({p.metro for p in self.pages if p.metro})
        missing_metro = [p.page_name for p in self.pages if not p.metro]
        out_of_market = self.by_role(config.ROLE_OUT_OF_MARKET)
        return {
            "total": len(self.pages),
            "local": len(self.by_role(config.ROLE_LOCAL)),
            "out_of_market": len(out_of_market),
            "reference": len(self.by_role(config.ROLE_REFERENCE)),
            "pending": len(self.pending),
            "metros_covered": metros,
            "pages_missing_metro": missing_metro,
            "target_metros_uncovered": [
                metro for metro in self.target_metros if metro not in metros
            ],
            "seed_gap": max(0, config.SEED_TARGET_MIN - len(out_of_market)),
        }


def load(path: Path | str = config.SEEDS_PATH) -> SeedFile:
    path = Path(path)
    if not path.exists():
        return SeedFile(path=path, pages=[], pending=[], target_metros=[], raw={})
    raw = json.loads(path.read_text())
    pages = [PageSeed.from_json(row) for row in raw.get("pages", [])]
    _reject_duplicates(pages)
    for page in pages:
        if page.role not in config.ROLES:
            raise ValueError(f"{page.page_name}: unknown role {page.role!r}")
    return SeedFile(
        path=path,
        pages=pages,
        pending=list(raw.get("pending", [])),
        target_metros=list(raw.get("target_metros", [])),
        raw=raw,
    )


def _reject_duplicates(pages: list[PageSeed]) -> None:
    seen: set[str] = set()
    for page in pages:
        if page.page_id in seen:
            raise ValueError(f"duplicate page_id in seed file: {page.page_id}")
        seen.add(page.page_id)


def save(seed_file: SeedFile, updated_on: str | None = None) -> None:
    raw = dict(seed_file.raw)
    raw["pages"] = [page.as_json() for page in seed_file.pages]
    raw["pending"] = seed_file.pending
    if seed_file.target_metros:
        raw["target_metros"] = seed_file.target_metros
    if updated_on:
        raw["updated_on"] = updated_on
    seed_file.path.write_text(json.dumps(raw, indent=2) + "\n")


def add(seed_file: SeedFile, seed: PageSeed) -> bool:
    """Add a page, or update the existing entry with the same id."""
    if seed.role not in config.ROLES:
        raise ValueError(f"unknown role {seed.role!r}; expected one of {config.ROLES}")
    for index, existing in enumerate(seed_file.pages):
        if existing.page_id == seed.page_id:
            seed_file.pages[index] = seed
            return False
    seed_file.pages.append(seed)
    # A newly verified page clears its pending placeholder.
    seed_file.pending = [
        entry
        for entry in seed_file.pending
        if str(entry.get("page_name", "")).strip().lower() != seed.page_name.strip().lower()
    ]
    return True
