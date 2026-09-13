"""Command line entry point: `python3 -m adbot <command>`.

Two operating modes share every command:
  plan   -> print the exact ads_library_search calls to run
  ingest -> feed the responses back in
Or, with META_ADS_LIBRARY_TOKEN set, `poll run` does both unattended.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from . import config, harvester, poll, report, scoring, seeds as seeds_module, vision
from .models import PageSeed, normalize_file, parse_date, today
from .store import Store


def _date(value: str | None) -> dt.date | None:
    if not value:
        return None
    parsed = parse_date(value)
    if parsed is None:
        raise argparse.ArgumentTypeError(f"not a date: {value!r}")
    return parsed


def _dump(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def _open(args) -> Store:
    return Store(args.db)


def _load_json(path: str):
    return json.loads(Path(path).read_text())


# -- seeds -------------------------------------------------------------------

def cmd_seeds_list(args) -> int:
    seed_file = seeds_module.load(args.seeds)
    _dump(
        {
            "coverage": seed_file.coverage(),
            "pages": [page.as_json() for page in seed_file.pages],
            "pending": seed_file.pending,
        }
    )
    return 0


def cmd_seeds_add(args) -> int:
    seed_file = seeds_module.load(args.seeds)
    seed = PageSeed(
        page_id=args.page_id,
        page_name=args.page_name,
        role=args.role,
        metro=args.metro,
        note=args.note,
    )
    added = seeds_module.add(seed_file, seed)
    seeds_module.save(seed_file, updated_on=today().isoformat())
    with _open(args) as store:
        store.upsert_page(seed)
    print(f"{'added' if added else 'updated'} {seed.page_name} ({seed.page_id})")
    return 0


def cmd_seeds_sync(args) -> int:
    with _open(args) as store:
        count = poll.sync_seeds(store, args.seeds)
    print(f"synced {count} page(s) into {args.db}")
    return 0


# -- stage 0: harvest --------------------------------------------------------

def cmd_harvest_plan(args) -> int:
    from . import client

    phrases = []
    for phrase in args.phrase:
        harvester.check_phrase(phrase)  # fail loudly before burning a call
        phrases.append(phrase)
    _dump(
        {
            "calls": client.plan_harvest(phrases),
            "then": "adbot harvest ingest <file.json>",
            "reminder": (
                "Roughly 80% of raw results are affiliate spam; the page_name "
                "filter is applied on ingest."
            ),
        }
    )
    return 0


def cmd_harvest_ingest(args) -> int:
    payload = _load_json(args.file)
    pulls = normalize_file(payload)
    seed_file = seeds_module.load(args.seeds)
    known = {page.page_id for page in seed_file.pages}
    result = harvester.harvest(pulls, known_page_ids=known)
    _dump(
        {
            "raw_ads": result.raw_ads,
            "kept_ads": result.kept_ads,
            "usable_rate": round(result.usable_rate, 3),
            "new_candidates": [c.as_json() for c in result.candidates],
            "dropped_page_names_sample": result.dropped_pages[:15],
            "next": "adbot seeds add --page-id ... --page-name ... --metro ...",
        }
    )
    return 0


# -- stage 1: poll -----------------------------------------------------------

def cmd_poll_plan(args) -> int:
    with _open(args) as store:
        if not store.pages():
            poll.sync_seeds(store, args.seeds)
        _dump(poll.plan(store))
    return 0


def cmd_poll_ingest(args) -> int:
    with _open(args) as store:
        if not store.pages():
            poll.sync_seeds(store, args.seeds)
        summary = poll.ingest_path(store, args.file, observed_on=args.observed_on)
    _dump(summary)
    return 0


def cmd_poll_run(args) -> int:
    with _open(args) as store:
        if not store.pages():
            poll.sync_seeds(store, args.seeds)
        summary = poll.run_live(store, observed_on=args.observed_on)
    _dump(summary)
    return 0


# -- stage 2: vision ---------------------------------------------------------

def cmd_vision_queue(args) -> int:
    with _open(args) as store:
        tasks = vision.queue(store, asof=args.asof)[: args.limit]
        _dump(
            {
                "count": len(tasks),
                "tasks": [task.as_json() for task in tasks],
                "prompt_template": vision.EXTRACTION_PROMPT,
                "then": "adbot vision ingest <file.json>",
            }
        )
    return 0


def cmd_vision_prompts(args) -> int:
    with _open(args) as store:
        for task in vision.queue(store, asof=args.asof)[: args.limit]:
            print(vision.prompt_for(task))
            print("-" * 72)
    return 0


def cmd_vision_ingest(args) -> int:
    payload = _load_json(args.file)
    with _open(args) as store:
        _dump(vision.ingest_vision(store, payload, asof=args.asof))
    return 0


# -- scoring / report --------------------------------------------------------

def cmd_score(args) -> int:
    with _open(args) as store:
        asof = args.asof or today()
        _dump(
            {
                "readiness": scoring.readiness(store, asof),
                "winning_angles": [
                    {
                        **vars(stat),
                        "cross_confirmed": stat.cross_confirmed,
                        "provisional": stat.provisional,
                    }
                    for stat in scoring.winning_angles(store, asof)[:20]
                ],
                "scaling_alerts": [
                    {**vars(alert), "delta": alert.delta, "ratio": round(alert.ratio, 2)}
                    for alert in scoring.scaling_alerts(store, asof)
                ],
                "graveyard": [vars(stat) for stat in scoring.graveyard(store, asof)],
                "gap_list": [vars(stat) for stat in scoring.gap_list(store, asof)],
                "local_watch": [vars(watch) for watch in scoring.local_watch(store, asof)],
            }
        )
    return 0


def cmd_report(args) -> int:
    with _open(args) as store:
        if args.stdout:
            print(report.build(store, asof=args.asof))
        else:
            path = report.write(store, asof=args.asof, path=args.out)
            print(f"wrote {path}")
    return 0


def cmd_status(args) -> int:
    with _open(args) as store:
        seed_file = seeds_module.load(args.seeds)
        _dump(
            {
                "db": str(args.db),
                "seeds": seed_file.coverage(),
                "readiness": scoring.readiness(store, args.asof or today()),
                "vision_queue": len(vision.queue(store, asof=args.asof)),
            }
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="adbot",
        description="Furniture Meta Ads research bot (Louisville).",
    )
    parser.add_argument("--db", default=str(config.DB_PATH), help="sqlite path")
    parser.add_argument("--seeds", default=str(config.SEEDS_PATH), help="seed list path")
    parser.add_argument("--asof", type=_date, default=None, help="override today's date")
    sub = parser.add_subparsers(dest="command", required=True)

    seeds_p = sub.add_parser("seeds", help="Stage 0 seed registry").add_subparsers(
        dest="sub", required=True
    )
    seeds_p.add_parser("list", help="show seeds and coverage").set_defaults(func=cmd_seeds_list)
    add_p = seeds_p.add_parser("add", help="add or update a verified page")
    add_p.add_argument("--page-id", required=True)
    add_p.add_argument("--page-name", required=True)
    add_p.add_argument("--role", default=config.ROLE_OUT_OF_MARKET, choices=config.ROLES)
    add_p.add_argument("--metro", default=None)
    add_p.add_argument("--note", default=None)
    add_p.set_defaults(func=cmd_seeds_add)
    seeds_p.add_parser("sync", help="load seeds.json into the database").set_defaults(
        func=cmd_seeds_sync
    )

    harvest_p = sub.add_parser("harvest", help="Stage 0 harvester").add_subparsers(
        dest="sub", required=True
    )
    hplan = harvest_p.add_parser("plan", help="build phrase-search calls")
    hplan.add_argument("phrase", nargs="+", help=f"{config.PHRASE_MIN_WORDS}-{config.PHRASE_MAX_WORDS} word phrases")
    hplan.set_defaults(func=cmd_harvest_plan)
    hing = harvest_p.add_parser("ingest", help="filter results into page candidates")
    hing.add_argument("file")
    hing.set_defaults(func=cmd_harvest_ingest)

    poll_p = sub.add_parser("poll", help="Stage 1 daily poll").add_subparsers(
        dest="sub", required=True
    )
    poll_p.add_parser("plan", help="print today's calls").set_defaults(func=cmd_poll_plan)
    ping = poll_p.add_parser("ingest", help="apply today's responses")
    ping.add_argument("file")
    ping.add_argument("--observed-on", dest="observed_on", type=_date, default=None)
    ping.set_defaults(func=cmd_poll_ingest)
    prun = poll_p.add_parser("run", help=f"poll directly (needs ${config.TOKEN_ENV})")
    prun.add_argument("--observed-on", dest="observed_on", type=_date, default=None)
    prun.set_defaults(func=cmd_poll_run)

    vision_p = sub.add_parser("vision", help="Stage 2 vision pass").add_subparsers(
        dest="sub", required=True
    )
    vq = vision_p.add_parser("queue", help="ads awaiting extraction")
    vq.add_argument("--limit", type=int, default=50)
    vq.set_defaults(func=cmd_vision_queue)
    vp = vision_p.add_parser("prompts", help="print ready-to-run extraction prompts")
    vp.add_argument("--limit", type=int, default=10)
    vp.set_defaults(func=cmd_vision_prompts)
    vi = vision_p.add_parser("ingest", help="apply extraction results")
    vi.add_argument("file")
    vi.set_defaults(func=cmd_vision_ingest)

    sub.add_parser("score", help="dump every signal as JSON").set_defaults(func=cmd_score)

    rep = sub.add_parser("report", help="weekly markdown report")
    rep.add_argument("--out", default=None)
    rep.add_argument("--stdout", action="store_true")
    rep.set_defaults(func=cmd_report)

    sub.add_parser("status", help="seed coverage and data readiness").set_defaults(
        func=cmd_status
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (harvester.PhraseLengthError, ValueError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
