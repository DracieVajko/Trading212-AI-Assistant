"""Social platform access status (WP4d).

Tracks per-platform access status instead of silently failing.
No scraping of X/StockTwits/Instagram/Facebook without permitted access.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class AccessStatus(Enum):
    SUCCESS_WITH_ITEMS = "SUCCESS_WITH_ITEMS"
    SUCCESS_EMPTY = "SUCCESS_EMPTY"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    ACCESS_RESTRICTED = "ACCESS_RESTRICTED"


@dataclass
class PlatformStatus:
    platform: str
    status: AccessStatus
    items_collected: int = 0
    error: str = ""
    attempted_at: str = ""
    access_notes: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


# Known platforms and their access status
PLATFORM_REGISTRY = {
    "reddit": {
        "name": "Reddit",
        "access_method": "public JSON API (no auth)",
        "status": AccessStatus.SUCCESS_WITH_ITEMS,
        "notes": "Public JSON endpoints; rate-limited; public posts only",
    },
    "slovak_press": {
        "name": "Slovak Press (sme/pravda/aktuality)",
        "access_method": "RSS",
        "status": AccessStatus.SUCCESS_WITH_ITEMS,
        "notes": "Official RSS feeds; headlines + links only",
    },
    "google_news": {
        "name": "Google News RSS",
        "access_method": "RSS",
        "status": AccessStatus.SUCCESS_WITH_ITEMS,
        "notes": "Aggregator URL; headlines + links only",
    },
    "tradingview_news": {
        "name": "TradingView Symbol News",
        "access_method": "Public HTTPS JSON",
        "status": AccessStatus.SUCCESS_WITH_ITEMS,
        "notes": "Distributor; origin publisher preserved separately",
    },
    "tradingview_technicals": {
        "name": "TradingView Technicals",
        "access_method": "Playwright (opt-in)",
        "status": AccessStatus.SUCCESS_WITH_ITEMS,
        "notes": "Opt-in, low frequency, data-facts only",
    },
    "tradingview_facts": {
        "name": "TradingView Key Facts",
        "access_method": "Playwright (opt-in)",
        "status": AccessStatus.SUCCESS_WITH_ITEMS,
        "notes": "Opt-in, low frequency, data-facts only",
    },
    "tradingview_ideas": {
        "name": "TradingView User Ideas",
        "access_method": "Playwright (opt-in)",
        "status": AccessStatus.NOT_IMPLEMENTED,
        "notes": "User-idea content type not collected; no permitted adapter",
    },
    "x_twitter": {
        "name": "X (Twitter)",
        "access_method": "Official API (requires paid tier)",
        "status": AccessStatus.ACCESS_RESTRICTED,
        "notes": "No permitted adapter in this codebase; requires paid API tier + approval",
    },
    "stocktwits": {
        "name": "StockTwits",
        "access_method": "Official API (requires approval)",
        "status": AccessStatus.ACCESS_RESTRICTED,
        "notes": "No permitted adapter; requires API approval",
    },
    "facebook_instagram": {
        "name": "Facebook/Instagram",
        "access_method": "Graph API (requires approval)",
        "status": AccessStatus.ACCESS_RESTRICTED,
        "notes": "No permitted adapter; requires Meta developer approval",
    },
    "stocktwits_api": {
        "name": "StockTwits API",
        "access_method": "Official API",
        "status": AccessStatus.ACCESS_RESTRICTED,
        "notes": "Requires API approval",
    },
    "private_forums": {
        "name": "Private Forums/Groups",
        "access_method": "No access",
        "status": AccessStatus.ACCESS_RESTRICTED,
        "notes": "Private forums and groups require explicit authorized access",
    },
}


def get_platform_status(platform: str) -> PlatformStatus:
    """Get the static status for a platform."""
    reg = PLATFORM_REGISTRY.get(platform.lower())
    if not reg:
        return PlatformStatus(platform=platform, status=AccessStatus.NOT_IMPLEMENTED,
                              error="Unknown platform")
    return PlatformStatus(
        platform=reg["name"],
        status=reg["status"],
        access_notes=reg["notes"],
    )


def get_all_platform_statuses() -> list[dict]:
    """Return status for all registered platforms."""
    return [get_platform_status(p).to_dict() for p in PLATFORM_REGISTRY]


def record_platform_attempt(platform: str, status: AccessStatus, items: int = 0,
                           error: str = "") -> dict:
    """Record a platform attempt for the current run (for manifest)."""
    return {
        "platform": platform,
        "status": status.value,
        "items_collected": items,
        "error": error,
        "attempted_at": datetime.now(timezone.utc).isoformat(),
    }


# Import at module level to avoid circular
from datetime import datetime, timezone


def get_social_platform_statuses() -> list[dict]:
    """Return all platform statuses for manifest inclusion."""
    return get_all_platform_statuses()


if __name__ == "__main__":
    import json
    print(json.dumps(get_all_platform_statuses(), indent=2))