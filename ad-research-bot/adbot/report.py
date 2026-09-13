"""Weekly report: the five sections the spec asks for, in that order.

Written as markdown so it can be pasted into anything. Every number is
labelled with what it actually is — an inference from run duration and ad
counts, never a performance metric, because none exists.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Sequence

from . import config, scoring
from .models import today
from .store import Store


def _fmt_days(value: float) -> str:
    return f"{value:.0f}" if float(value).is_integer() else f"{value:.1f}"


def _snapshots(urls: Sequence[str], limit: int = 2) -> str:
    if not urls:
        return "_no snapshot URLs recorded_"
    return " ".join(f"[snapshot {i}]({url})" for i, url in enumerate(urls[:limit], 1))


def _angle_line(stat: scoring.AngleStat) -> str:
    metros = ", ".join(stat.metros) if stat.metros else "metros unknown"
    flag = "" if stat.cross_confirmed else " _(provisional — metro data incomplete)_"
    return (
        f"- **{stat.label}**{flag}  \n"
        f"  median run {_fmt_days(stat.median_run_days)} days · longest {stat.longest_run_days} days · "
        f"{stat.store_count} stores ({metros}) · {stat.ad_count} ads  \n"
        f"  stores: {', '.join(stat.stores)}  \n"
        f"  {_snapshots(stat.snapshot_urls)}"
    )


def build(store: Store, asof: dt.date | None = None) -> str:
    asof = asof or today()
    ready = scoring.readiness(store, asof)
    angles = scoring.winning_angles(store, asof)
    confirmed = [s for s in angles if s.cross_confirmed]
    provisional = [s for s in angles if s.provisional]
    alerts = scoring.scaling_alerts(store, asof)
    dead = scoring.graveyard(store, asof)
    gaps = scoring.gap_list(store, asof)
    watches = scoring.local_watch(store, asof)

    out: list[str] = []
    out.append(f"# Furniture ad research — week ending {asof.isoformat()}")
    out.append("")
    out.append(
        "_No spend, impressions, CTR or ROAS exist in the Ad Library. Everything below "
        "is inferred from how long ads stay live and how fast pages add them._"
    )
    out.append("")

    # Data readiness — an empty report and a broken report look identical.
    out.append("## Data readiness")
    out.append("")
    out.append(f"- History: **{ready['history_days']} day(s)** of polls")
    if not ready["duration_signal_ready"]:
        out.append(
            "- ⚠️ **Duration signal is not live yet.** It needs roughly two weeks of "
            "passive collection before run-length means anything. Sections 1, 3 and 4 "
            "will be thin or empty until then — that is expected, not a failure."
        )
    out.append(
        f"- Seed pages scored: **{ready['seed_pages_scored']}** "
        f"(target {config.SEED_TARGET_MIN}–{config.SEED_TARGET_MAX})"
    )
    if ready["seed_gap"]:
        out.append(f"  - {ready['seed_gap']} more out-of-market pages needed")
    out.append(
        f"- Ads tracked: **{ready['ads_tracked']}** · with vision extraction: "
        f"**{ready['ads_with_vision']}**"
    )
    if ready["pages_missing_metro"]:
        out.append(
            "- ⚠️ Missing metro on "
            f"{len(ready['pages_missing_metro'])} scored page(s): "
            f"{', '.join(ready['pages_missing_metro'])}. Cross-market confirmation "
            "counts distinct metros, so these hold angles at provisional."
        )
    out.append("")

    # 1 — cross-confirmed winners
    out.append("## 1. Cross-confirmed winning angles")
    out.append("")
    out.append(
        f"_Median run ≥ {config.WINNER_MIN_DAYS} days across "
        f"≥ {config.CROSS_MARKET_MIN_STORES} unrelated stores in "
        f"{config.CROSS_MARKET_MIN_STORES} metros._"
    )
    out.append("")
    if confirmed:
        out.extend(_angle_line(stat) for stat in confirmed[:5])
    else:
        out.append("_None yet._")
    if provisional:
        out.append("")
        out.append("**Provisional — long-running at enough stores, metros unconfirmed:**")
        out.append("")
        out.extend(_angle_line(stat) for stat in provisional[:5])
    if not confirmed and not provisional and angles:
        out.append("")
        out.append("Longest-running angles so far (below the confirmation bar):")
        out.append("")
        out.extend(_angle_line(stat) for stat in angles[:3])
    out.append("")

    # 2 — scaling alerts
    out.append("## 2. Scaling alerts")
    out.append("")
    out.append(
        f"_Active ad count up ≥ {config.VELOCITY_MIN_RATIO:g}× and ≥ "
        f"{config.VELOCITY_MIN_DELTA} ads within {config.VELOCITY_WINDOW_DAYS} days. "
        "Fires before the duration threshold can._"
    )
    out.append("")
    if alerts:
        for alert in alerts:
            metro = f" ({alert.metro})" if alert.metro else ""
            out.append(
                f"- **{alert.page_name}**{metro}: {alert.prior_count} → "
                f"{alert.current_count} active ads "
                f"({alert.prior_on.isoformat()} → {alert.current_on.isoformat()}, "
                f"+{alert.delta}, {alert.ratio:.1f}×)"
            )
            for ad in alert.new_ads[:5]:
                label = ad["angle"] or ad["link_title"] or "(no link title, not yet read)"
                count = f" ×{ad['ad_count']}" if ad["ad_count"] > 1 else ""
                url = f" — [snapshot]({ad['snapshot_url']})" if ad["snapshot_url"] else ""
                out.append(f"  - launched {ad['first_seen']}: {label}{count}{url}")
    else:
        out.append("_No page crossed the velocity threshold this week._")
    out.append("")

    # 3 — graveyard
    out.append("## 3. Graveyard — do not test")
    out.append("")
    out.append(
        f"_Angles with a median run ≤ {config.KILL_MAX_DAYS} days across "
        f"≥ {config.GRAVEYARD_MIN_STORES} independent stores, with nobody still "
        "running them._"
    )
    out.append("")
    if dead:
        for stat in dead[:10]:
            out.append(
                f"- **{stat.label}** — median {_fmt_days(stat.median_run_days)} days "
                f"across {stat.store_count} stores ({', '.join(stat.stores)})"
            )
    else:
        out.append("_Nothing has died fast in multiple markets yet._")
    out.append("")

    # 4 — gap list
    out.append("## 4. Gap list — the offense list")
    out.append("")
    out.append("_Winning angles no Louisville competitor is currently running._")
    out.append("")
    if gaps:
        for stat in gaps[:10]:
            flag = "" if stat.cross_confirmed else " _(provisional)_"
            out.append(
                f"- **{stat.label}**{flag} — median {_fmt_days(stat.median_run_days)} days "
                f"at {stat.store_count} stores. {_snapshots(stat.snapshot_urls, 1)}"
            )
    else:
        out.append("_No confirmed winner is currently unclaimed in Louisville._")
    out.append("")

    # 5 — local watch
    out.append("## 5. Local watch")
    out.append("")
    if watches:
        for watch in watches:
            observed = watch.observed_on.isoformat() if watch.observed_on else "n/a"
            out.append(
                f"### {watch.page_name} — {watch.active_count} active ads "
                f"(as of {observed})"
            )
            out.append("")
            out.append(f"- Longest current run: **{watch.longest_run_days} days**")
            if watch.longest_run_days < config.WINNER_MIN_DAYS:
                out.append(
                    "- No proven evergreen creative is being defended here — no ad has "
                    f"reached {config.WINNER_MIN_DAYS} days."
                )
            for ad in watch.newest_ads:
                title = ad["link_title"] or "(no link title)"
                url = f" — [snapshot]({ad['snapshot_url']})" if ad["snapshot_url"] else ""
                out.append(
                    f"- Newest: {title} · first seen {ad['first_seen']} · "
                    f"{ad['run_days']} days{url}"
                )
            out.append("")
    else:
        out.append("_No pages tagged `local` in the seed list._")
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def write(store: Store, asof: dt.date | None = None, path: Any = None) -> Any:
    from pathlib import Path

    asof = asof or today()
    target = Path(path) if path else config.REPORT_DIR / f"weekly-{asof.isoformat()}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build(store, asof))
    return target
