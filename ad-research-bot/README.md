# Furniture Meta Ads Research Bot

Find proven-winning furniture ad angles in other metros **before** competitors in
Louisville run them.

Pure standard-library Python 3.11. No install step, no dependencies.

```bash
cd ad-research-bot
python3 -m adbot status
python3 -m unittest discover -s tests
```

---

## The four constraints that shape everything

These are tested and confirmed against the Ad Library API. Nothing here is
designed around an assumption.

1. **No advertiser-name search.** `search_terms` matches ad creative text only,
   never page names. Searching `"BoxDrop Mattress and Furniture"` returns 224,000
   romance-novel ads. Page IDs have to be acquired another way.
2. **No city or region filter.** Countries only (ISO-2). You cannot query
   "furniture ads in Nashville." Geography comes from *which pages are in the seed
   list*, which is why `seeds.json` is the geographic index and a missing `metro`
   is a real gap.
3. **No ad body copy returned.** You get ad ID, page ID, page name, an often-blank
   `ad_creative_link_title`, timestamps, and a snapshot URL. Copy and creative
   require a vision pass on the snapshot.
4. **No performance data, ever.** No spend, impressions, CTR, ROAS. Every
   "what's winning" judgement here is inferred from run duration and ad-count
   behaviour.

## Two ways to run it

The pipeline never learns which one you used.

| Mode | When | How |
| --- | --- | --- |
| **plan / ingest** | You or an agent holds the API access (e.g. an `ads_library_search` MCP tool) | `adbot <stage> plan` prints the exact calls; feed the responses back with `adbot <stage> ingest file.json` |
| **direct** | Unattended cron with an Ad Library token | `export META_ADS_LIBRARY_TOKEN=...` then `adbot poll run` |

Ingest accepts whatever envelope the responses arrive in — a bare list,
`{"data": [...]}`, `{"ads": [...]}` — and a batch of pages in one file:

```json
{"observed_on": "2026-09-14",
 "pulls": [{"page_id": "503984643076551", "response": { ...raw result... }}]}
```

---

## Stage 0 — Seed list (run once, refresh quarterly)

`seeds.json` holds the verified pages. Seven are already in it; three still need a
manual lookup (Facebook page → About → Page Transparency → Page ID):
**BoxDrop Louisville**, **Sims Furniture**, **Ashley**.

```bash
python3 -m adbot seeds list      # pages, pending lookups, metro coverage, seed gap
python3 -m adbot seeds add --page-id 123 --page-name "NashCo Furniture" --metro Nashville
```

**Roles.** `local` = the Louisville competitors you are trying to beat.
`out_of_market` = the only pages that feed trend scoring. `reference` = pages you
want to see but not score — tag corporate **Ashley** here, since its hundreds of
national ads would drown the local signal.

**Harvester.** Out-of-market IDs are found by searching phrases that plausibly
appear in a furniture retailer's ad title, then filtering results by page name:

```bash
python3 -m adbot harvest plan "Furniture and Mattress Store"
python3 -m adbot harvest ingest results.json
```

Phrase length is the whole game, and the CLI enforces it (3–5 words):

| Query | Result |
| --- | --- |
| `Louisville Overstock Furniture` (3 words) | 2 ads — clean |
| `Furniture and Mattress Store` (4 words) | 5,949 ads — ~20% usable |
| `BoxDrop` (1 word) | 8.1M ads — pure spam |
| `Sectional Sofa Queen Bedroom Set Clearance Warehouse` (7 words) | 0 ads |

Ingest applies the mandatory page-name filter: keep
`furniture|mattress|home|sofa|sleep|interiors|décor|warehouse`, drop
`novel|drama|read|chapter|story|chatme|romance`. Roughly 80% of raw results are
affiliate spam. The drop list wins ties, and a legitimate store whose name matches
no keep-word (e.g. "Louisville Overstock") won't survive discovery — add those by
hand.

**Target:** 25–30 out-of-market stores across comparable metros — Memphis,
Birmingham, Indianapolis, Nashville, Columbus, OKC, Knoxville, Dayton, Greensboro.

## Stage 1 — Daily poll

```bash
python3 -m adbot poll plan > calls.json     # one call per seed page
python3 -m adbot poll ingest responses.json
```

One call per page, never batched: a shared `limit` lets a page running 40 ads
crowd out a page running 3 and fake an ending for it.

Each ad is stored with `first_seen` / `last_seen`. Ads absent from today's pull for
a **polled** page are marked ended as of today; a page you skipped is left alone,
so a missed day never mass-kills history. An ad that reappears has its end date
cleared. `estimated_total_count` is logged per page per day — the trend line
matters more than the number.

