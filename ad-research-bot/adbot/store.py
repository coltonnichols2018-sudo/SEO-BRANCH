"""SQLite storage and the day-over-day diff that Stage 1 depends on.

History is the whole product: run duration and ad-count velocity only exist
because yesterday's pull was kept. Nothing in here deletes an ad row.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import config
from .models import Ad, PageSeed, Pull, iso, parse_date, today

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    page_id     TEXT PRIMARY KEY,
    page_name   TEXT NOT NULL DEFAULT '',
    role        TEXT NOT NULL DEFAULT 'out_of_market',
    metro       TEXT,
    note        TEXT,
    verified    INTEGER NOT NULL DEFAULT 1,
    added_on    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ads (
    ad_id                   TEXT PRIMARY KEY,
    page_id                 TEXT NOT NULL,
    page_name               TEXT NOT NULL DEFAULT '',
    link_title              TEXT,
    ad_creation_time        TEXT,
    ad_delivery_start_time  TEXT,
    snapshot_url            TEXT,
    first_seen              TEXT NOT NULL,
    last_seen               TEXT NOT NULL,
    ended_on                TEXT
);
CREATE INDEX IF NOT EXISTS ads_page_idx ON ads(page_id);
CREATE INDEX IF NOT EXISTS ads_last_seen_idx ON ads(last_seen);

CREATE TABLE IF NOT EXISTS page_counts (
    page_id             TEXT NOT NULL,
    observed_on         TEXT NOT NULL,
    active_ad_count     INTEGER NOT NULL,
    PRIMARY KEY (page_id, observed_on)
);

CREATE TABLE IF NOT EXISTS vision (
    ad_id           TEXT PRIMARY KEY,
    processed_on    TEXT NOT NULL,
    trigger         TEXT NOT NULL,
    offer_type      TEXT,
    price_points    TEXT,
    hook            TEXT,
    urgency         TEXT,
    ad_format       TEXT,
    creative_style  TEXT,
    cta             TEXT,
    destination     TEXT,
    raw             TEXT
);

CREATE TABLE IF NOT EXISTS polls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    observed_on TEXT NOT NULL,
    pages       INTEGER NOT NULL DEFAULT 0,
    ads_seen    INTEGER NOT NULL DEFAULT 0,
    new_ads     INTEGER NOT NULL DEFAULT 0,
    ended_ads   INTEGER NOT NULL DEFAULT 0,
    source      TEXT NOT NULL DEFAULT 'ingest'
);
"""

VISION_FIELDS = (
    "offer_type",
    "price_points",
    "hook",
    "urgency",
    "ad_format",
    "creative_style",
    "cta",
    "destination",
)


