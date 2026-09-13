"""Tests for the rules the spec calls load-bearing."""

from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adbot import config, harvester, poll, report, scoring, vision  # noqa: E402
from adbot.models import PageSeed, normalize_file, normalize_pull  # noqa: E402
from adbot.store import Store  # noqa: E402

DAY = dt.timedelta(days=1)
TODAY = dt.date(2026, 9, 13)


def ad(ad_id, page_id, page_name, start, title=None, snapshot=None):
    return {
        "id": ad_id,
        "page_id": page_id,
        "page_name": page_name,
        "ad_delivery_start_time": start.isoformat() + "T08:00:00+0000",
        "ad_creative_link_titles": [title] if title else [],
        "ad_snapshot_url": snapshot or f"https://facebook.com/ads/library/?id={ad_id}",
    }


def pull(page_id, ads, count=None):
    body = {"data": ads}
    if count is not None:
        body["estimated_total_count"] = count
    return {"page_id": page_id, "response": body}


class PhraseRuleTests(unittest.TestCase):
    def test_three_to_five_words_accepted(self):
        self.assertEqual(len(harvester.check_phrase("Louisville Overstock Furniture")), 3)
        self.assertEqual(len(harvester.check_phrase("Furniture and Mattress Store Sale")), 5)

    def test_single_word_rejected(self):
        with self.assertRaises(harvester.PhraseLengthError):
            harvester.check_phrase("BoxDrop")

    def test_seven_words_rejected(self):
        with self.assertRaises(harvester.PhraseLengthError):
            harvester.check_phrase("Sectional Sofa Queen Bedroom Set Clearance Warehouse")


class PageNameFilterTests(unittest.TestCase):
    def test_keeps_furniture_retailers(self):
        for name in ["NashCo Furniture", "Sleep Outfitters", "Home Décor Warehouse",
                     "Sofa City", "Kassa Mall Home Furniture and Mattress"]:
            self.assertTrue(harvester.is_store_name(name), name)

    def test_drops_spam(self):
        for name in ["Billionaire Romance Chapter 12", "ChatMe Stories",
                     "Read Drama Now", ""]:
            self.assertFalse(harvester.is_store_name(name), name)

    def test_drop_list_beats_keep_list(self):
        # Spam pages often stuff retail words in; the drop list has to win.
        self.assertFalse(harvester.is_store_name("Romance Home Story Novel"))

    def test_harvest_filters_and_counts(self):
        pulls = normalize_file(
            {
                "pulls": [
                    {
                        "response": {
                            "search_terms": "Furniture and Mattress Store",
                            "data": [
                                ad("1", "900", "Dayton Furniture Outlet", TODAY),
                                ad("2", "900", "Dayton Furniture Outlet", TODAY),
                                ad("3", "901", "Billionaire Romance Chapter 9", TODAY),
                                ad("4", "91223253446", "Louisville Overstock", TODAY),
                            ],
                        }
                    }
                ]
            }
        )
        result = harvester.harvest(pulls, known_page_ids={"91223253446"})
        self.assertEqual([c.page_id for c in result.candidates], ["900"])
        self.assertEqual(result.candidates[0].ad_count, 2)
        self.assertEqual(result.raw_ads, 4)
        # "Louisville Overstock" matches no keep-word, so the discovery filter
        # drops it too. Stores like that are why the spec adds locals by hand.
        self.assertEqual(result.kept_ads, 2)
        self.assertIn("Billionaire Romance Chapter 9", result.dropped_pages)


class NormalisationTests(unittest.TestCase):
    def test_accepts_several_envelopes(self):
        rows = [ad("10", "500", "Kassa Mall Home Furniture and Mattress", TODAY)]
        for payload in (rows, {"data": rows}, {"ads": rows}, {"results": rows}):
            self.assertEqual(len(normalize_pull(payload).ads), 1)

    def test_page_id_inferred_when_unambiguous(self):
        parsed = normalize_pull({"data": [ad("10", "500", "Kassa Mall", TODAY)]})
        self.assertEqual(parsed.page_id, "500")

    def test_blank_link_title_survives(self):
        parsed = normalize_pull({"data": [ad("10", "500", "Kassa Mall", TODAY)]})
        self.assertIsNone(parsed.ads[0].link_title)

    def test_rows_without_ids_are_dropped(self):
        parsed = normalize_pull({"data": [{"page_name": "nope"}]})
        self.assertEqual(parsed.ads, [])


class PollDiffTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.store.upsert_page(PageSeed("500", "Kassa Mall", config.ROLE_OUT_OF_MARKET, "Memphis"))

    def tearDown(self):
        self.store.close()

    def test_missing_ad_is_marked_ended(self):
        day1, day2 = TODAY - 2 * DAY, TODAY - DAY
        poll.ingest(
            self.store,
            {"pulls": [pull("500", [ad("a", "500", "Kassa Mall", day1),
                                    ad("b", "500", "Kassa Mall", day1)])]},
            observed_on=day1,
        )
        poll.ingest(
            self.store,
            {"pulls": [pull("500", [ad("a", "500", "Kassa Mall", day1)])]},
            observed_on=day2,
        )
        self.assertIsNone(self.store.ad("a")["ended_on"])
        self.assertEqual(self.store.ad("b")["ended_on"], day2.isoformat())

    def test_reappearing_ad_clears_end_date(self):
        day1, day2, day3 = TODAY - 2 * DAY, TODAY - DAY, TODAY
        for day, ads in ((day1, ["a"]), (day2, []), (day3, ["a"])):
            poll.ingest(
                self.store,
                {"pulls": [pull("500", [ad(i, "500", "Kassa Mall", day1) for i in ads])]},
                observed_on=day,
            )
        self.assertIsNone(self.store.ad("a")["ended_on"])

    def test_ingesting_the_same_day_twice_is_idempotent(self):
        payload = {"pulls": [pull("500", [ad("a", "500", "Kassa Mall", TODAY)])]}
        poll.ingest(self.store, payload, observed_on=TODAY)
        poll.ingest(self.store, payload, observed_on=TODAY)
        self.assertEqual(len(self.store.ads()), 1)
        self.assertEqual(len(self.store.counts(page_id="500")), 1)
        self.assertIsNone(self.store.ad("a")["ended_on"])

    def test_other_pages_are_untouched_by_one_pages_pull(self):
        self.store.upsert_page(PageSeed("600", "NashCo Furniture", metro="Nashville"))
        day1 = TODAY - DAY
        poll.ingest(
            self.store,
            {"pulls": [pull("500", [ad("a", "500", "Kassa Mall", day1)]),
                       pull("600", [ad("z", "600", "NashCo Furniture", day1)])]},
            observed_on=day1,
        )
        poll.ingest(self.store, {"pulls": [pull("500", [])]}, observed_on=TODAY)
        self.assertEqual(self.store.ad("a")["ended_on"], TODAY.isoformat())
        self.assertIsNone(self.store.ad("z")["ended_on"])

    def test_estimated_total_count_is_logged_daily(self):
        poll.ingest(
            self.store,
            {"pulls": [pull("500", [ad("a", "500", "Kassa Mall", TODAY)], count=37)]},
            observed_on=TODAY,
        )
        counts = self.store.counts(page_id="500")
        self.assertEqual(counts[-1]["active_ad_count"], 37)

    def test_unattributed_pull_does_not_end_ads(self):
        poll.ingest(
            self.store,
            {"pulls": [pull("500", [ad("a", "500", "Kassa Mall", TODAY),
                                    ad("b", "600", "NashCo Furniture", TODAY)])]},
            observed_on=TODAY - DAY,
        )
        summary = poll.ingest(self.store, {"data": []}, observed_on=TODAY)
        self.assertEqual(summary["unattributed_pulls"], 1)
        self.assertIsNone(self.store.ad("a")["ended_on"])


class VisionQueueTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.store.upsert_page(PageSeed("500", "Kassa Mall", metro="Memphis"))

    def tearDown(self):
        self.store.close()

    def test_new_and_day30_ads_queue_but_mid_life_ads_do_not(self):
        old_start = TODAY - dt.timedelta(days=40)
        mid_start = TODAY - dt.timedelta(days=10)
        poll.ingest(
            self.store,
            {"pulls": [pull("500", [ad("old", "500", "Kassa Mall", old_start),
                                    ad("mid", "500", "Kassa Mall", mid_start)])]},
            observed_on=TODAY - DAY,
        )
        poll.ingest(
            self.store,
            {"pulls": [pull("500", [ad("old", "500", "Kassa Mall", old_start),
                                    ad("mid", "500", "Kassa Mall", mid_start),
                                    ad("fresh", "500", "Kassa Mall", TODAY)])]},
            observed_on=TODAY,
        )
        queued = {task.ad_id: task.trigger for task in vision.queue(self.store, asof=TODAY)}
        self.assertEqual(queued.get("fresh"), vision.TRIGGER_NEW)
        self.assertEqual(queued.get("old"), vision.TRIGGER_DAY30)
        self.assertNotIn("mid", queued)

    def test_ad_that_appeared_between_vision_runs_still_queues(self):
        # Vision may run weekly while the poll runs daily; an ad that launched
        # three days ago must not have to wait until day 30 to be read.
        poll.ingest(
            self.store,
            {"pulls": [pull("500", [ad("seed", "500", "Kassa Mall", TODAY - 20 * DAY)])]},
            observed_on=TODAY - 10 * DAY,
        )
        poll.ingest(
            self.store,
            {"pulls": [pull("500", [ad("seed", "500", "Kassa Mall", TODAY - 20 * DAY),
                                    ad("later", "500", "Kassa Mall", TODAY - 3 * DAY)])]},
            observed_on=TODAY - 3 * DAY,
        )
        poll.ingest(
            self.store,
            {"pulls": [pull("500", [ad("seed", "500", "Kassa Mall", TODAY - 20 * DAY),
                                    ad("later", "500", "Kassa Mall", TODAY - 3 * DAY)])]},
            observed_on=TODAY,
        )
        queued = {task.ad_id: task.trigger for task in vision.queue(self.store, asof=TODAY)}
        self.assertEqual(queued.get("later"), vision.TRIGGER_NEW)
        # The ad already live at the first poll is backfill, not new.
        self.assertNotIn("seed", queued)

    def test_processed_ads_are_never_requeued(self):
        poll.ingest(
            self.store,
            {"pulls": [pull("500", [ad("fresh", "500", "Kassa Mall", TODAY)])]},
            observed_on=TODAY,
        )
        vision.ingest_vision(
            self.store,
            [{"ad_id": "fresh", "offer_type": "0% APR financing", "urgency": "ends Sunday"}],
            asof=TODAY,
        )
        self.assertEqual(vision.queue(self.store, asof=TODAY), [])
        stored = self.store.vision("fresh")
        self.assertEqual(stored["offer_type"], "financing")
        self.assertEqual(stored["urgency"], "deadline")

    def test_vision_errors_are_not_recorded(self):
        poll.ingest(
            self.store,
            {"pulls": [pull("500", [ad("fresh", "500", "Kassa Mall", TODAY)])]},
            observed_on=TODAY,
        )
        result = vision.ingest_vision(
            self.store, [{"ad_id": "fresh", "error": "unavailable"}], asof=TODAY
        )
        self.assertEqual(result["errored"], 1)
        self.assertIsNone(self.store.vision("fresh"))


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.metros = {
            "500": "Memphis", "600": "Nashville", "700": "Indianapolis",
            "800": "Birmingham", "900": "Columbus",
        }
        for page_id, metro in self.metros.items():
            self.store.upsert_page(
                PageSeed(page_id, f"Store {metro}", config.ROLE_OUT_OF_MARKET, metro)
            )
        self.store.upsert_page(
            PageSeed("91223253446", "Louisville Overstock", config.ROLE_LOCAL, "Louisville")
        )
        self.store.upsert_page(
            PageSeed("111", "Ashley HomeStore", config.ROLE_REFERENCE, None)
        )

    def tearDown(self):
        self.store.close()

    def _seed_angle(self, page_ids, days, offer, urgency, ad_prefix, ended=False):
        start = TODAY - dt.timedelta(days=days)
        pulls = [
            pull(page_id, [ad(f"{ad_prefix}-{page_id}", page_id, f"Store {page_id}", start)])
            for page_id in page_ids
        ]
        poll.ingest(self.store, {"pulls": pulls}, observed_on=TODAY - DAY)
        if ended:
            poll.ingest(
                self.store,
                {"pulls": [pull(page_id, []) for page_id in page_ids]},
                observed_on=TODAY,
            )
        for page_id in page_ids:
            vision.ingest_vision(
                self.store,
                [{
                    "ad_id": f"{ad_prefix}-{page_id}",
                    "offer_type": offer,
                    "urgency": urgency,
                    "hook": "Hook",
                }],
                asof=TODAY,
            )

    def test_forty_five_day_angle_across_four_metros_is_cross_confirmed(self):
        self._seed_angle(["500", "600", "700", "800"], 50, "financing", "deadline", "fin")
        winners = [s for s in scoring.winning_angles(self.store, TODAY) if s.cross_confirmed]
        self.assertEqual(len(winners), 1)
        self.assertEqual(winners[0].store_count, 4)
        self.assertEqual(winners[0].metro_count, 4)
        self.assertGreaterEqual(winners[0].median_run_days, config.WINNER_MIN_DAYS)

    def test_three_stores_is_not_enough(self):
        self._seed_angle(["500", "600", "700"], 60, "bogo", "none", "bogo")
        self.assertEqual(
            [s for s in scoring.winning_angles(self.store, TODAY) if s.cross_confirmed], []
        )

    def test_long_run_at_one_store_is_not_confirmed(self):
        self._seed_angle(["500"], 120, "percent_off", "deadline", "pct")
        stats = scoring.winning_angles(self.store, TODAY)
        self.assertEqual(stats[0].store_count, 1)
        self.assertFalse(stats[0].cross_confirmed)

    def test_unknown_metro_holds_an_angle_at_provisional(self):
        for page_id in ["500", "600", "700", "800"]:
            self.store.upsert_page(PageSeed(page_id, f"Store {page_id}", metro=None))
        self._seed_angle(["500", "600", "700", "800"], 50, "financing", "deadline", "fin")
        stats = scoring.winning_angles(self.store, TODAY)
        self.assertFalse(stats[0].cross_confirmed)
        self.assertTrue(stats[0].provisional)

    def test_reference_and_local_pages_are_excluded_from_trends(self):
        self._seed_angle(["500", "600", "700", "111", "91223253446"], 90,
                         "event", "event", "evt")
        stats = scoring.winning_angles(self.store, TODAY)
        self.assertEqual(stats[0].store_count, 3)  # only the out-of-market pages

    def test_one_page_running_many_variants_counts_once(self):
        start = TODAY - dt.timedelta(days=60)
        ads = [ad(f"v{i}", "500", "Store Memphis", start) for i in range(20)]
        poll.ingest(self.store, {"pulls": [pull("500", ads)]}, observed_on=TODAY)
        for i in range(20):
            vision.ingest_vision(
                self.store,
                [{"ad_id": f"v{i}", "offer_type": "percent_off", "urgency": "deadline"}],
                asof=TODAY,
            )
        stats = scoring.winning_angles(self.store, TODAY)
        self.assertEqual(stats[0].store_count, 1)
        self.assertEqual(stats[0].ad_count, 20)
        self.assertFalse(stats[0].cross_confirmed)

    def test_fast_deaths_in_two_markets_land_in_the_graveyard(self):
        self._seed_angle(["500", "600"], 4, "bogo", "stock_scarcity", "dead", ended=True)
        dead = scoring.graveyard(self.store, TODAY)
        self.assertEqual(len(dead), 1)
        self.assertLessEqual(dead[0].median_run_days, config.KILL_MAX_DAYS)

    def test_an_angle_still_live_somewhere_is_not_buried(self):
        self._seed_angle(["500", "600"], 4, "bogo", "stock_scarcity", "dead", ended=True)
        self._seed_angle(["700"], 3, "bogo", "stock_scarcity", "live")
        self.assertEqual(scoring.graveyard(self.store, TODAY), [])

    def test_velocity_jump_is_flagged_with_its_new_creative(self):
        week_ago = TODAY - dt.timedelta(days=8)
        poll.ingest(
            self.store,
            {"pulls": [pull("500", [ad("old1", "500", "Store Memphis", week_ago)], count=8)]},
            observed_on=week_ago,
        )
        fresh = [ad(f"n{i}", "500", "Store Memphis", TODAY) for i in range(40)]
        poll.ingest(self.store, {"pulls": [pull("500", fresh, count=40)]}, observed_on=TODAY)
        alerts = scoring.scaling_alerts(self.store, TODAY)
        self.assertEqual(len(alerts), 1)
        self.assertEqual((alerts[0].prior_count, alerts[0].current_count), (8, 40))
        self.assertTrue(alerts[0].new_ads)

    def test_scaling_burst_is_grouped_by_angle(self):
        week_ago = TODAY - dt.timedelta(days=8)
        poll.ingest(
            self.store,
            {"pulls": [pull("500", [ad("o", "500", "Store Memphis", week_ago)], count=3)]},
            observed_on=week_ago,
        )
        burst = [
            ad(f"n{i}", "500", "Store Memphis", TODAY, title="Labor Day Blowout Ends Sunday")
            for i in range(15)
        ]
        poll.ingest(self.store, {"pulls": [pull("500", burst, count=18)]}, observed_on=TODAY)
        alert = scoring.scaling_alerts(self.store, TODAY)[0]
        self.assertEqual(len(alert.new_ads), 1)
        self.assertEqual(alert.new_ads[0]["ad_count"], 15)

    def test_small_increase_is_not_an_alert(self):
        week_ago = TODAY - dt.timedelta(days=8)
        poll.ingest(
            self.store,
            {"pulls": [pull("500", [ad("o", "500", "Store Memphis", week_ago)], count=10)]},
            observed_on=week_ago,
        )
        poll.ingest(
            self.store,
            {"pulls": [pull("500", [ad("o", "500", "Store Memphis", week_ago)], count=13)]},
            observed_on=TODAY,
        )
        self.assertEqual(scoring.scaling_alerts(self.store, TODAY), [])

    def test_gap_list_excludes_angles_louisville_already_runs(self):
        self._seed_angle(["500", "600", "700", "800"], 50, "financing", "deadline", "fin")
        self.assertEqual(len(scoring.gap_list(self.store, TODAY)), 1)
        poll.ingest(
            self.store,
            {"pulls": [pull("91223253446",
                            [ad("loc", "91223253446", "Louisville Overstock", TODAY)])]},
            observed_on=TODAY,
        )
        vision.ingest_vision(
            self.store,
            [{"ad_id": "loc", "offer_type": "financing", "urgency": "deadline"}],
            asof=TODAY,
        )
        self.assertEqual(scoring.gap_list(self.store, TODAY), [])

    def test_local_watch_reports_count_and_newest_creative(self):
        poll.ingest(
            self.store,
            {"pulls": [pull("91223253446",
                            [ad("l1", "91223253446", "Louisville Overstock",
                                dt.date(2026, 9, 3), title="$498 Cayboni Bedroom Set"),
                             ad("l2", "91223253446", "Louisville Overstock",
                                dt.date(2026, 9, 10), title="$288 Loreo Sofa")],
                            count=2)]},
            observed_on=TODAY,
        )
        watch = scoring.local_watch(self.store, TODAY)[0]
        self.assertEqual(watch.active_count, 2)
        self.assertEqual(watch.longest_run_days, 10)
        self.assertEqual(watch.newest_ads[0]["link_title"], "$288 Loreo Sofa")

    def test_title_groups_ads_before_a_vision_pass_exists(self):
        start = TODAY - dt.timedelta(days=50)
        pulls = [
            pull(page_id, [ad(f"t-{page_id}", page_id, f"Store {page_id}", start,
                              title="Walk-In Exclusive Extra Savings")])
            for page_id in ["500", "600", "700", "800"]
        ]
        poll.ingest(self.store, {"pulls": pulls}, observed_on=TODAY)
        stats = scoring.winning_angles(self.store, TODAY)
        self.assertEqual(stats[0].store_count, 4)
        self.assertTrue(stats[0].cross_confirmed)

    def test_untitled_unread_ads_do_not_group(self):
        start = TODAY - dt.timedelta(days=50)
        pulls = [pull(p, [ad(f"u-{p}", p, f"Store {p}", start)]) for p in ["500", "600"]]
        poll.ingest(self.store, {"pulls": pulls}, observed_on=TODAY)
        self.assertEqual(scoring.winning_angles(self.store, TODAY), [])


class ReportTests(unittest.TestCase):
    def test_report_has_all_five_sections_even_when_empty(self):
        with Store(":memory:") as store:
            store.upsert_page(
                PageSeed("91223253446", "Louisville Overstock", config.ROLE_LOCAL, "Louisville")
            )
            text = report.build(store, asof=TODAY)
        for heading in [
            "## 1. Cross-confirmed winning angles",
            "## 2. Scaling alerts",
            "## 3. Graveyard",
            "## 4. Gap list",
            "## 5. Local watch",
        ]:
            self.assertIn(heading, text)
        self.assertIn("Duration signal is not live yet", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
