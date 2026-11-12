"""Trading 212 order client (demo/live). Disabled by default at the caller."""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Any
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

ALLOWED_PATHS = {
    "/api/v0/equity/account/summary",
    "/api/v0/equity/positions",
    "/api/v0/equity/orders",
    "/api/v0/equity/orders/market",
    "/api/v0/equity/orders/limit",
    "/api/v0/equity/orders/stop",
    "/api/v0/equity/orders/stop_limit",
}


class T212OrderClient:
    def __init__(self, environment: str, api_key: str, api_secret: str = ""):
        if environment not in ("demo", "live"):
            raise ValueError("environment must be demo or live")
        if not api_key:
            raise ValueError("api_key is required")
        host = "https://demo.trading212.com" if environment == "demo" else "https://live.trading212.com"
        self.environment = environment
        self.base_url = host
        self.api_base = f"{host}/api/v0"
        self.session = requests.Session()
        creds = base64.b64encode(f"{api_key}:{api_secret}".encode("utf-8")).decode("ascii")
        self._auth = f"Basic {creds}"
        self._last_call = 0.0
        self._min_interval = 1.2

    def _throttle(self) -> None:
        now = time.monotonic()
        wait = self._min_interval - (now - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        params: dict | None = None,
        timeout: int = 30,
        max_retries: int = 5,
    ) -> dict[str, Any]:
        if path not in ALLOWED_PATHS and not path.startswith("/api/v0/equity/orders/"):
            return {"error": f"disallowed path: {path}", "status": "forbidden"}
        if method.upper() in ("POST", "DELETE") and self.environment == "live":
            if os.getenv("T212_LIVE_ORDER_ENABLED", "0") != "1" or os.getenv("T212_LIVE_ACK", "") != "I_UNDERSTAND_LIVE_TRADING":
                return {"status": "blocked", "error": "live order execution disabled"}

        method_u = method.upper()
        if method_u not in ("GET", "POST", "DELETE"):
            return {"error": f"unsupported method {method}", "status": "forbidden"}

        url = f"{self.base_url}{path}"
        headers = {"Authorization": self._auth, "Content-Type": "application/json"}

        last_error: dict[str, Any] = {"error": "request failed", "status": "error"}
        for attempt in range(max_retries):
            self._throttle()
            try:
                if method_u == "GET":
                    resp = self.session.get(url, headers=headers, params=params, timeout=timeout)
                elif method_u == "POST":
                    resp = self.session.post(url, headers=headers, json=json_body, timeout=timeout)
                else:
                    resp = self.session.delete(url, headers=headers, timeout=timeout)
            except (requests.Timeout, requests.ConnectionError, requests.RequestException) as exc:
                last_error = {"error": f"{type(exc).__name__}: {exc}", "status": "network_error"}
                logger.warning("T212 %s %s network error (attempt %d/%d): %s", method_u, path, attempt + 1, max_retries, exc)
                if attempt < max_retries - 1:
                    time.sleep(min(2 ** attempt, 30))
                    continue
                return last_error

            if resp.status_code == 429:
                try:
                    retry_after = int(resp.headers.get("Retry-After", "") or "")
                except (TypeError, ValueError):
                    retry_after = 0
                if retry_after <= 0:
                    retry_after = min(2 ** attempt * 2, 60)
                retry_after = min(retry_after, 60)
                logger.warning("T212 %s %s rate limited 429 (attempt %d/%d); sleeping %ds", method_u, path, attempt + 1, max_retries, retry_after)
                if attempt < max_retries - 1:
                    time.sleep(retry_after)
                    continue
                return {"error": "rate limited (429) after retries", "status": "rate_limited"}

            if resp.status_code in (200, 201):
                try:
                    return resp.json() if resp.content else {"success": True}
                except Exception:
                    return {"success": True, "status": "ok"}

            if resp.status_code == 401:
                return {"error": "Unauthorized", "status": "auth_failed"}
            if resp.status_code == 403:
                return {"error": "Forbidden - missing orders:execute scope", "status": "forbidden"}
            if resp.status_code == 404:
                return {"error": f"404 Not Found: {path}", "status": "not_found"}

            if resp.status_code >= 500:
                last_error = {"error": f"server error {resp.status_code}", "status": "server_error"}
                logger.warning("T212 %s %s server error %d (attempt %d/%d)", method_u, path, resp.status_code, attempt + 1, max_retries)
                if attempt < max_retries - 1:
                    time.sleep(min(2 ** attempt, 30))
                    continue
                return last_error

            try:
                body = resp.json()
            except Exception:
                body = resp.text[:500]
            return {"error": f"HTTP {resp.status_code}", "status": "error", "body": body}

        return last_error

    def get_account_summary(self) -> dict[str, Any]:
        return self._request("GET", "/api/v0/equity/account/summary")

    def get_positions(self) -> dict[str, Any]:
        return self._request("GET", "/api/v0/equity/positions")

    def get_orders(self) -> dict[str, Any]:
        return self._request("GET", "/api/v0/equity/orders")

    def get_order(self, order_id: int | str) -> dict[str, Any]:
        return self._request("GET", f"/api/v0/equity/orders/{order_id}")

    def cancel_order(self, order_id: int | str) -> dict[str, Any]:
        return self._request("DELETE", f"/api/v0/equity/orders/{order_id}")

    def place_market_order(self, ticker: str, quantity: float, extended_hours: bool = False) -> dict[str, Any]:
        body: dict[str, Any] = {"ticker": ticker, "quantity": quantity}
        if extended_hours:
            body["extendedHours"] = True
        return self._request("POST", "/api/v0/equity/orders/market", json_body=body)

    def place_limit_order(self, ticker: str, quantity: float, limit_price: float, time_in_force: str = "DAY", extended_hours: bool = False) -> dict[str, Any]:
        body: dict[str, Any] = {"ticker": ticker, "quantity": quantity, "limitPrice": limit_price}
        # timeInForce/extendedHours are accepted by some environments but rejected
        # by the current beta for limit orders; omit them to use server defaults.
        return self._request("POST", "/api/v0/equity/orders/limit", json_body=body)

    def place_stop_order(self, ticker: str, quantity: float, stop_price: float, time_in_force: str = "DAY", extended_hours: bool = False) -> dict[str, Any]:
        body: dict[str, Any] = {"ticker": ticker, "quantity": quantity, "stopPrice": stop_price}
        return self._request("POST", "/api/v0/equity/orders/stop", json_body=body)

    def place_stop_limit_order(self, ticker: str, quantity: float, stop_price: float, limit_price: float, time_in_force: str = "DAY", extended_hours: bool = False) -> dict[str, Any]:
        body: dict[str, Any] = {"ticker": ticker, "quantity": quantity, "stopPrice": stop_price, "limitPrice": limit_price}
        return self._request("POST", "/api/v0/equity/orders/stop_limit", json_body=body)