class Store:
    def __init__(self, path: Path | str = config.DB_PATH):
        self.path = Path(path)
        if self.path.parent and str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- pages ---------------------------------------------------------------

    def upsert_page(self, seed: PageSeed, added_on: dt.date | None = None) -> None:
        self.conn.execute(
            """
            INSERT INTO pages (page_id, page_name, role, metro, note, verified, added_on)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(page_id) DO UPDATE SET
                page_name = excluded.page_name,
                role      = excluded.role,
                metro     = excluded.metro,
                note      = excluded.note,
                verified  = excluded.verified
            """,
            (
                seed.page_id,
                seed.page_name,
                seed.role,
                seed.metro,
                seed.note,
                int(seed.verified),
                iso(added_on or today()),
            ),
        )
        self.conn.commit()

    def sync_seeds(self, seeds: Iterable[PageSeed]) -> int:
        count = 0
        for seed in seeds:
            self.upsert_page(seed)
            count += 1
        return count

    def pages(self, roles: Sequence[str] | None = None) -> list[PageSeed]:
        sql = "SELECT * FROM pages"
        args: list[Any] = []
        if roles:
            sql += f" WHERE role IN ({','.join('?' * len(roles))})"
            args = list(roles)
        sql += " ORDER BY page_name COLLATE NOCASE"
        rows = self.conn.execute(sql, args).fetchall()
        return [
            PageSeed(
                page_id=row["page_id"],
                page_name=row["page_name"],
                role=row["role"],
                metro=row["metro"],
                note=row["note"],
                verified=bool(row["verified"]),
            )
            for row in rows
        ]

    def page(self, page_id: str) -> PageSeed | None:
        row = self.conn.execute(
            "SELECT * FROM pages WHERE page_id = ?", (str(page_id),)
        ).fetchone()
        if row is None:
            return None
        return PageSeed(
            page_id=row["page_id"],
            page_name=row["page_name"],
            role=row["role"],
            metro=row["metro"],
            note=row["note"],
            verified=bool(row["verified"]),
        )

    # -- ads -----------------------------------------------------------------

    def record_ad(self, ad: Ad, observed_on: dt.date) -> bool:
        """Insert or refresh one ad. Returns True if it is newly seen."""
        stamp = iso(observed_on)
        existing = self.conn.execute(
            "SELECT ad_id, first_seen FROM ads WHERE ad_id = ?", (ad.ad_id,)
        ).fetchone()
        if existing is None:
            self.conn.execute(
                """
                INSERT INTO ads (ad_id, page_id, page_name, link_title,
                                 ad_creation_time, ad_delivery_start_time,
                                 snapshot_url, first_seen, last_seen, ended_on)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    ad.ad_id,
                    ad.page_id,
                    ad.page_name,
                    ad.link_title,
                    iso(ad.ad_creation_time),
                    iso(ad.ad_delivery_start_time),
                    ad.snapshot_url,
                    stamp,
                    stamp,
                ),
            )
            return True
        # An ad that reappears was never really dead: clear the end date.
        self.conn.execute(
            """
            UPDATE ads SET
                page_name              = COALESCE(NULLIF(?, ''), page_name),
                link_title             = COALESCE(?, link_title),
                ad_creation_time       = COALESCE(?, ad_creation_time),
                ad_delivery_start_time = COALESCE(?, ad_delivery_start_time),
                snapshot_url           = COALESCE(?, snapshot_url),
                last_seen              = MAX(last_seen, ?),
                ended_on               = NULL
            WHERE ad_id = ?
            """,
            (
                ad.page_name,
                ad.link_title,
                iso(ad.ad_creation_time),
                iso(ad.ad_delivery_start_time),
                ad.snapshot_url,
                stamp,
                ad.ad_id,
            ),
        )
        return False

    def mark_ended(self, page_id: str, observed_on: dt.date,
                   seen_ad_ids: Iterable[str]) -> list[str]:
        """Ads absent from today's pull for a page are ended as of today.

        The spec's diff step. Only pages actually polled today are touched, so
        a skipped page never mass-kills its own history.
        """
        seen = set(seen_ad_ids)
        rows = self.conn.execute(
            "SELECT ad_id FROM ads WHERE page_id = ? AND ended_on IS NULL",
            (str(page_id),),
        ).fetchall()
        ended = [row["ad_id"] for row in rows if row["ad_id"] not in seen]
        for ad_id in ended:
            self.conn.execute(
                "UPDATE ads SET ended_on = ? WHERE ad_id = ?", (iso(observed_on), ad_id)
            )
        return ended

    def ads(self, page_id: str | None = None, active_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM ads"
        clauses: list[str] = []
        args: list[Any] = []
        if page_id:
            clauses.append("page_id = ?")
            args.append(str(page_id))
        if active_only:
            clauses.append("ended_on IS NULL")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY first_seen DESC, ad_id"
        return [dict(row) for row in self.conn.execute(sql, args).fetchall()]

    def ad(self, ad_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM ads WHERE ad_id = ?", (str(ad_id),)).fetchone()
        return dict(row) if row else None

    # -- counts --------------------------------------------------------------

    def record_count(self, page_id: str, observed_on: dt.date, count: int) -> None:
        self.conn.execute(
            """
            INSERT INTO page_counts (page_id, observed_on, active_ad_count)
            VALUES (?, ?, ?)
            ON CONFLICT(page_id, observed_on) DO UPDATE SET
                active_ad_count = excluded.active_ad_count
            """,
            (str(page_id), iso(observed_on), int(count)),
        )

    def counts(self, page_id: str | None = None, since: dt.date | None = None) -> list[dict]:
        sql = "SELECT * FROM page_counts"
        clauses: list[str] = []
        args: list[Any] = []
        if page_id:
            clauses.append("page_id = ?")
            args.append(str(page_id))
        if since:
            clauses.append("observed_on >= ?")
            args.append(iso(since))
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY page_id, observed_on"
        return [dict(row) for row in self.conn.execute(sql, args).fetchall()]

    # -- vision --------------------------------------------------------------

    def record_vision(self, ad_id: str, trigger: str, fields: dict[str, Any],
                      processed_on: dt.date | None = None) -> None:
        price_points = fields.get("price_points")
        if isinstance(price_points, (list, tuple)):
            price_points = json.dumps(list(price_points))
        self.conn.execute(
            """
            INSERT INTO vision (ad_id, processed_on, trigger, offer_type, price_points,
                                hook, urgency, ad_format, creative_style, cta,
                                destination, raw)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ad_id) DO NOTHING
            """,
            (
                str(ad_id),
                iso(processed_on or today()),
                trigger,
                fields.get("offer_type"),
                price_points,
                fields.get("hook"),
                fields.get("urgency"),
                fields.get("ad_format") or fields.get("format"),
                fields.get("creative_style"),
                fields.get("cta"),
                fields.get("destination"),
                json.dumps(fields, default=str),
            ),
        )
        self.conn.commit()

    def vision(self, ad_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM vision WHERE ad_id = ?", (str(ad_id),)).fetchone()
        return dict(row) if row else None

    def vision_ad_ids(self) -> set[str]:
        return {row["ad_id"] for row in self.conn.execute("SELECT ad_id FROM vision")}

    # -- polls ---------------------------------------------------------------

    def record_poll(self, observed_on: dt.date, pages: int, ads_seen: int,
                    new_ads: int, ended_ads: int, source: str = "ingest") -> None:
        self.conn.execute(
            """
            INSERT INTO polls (observed_on, pages, ads_seen, new_ads, ended_ads, source)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (iso(observed_on), pages, ads_seen, new_ads, ended_ads, source),
        )
        self.conn.commit()

    def last_poll_date(self) -> dt.date | None:
        row = self.conn.execute("SELECT MAX(observed_on) AS d FROM polls").fetchone()
        return parse_date(row["d"]) if row and row["d"] else None

    def first_poll_date(self) -> dt.date | None:
        row = self.conn.execute("SELECT MIN(observed_on) AS d FROM polls").fetchone()
        return parse_date(row["d"]) if row and row["d"] else None

    def history_days(self) -> int:
        row = self.conn.execute(
            "SELECT MIN(observed_on) AS first, MAX(observed_on) AS last FROM polls"
        ).fetchone()
        if not row or not row["first"]:
            return 0
        first, last = parse_date(row["first"]), parse_date(row["last"])
        if not first or not last:
            return 0
        return (last - first).days + 1

    def commit(self) -> None:
        self.conn.commit()


def ingest_pull(store: Store, pull: Pull, observed_on: dt.date) -> dict[str, Any]:
    """Apply one page's response: record ads, diff, log the active count."""
    page_id = pull.page_id
    seen_ids = [ad.ad_id for ad in pull.ads]
    new_ads = 0
    for ad in pull.ads:
        if store.record_ad(ad, observed_on):
            new_ads += 1

    ended: list[str] = []
    if page_id:
        ended = store.mark_ended(page_id, observed_on, seen_ids)
        # estimated_total_count is the page's active ad count; fall back to the
        # rows actually returned when the API omits it.
        count = pull.estimated_total_count
        if count is None:
            count = len([ad for ad in pull.ads if ad.page_id == str(page_id)])
        store.record_count(page_id, observed_on, count)
    store.commit()
    return {
        "page_id": page_id,
        "ads_seen": len(pull.ads),
        "new_ads": new_ads,
        "ended_ads": len(ended),
        "ended_ad_ids": ended,
    }
