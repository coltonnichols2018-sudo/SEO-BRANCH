"""Stage 0 harvester: turn phrase-search noise into candidate page IDs.

There is no advertiser-name search — `search_terms` matches ad creative text
only — so seeds are found by searching phrases that plausibly appear in a
furniture retailer's ad title and then filtering the results by page_name.
About 80% of raw results are affiliate spam.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from . import config
from .models import Ad, Pull

WORD = re.compile(r"[A-Za-z0-9'&$%]+")


class PhraseLengthError(ValueError):
    pass


def check_phrase(phrase: str) -> list[str]:
    """Enforce the 3-5 word rule that the spec calls 'the whole game'.

    Shorter ('BoxDrop') returns 8.1M ebook and short-drama ads; longer
    (7 words) returns nothing at all.
    """
    words = WORD.findall(phrase or "")
    if len(words) < config.PHRASE_MIN_WORDS:
        raise PhraseLengthError(
            f"{phrase!r} is {len(words)} word(s); shorter than "
            f"{config.PHRASE_MIN_WORDS} returns spam, not stores"
        )
    if len(words) > config.PHRASE_MAX_WORDS:
        raise PhraseLengthError(
            f"{phrase!r} is {len(words)} words; longer than "
            f"{config.PHRASE_MAX_WORDS} returns zero results"
        )
    return words


def is_store_name(page_name: str) -> bool:
    """The mandatory page_name filter: drop list wins over the keep list."""
    name = page_name or ""
    if config.PAGE_NAME_DROP.search(name):
        return False
    return bool(config.PAGE_NAME_KEEP.search(name))


@dataclass
class Candidate:
    page_id: str
    page_name: str
    ad_count: int = 0
    phrases: list[str] = field(default_factory=list)
    example_snapshot_url: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "page_id": self.page_id,
            "page_name": self.page_name,
            "ads_in_sample": self.ad_count,
            "matched_phrases": self.phrases,
            "example_snapshot_url": self.example_snapshot_url,
        }


@dataclass
class HarvestResult:
    candidates: list[Candidate]
    raw_ads: int
    kept_ads: int
    dropped_pages: list[str]

    @property
    def usable_rate(self) -> float:
        return (self.kept_ads / self.raw_ads) if self.raw_ads else 0.0


def harvest(pulls: Iterable[Pull], known_page_ids: Iterable[str] = ()) -> HarvestResult:
    """Filter phrase-search results down to plausible furniture retailers."""
    known = {str(page_id) for page_id in known_page_ids}
    candidates: dict[str, Candidate] = {}
    dropped: dict[str, None] = {}
    raw = kept = 0

    for pull in pulls:
        phrase = pull.search_terms
        for ad in pull.ads:
            raw += 1
            if not is_store_name(ad.page_name):
                if ad.page_name:
                    dropped.setdefault(ad.page_name, None)
                continue
            kept += 1
            if ad.page_id in known:
                continue
            candidate = candidates.get(ad.page_id)
            if candidate is None:
                candidate = Candidate(page_id=ad.page_id, page_name=ad.page_name)
                candidates[ad.page_id] = candidate
            candidate.ad_count += 1
            if phrase and phrase not in candidate.phrases:
                candidate.phrases.append(phrase)
            if candidate.example_snapshot_url is None:
                candidate.example_snapshot_url = ad.snapshot_url

    ordered = sorted(
        candidates.values(), key=lambda c: (-c.ad_count, c.page_name.lower())
    )
    return HarvestResult(
        candidates=ordered,
        raw_ads=raw,
        kept_ads=kept,
        dropped_pages=list(dropped),
    )