## Stage 2 — Vision pass

The API returns no copy, so the creative has to be read off the snapshot.

```bash
python3 -m adbot vision queue      # ads awaiting extraction, with the JSON schema
python3 -m adbot vision prompts    # ready-to-run extraction prompts
python3 -m adbot vision ingest extracted.json
```

Triggers on newly appeared ads and ads crossing the 30-day mark. Each ad is
processed exactly once. "Newly appeared" means first seen *after* the first poll —
ads already live when tracking began are backfill and enter at day 30 — so an ad
that launches between two weekly vision runs is not skipped.

Extracted per ad: offer type (price anchor / financing / % off / BOGO / free
add-on / event), price points, hook, urgency mechanic (deadline / stock scarcity /
event / none), format, creative style, CTA and destination. Free-text answers are
normalised onto that vocabulary on the way in — grouping is worthless if "0% APR"
and "financing" land in different buckets.

## Scoring — three proxies, one confirmation rule

1. **Run duration = the winner signal.** An ad live 45+ days on a small-business
   page is almost certainly profitable; nobody funds a loser for six weeks. Angles
   are ranked by median run duration, counting each store once (per-store longest
   run, then median across stores) so one page running twenty variants cannot
   outvote four independent stores.
2. **Ad-count velocity = the scaling signal.** A page going 8 → 40 active ads
   inside a week found something. Fires before the 45-day threshold can, which is
   the point. Reported with the creative that launched alongside it, grouped by
   angle.
3. **Kill speed = free negative testing.** Ads dead inside 7 days failed. An angle
   with a short median lifespan across several independent stores is one not to
   test.

**Cross-market confirmation.** An angle running long at one store is one store's
situation. Only angles running 45+ days at **four unrelated stores in four
metros** are reported as confirmed. Angles that clear the store count but whose
metros aren't all filled in are reported separately as *provisional*, never
promoted — four stores in one metro is exactly what the rule exists to exclude.

## Weekly output

```bash
python3 -m adbot report              # writes reports/weekly-YYYY-MM-DD.md
python3 -m adbot report --stdout
python3 -m adbot score               # every signal as JSON
```

1. Cross-confirmed winning angles — angle, median run duration, store count,
   example snapshot URLs
2. Scaling alerts — pages whose active ad count jumped, with the new creative
3. Graveyard — angles that died fast in multiple markets; do not test these
4. Gap list — winning angles nobody in Louisville is currently running (the
   offense list)
5. Local watch — active ad count and newest creative per Louisville competitor

Every report opens with a data-readiness block: history length, seed gap, missing
metros, and a warning while the duration signal is not live yet. An empty report
and a broken report otherwise look identical.

## Build order

1. Seed list to 25–30 pages (harvester + the three manual lookups)
2. Daily poll, storage, diffing
3. **Two weeks of passive collection** — the duration signal does not exist until
   there is history
4. Vision pass
5. Weekly report

Steps 1–2 produce nothing useful on day one. That is expected. The bot's entire
value is longitudinal.

### Daily cron

```cron
0 7 * * *  cd /path/to/ad-research-bot && python3 -m adbot poll run >> data/poll.log 2>&1
0 8 * * 1  cd /path/to/ad-research-bot && python3 -m adbot report
```

## Baseline readings (Sept 12, 2026)

- **Louisville Overstock** — 2 active ads, started Sept 3 and Sept 10. No
  long-runners at all, meaning no proven evergreen creative is being defended.
  Live angle is hard price anchoring on entry-level tickets: $498 Cayboni bedroom
  set, $288 Loreo sofa, $248 8" queen mattress.
- **Kassa Mall** — running "Walk-In Exclusive — Extra Savings This Week Only"
  since ~Sept 5. An offer structured to be redeemable only in person. Worth
  watching whether it crosses 45 days.

## Layout

```
adbot/config.py      thresholds, each traceable to a spec line
adbot/models.py      record shapes + response normalisation
adbot/store.py       SQLite schema, upserts, the daily diff
adbot/client.py      call planner + optional Graph API client
adbot/seeds.py       Stage 0 seed registry and coverage
adbot/harvester.py   Stage 0 phrase search filtering
adbot/poll.py        Stage 1 orchestration
adbot/vision.py      Stage 2 queue, prompt, normalisation
adbot/scoring.py     duration / velocity / kill speed / cross-market
adbot/report.py      weekly markdown
adbot/cli.py         python3 -m adbot
```
