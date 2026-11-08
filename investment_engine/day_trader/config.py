"""Phase 1 day-trader configuration (read-only pack)."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class ScanConfig:
    min_price: float = 5.0
    min_volume: int = 1_000_000
    or_minutes: int = 15


@dataclass
class BudgetConfig:
    account_currency: str = "EUR"
    account_value: float = 1000.0
    max_loss_per_trade: float = 10.0
    max_daily_loss: float = 30.0
    max_trades_per_day: int = 2
    max_position_pct: float = 20.0
    cash_buffer_pct: float = 10.0


@dataclass
class ExecutionConfig:
    enabled: bool = False
    broker: str = "trading212"
    environment: str = "demo"
    auto_approve: bool = False
    max_order_eur: float = 50.0
    max_daily_orders: int = 2
    allowed_sides: list[str] = field(default_factory=lambda: ["BUY"])
    live_ack: str = ""
    unlimited: bool = False


@dataclass
class ReportConfig:
    max_hits: int = 10
    include_pelosi: bool = True


@dataclass
class UniverseConfig:
    include_sp500: bool = True
    include_nasdaq100: bool = False
    include_portfolio: bool = True
    extra_symbols: list[str] = field(default_factory=lambda: [
        # EU/European stocks (EUR-denominated)
        "EXI2.DE", "VWCE.DE", "VWS.CO", "IBE.MC", "RWE.DE", "ENR.DE", "LOM.DE", "SAP.DE",
        "ASML.AS", "MC.PA", "TTE.PA", "SIE.DE", "AIR.PA", "BNP.PA",
        # China/HK stocks (USD/HKD)
        "0700.HK", "9988.HK", "3690.HK", "2318.HK", "1398.HK", "939.HK",
    ])
    max_symbols: int = 500


@dataclass
class FilterConfig:
    enabled: bool = True
    atr_multiple: float = 1.5
    max_recent_drop_pct: float = 8.0


@dataclass
class DayTraderConfig:
    enabled: bool = False
    auto_run: bool = False
    state_dir: str = "data/day_trader"
    timezone: str = "America/New_York"
    universe_limit: int = 200
    watchlist_limit: int = 20
    scan: ScanConfig = field(default_factory=ScanConfig)
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    report: ReportConfig = field(default_factory=ReportConfig)
    universe: UniverseConfig = field(default_factory=UniverseConfig)
    filters: FilterConfig = field(default_factory=FilterConfig)

    def __post_init__(self) -> None:
        if isinstance(self.scan, dict):
            self.scan = ScanConfig(**self.scan)
        if isinstance(self.budget, dict):
            self.budget = BudgetConfig(**self.budget)
        if isinstance(self.execution, dict):
            self.execution = ExecutionConfig(**self.execution)
        if isinstance(self.report, dict):
            self.report = ReportConfig(**self.report)
        if isinstance(self.universe, dict):
            self.universe = UniverseConfig(**self.universe)
        if isinstance(self.filters, dict):
            self.filters = FilterConfig(**self.filters)
        self.validate()

    @classmethod
    def from_mapping(cls, mapping: Any) -> "DayTraderConfig":
        scan_raw = mapping.get("scan", {})
        budget_raw = mapping.get("budget", {})
        exec_raw = mapping.get("execution", {})
        report_raw = mapping.get("report", {})
        universe_raw = mapping.get("universe", {})
        filters_raw = mapping.get("filters", {})
        return cls(
            enabled=bool(mapping.get("enabled", False)),
            auto_run=bool(mapping.get("auto_run", False)),
            state_dir=str(mapping.get("state_dir", "data/day_trader")),
            timezone=str(mapping.get("timezone", "America/New_York")),
            universe_limit=int(mapping.get("universe_limit", 200) or 200),
            watchlist_limit=int(mapping.get("watchlist_limit", 20) or 20),
            scan=ScanConfig(
                min_price=float(scan_raw.get("min_price", 5.0) or 5.0),
                min_volume=int(scan_raw.get("min_volume", 1_000_000) or 1_000_000),
                or_minutes=int(scan_raw.get("or_minutes", 15) or 15),
            ),
            budget=BudgetConfig(
                account_currency=str(budget_raw.get("account_currency", "EUR")),
                account_value=float(budget_raw.get("account_value", 1000.0) or 1000.0),
                max_loss_per_trade=float(budget_raw.get("max_loss_per_trade", 10.0) or 10.0),
                max_daily_loss=float(budget_raw.get("max_daily_loss", 30.0) or 30.0),
                max_trades_per_day=int(budget_raw.get("max_trades_per_day", 2) or 2),
                max_position_pct=float(budget_raw.get("max_position_pct", 20.0) or 20.0),
                cash_buffer_pct=float(budget_raw.get("cash_buffer_pct", 10.0) or 10.0),
            ),
            execution=ExecutionConfig(
                enabled=bool(exec_raw.get("enabled", False)),
                broker=str(exec_raw.get("broker", "trading212")),
                environment=str(exec_raw.get("environment", "demo")),
                auto_approve=bool(exec_raw.get("auto_approve", False)),
                max_order_eur=float(exec_raw.get("max_order_eur", 50.0) or 50.0),
                max_daily_orders=int(exec_raw.get("max_daily_orders", 2) or 2),
                allowed_sides=list(exec_raw.get("allowed_sides", ["BUY"]) or ["BUY"]),
                live_ack=str(exec_raw.get("live_ack", "")),
                unlimited=bool(exec_raw.get("unlimited", False)),
            ),
            report=ReportConfig(
                max_hits=int(report_raw.get("max_hits", 10) or 10),
                include_pelosi=bool(report_raw.get("include_pelosi", True)),
            ),
            universe=UniverseConfig(
                include_sp500=bool(universe_raw.get("include_sp500", True)),
                include_nasdaq100=bool(universe_raw.get("include_nasdaq100", False)),
                include_portfolio=bool(universe_raw.get("include_portfolio", True)),
                extra_symbols=list(universe_raw["extra_symbols"]) if "extra_symbols" in universe_raw else UniverseConfig().extra_symbols,
                max_symbols=int(universe_raw.get("max_symbols", 500) or 500),
            ),
            filters=FilterConfig(
                enabled=bool(filters_raw.get("enabled", True)),
                atr_multiple=float(filters_raw.get("atr_multiple", 1.5) or 1.5),
                max_recent_drop_pct=float(filters_raw.get("max_recent_drop_pct", 8.0) or 8.0),
            ),
        )

    def validate(self) -> None:
        if self.execution.environment not in ("demo", "live"):
            raise ValueError("execution.environment must be demo or live")
        if self.execution.environment == "live":
            if not self.execution.live_ack:
                raise ValueError("live execution requires execution.live_ack")
            if self.execution.auto_approve:
                raise ValueError("auto_approve is forbidden in live mode")
        if self.universe_limit <= 0:
            raise ValueError("universe_limit must be positive")
        if self.watchlist_limit <= 0:
            raise ValueError("watchlist_limit must be positive")
        if self.budget.account_value < 0:
            raise ValueError("budget.account_value must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
