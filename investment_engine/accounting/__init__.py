"""Historical Transaction Ledger – Read-Only Accounting Layer.

This module imports manually exported Trading 212 transaction/activity CSV files
and calculates historical performance without corrupting or replacing live
account reconciliation.

Key principles:
- Read-only: never calls Trading 212 API or any external service
- Source priority: actual CSV > manual adjustments > broker API (if verified)
- Decimal for all monetary calculations
- Timezone-aware timestamps
- Unknown events force PARTIAL status unless explicitly ignored
- Raw CSV rows preserved locally only, never in user-facing reports

This module is independent from the live portfolio reconciliation in
trading212_portfolio.py and investment_engine/portfolio/.
"""

from investment_engine.accounting.fees import (
    FeeCategory,
    categorize_fee,
)
from investment_engine.accounting.importers.t212_csv import (
    detect_csv_type,
    import_t212_activity_csv,
    import_t212_cash_csv,
)
from investment_engine.accounting.ledger import (
    Ledger,
    build_ledger,
)
from investment_engine.accounting.lot_matching import (
    MatchingResult,
    match_sell_fifo,
)
from investment_engine.accounting.models import (
    EventType,
    LedgerEvent,
    LedgerSummary,
    Lot,
    ManualAdjustments,
    MatchedTrade,
    ParseStatus,
)
from investment_engine.accounting.performance import (
    PerformanceResult,
    calculate_performance,
)
from investment_engine.accounting.reconciliation import (
    ReconciliationResult,
    reconcile_ledger,
)

__all__ = [
    # Models
    "EventType",
    "FeeCategory",
    # Ledger
    "Ledger",
    "LedgerEvent",
    "LedgerSummary",
    "Lot",
    "ManualAdjustments",
    "MatchedTrade",
    "MatchingResult",
    "ParseStatus",
    "PerformanceResult",
    "ReconciliationResult",
    "build_ledger",
    # Performance
    "calculate_performance",
    # Fees
    "categorize_fee",
    "detect_csv_type",
    # Importers
    "import_t212_activity_csv",
    "import_t212_cash_csv",
    # Lot matching
    "match_sell_fifo",
    # Reconciliation
    "reconcile_ledger",
]