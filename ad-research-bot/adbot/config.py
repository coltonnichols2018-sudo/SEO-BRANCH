"""Tunable constants and paths.

Every threshold here traces back to a line in the build spec; the spec
reasoning is quoted so nobody "tidies up" a number that is load-bearing.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent

DATA_DIR = Path(os.environ.get("ADBOT_DATA_DIR", PROJECT_ROOT / "data"))
REPORT_DIR = Path(os.environ.get("ADBOT_REPORT_DIR", PROJECT_ROOT / "reports"))
DB_PATH = Path(os.environ.get("ADBOT_DB", DATA_DIR / "adbot.sqlite3"))
SEEDS_PATH = Path(os.environ.get("ADBOT_SEEDS", PROJECT_ROOT / "seeds.json"))

# --- Stage 0: harvester -----------------------------------------------------
# "3-5 word phrases that plausibly appear in a furniture retailer's ad title.
#  Longer returns nothing; shorter returns ebook and short-drama spam."
PHRASE_MIN_WORDS = 3
PHRASE_MAX_WORDS = 5
HARVEST_LIMIT = 40
HARVEST_COUNTRIES = ("US",)

# "Keep only pages matching ... Drop anything matching ..." Roughly 80% of raw
# results are affiliate spam, so the drop list wins ties.
PAGE_NAME_KEEP = re.compile(
    r"furniture|mattress|home|sofa|sleep|interiors|d[eé]cor|warehouse", re.I
)
PAGE_NAME_DROP = re.compile(
    r"novel|drama|read|chapter|story|chatme|romance", re.I
)

SEED_TARGET_MIN = 25
SEED_TARGET_MAX = 30

# --- Stage 1: daily poll ----------------------------------------------------
POLL_LIMIT = 50
POLL_COUNTRIES = ("US",)

# --- Stage 2: vision pass ---------------------------------------------------
# "Trigger only on: (a) newly appeared ads, (b) ads crossing the 30-day mark."
VISION_MATURITY_DAYS = 30

# --- Scoring ----------------------------------------------------------------
# "An ad live 45+ days on a small-business page is almost certainly profitable."
WINNER_MIN_DAYS = 45
# "Ads dead inside 7 days failed."
KILL_MAX_DAYS = 7
# "The same angle running 45+ days at four unrelated stores in four metros."
CROSS_MARKET_MIN_STORES = 4
# An angle only reaches the graveyard once more than one market has killed it.
GRAVEYARD_MIN_STORES = 2
# "A page going 8 -> 40 active ads inside a week found something."
VELOCITY_MIN_RATIO = 2.0
VELOCITY_MIN_DELTA = 5
VELOCITY_WINDOW_DAYS = 7

# --- Roles ------------------------------------------------------------------
ROLE_LOCAL = "local"
ROLE_OUT_OF_MARKET = "out_of_market"
# "Tag it reference, not competitor, and exclude it from trend scoring."
ROLE_REFERENCE = "reference"
ROLES = (ROLE_LOCAL, ROLE_OUT_OF_MARKET, ROLE_REFERENCE)
SCORING_ROLES = (ROLE_OUT_OF_MARKET,)

GRAPH_API_VERSION = "v21.0"
GRAPH_API_BASE = "https://graph.facebook.com"
TOKEN_ENV = "META_ADS_LIBRARY_TOKEN"

AD_FIELDS = (
    "id",
    "page_id",
    "page_name",
    "ad_creative_link_titles",
    "ad_creation_time",
    "ad_delivery_start_time",
    "ad_delivery_stop_time",
    "ad_snapshot_url",
)
