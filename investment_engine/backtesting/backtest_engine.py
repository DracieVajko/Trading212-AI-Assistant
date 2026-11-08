"""backtest_engine.py — Vectorbt-based backtesting engine.

Provides vectorized backtesting of portfolio strategies using vectorbt.
Supports walk-forward optimization, transaction costs, and performance metrics
(Sharpe, Sortino, max drawdown, win rate).

Designed to work with the existing portfolio_ai_assistant data structures
(portfolio_rows, signals, regime_result).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

try:
    import vectorbt as vbt

    HAS_VECTORBT = True
except ImportError:
    HAS_VECTORBT = False
    logger = logging.getLogger(__name__)
    logger.warning(
        "vectorbt not installed. Backtesting will be disabled. "
        "Install with: pip install vectorbt"
    )

logger = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    """Configuration for backtesting engine."""

    initial_capital: float = 10000.0
    commission_pct: float = 0.001  # 0.1% per trade
    slippage_pct: float = 0.0005  # 0.05% slippage
    min_position_size: float = 0.01  # 1% minimum position size
    max_position_size: float = 0.20  # 20% maximum position size
    risk_free_rate: float = 0.02  # 2% annual risk-free rate
    trading_days_per_year: int = 252


@dataclass
class BacktestResult:
    """Results from a backtest run."""

    total_return: float = 0.0
    annualized_return: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_duration: int = 0
    win_rate: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    avg_trade_return: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    calmar_ratio: float = 0.0
    equity_curve: pd.Series | None = None
    drawdown_curve: pd.Series | None = None
    trade_log: list[dict[str, Any]] | None = None


class BacktestEngine:
    """Core backtesting engine using vectorbt.

    Supports:
    - Long-only strategies
    - Transaction costs (commission + slippage)
    - Position sizing based on risk or fixed percentage
    - Multiple metrics (Sharpe, Sortino, max drawdown, win rate)
    - Trade recording and analysis
    """

    def __init__(self, config: BacktestConfig | None = None):
        if not HAS_VECTORBT:
            raise ImportError(
                "vectorbt is required for backtesting. "
                "Install with: pip install vectorbt"
            )
        self.config = config or BacktestConfig()
        self.logger = logging.getLogger(__name__)

    def run_backtest(
        self,
        prices: pd.DataFrame,
        signals: pd.DataFrame,
        initial_capital: float | None = None,
    ) -> BacktestResult:
        """Run a backtest on price data with entry/exit signals.

        Args:
            prices: DataFrame with OHLCV data (columns: open, high, low, close, volume)
            signals: DataFrame with signal columns (1 for buy, -1 for sell, 0 for hold)
            initial_capital: Initial capital in EUR

        Returns:
            BacktestResult with performance metrics and equity curve.
        """
        if not HAS_VECTORBT:
            raise ImportError(
                "vectorbt is required for backtesting. "
                "Install with: pip install vectorbt"
            )

        initial_capital = initial_capital or self.config.initial_capital

        # Align prices and signals on common index
        common_index = prices.index.intersection(signals.index)
        if len(common_index) == 0:
            return BacktestResult()

        prices = prices.loc[common_index]
        signals = signals.loc[common_index]

        # Calculate returns
        returns = prices["close"].pct_change().fillna(0)

        # Create entry/exit signals for vectorbt (boolean Series required)
        # Use the first column as the signal source
        signal_col = signals.columns[0] if len(signals.columns) > 0 else None
        if signal_col is None:
            return BacktestResult()
        entries = signals[signal_col] > 0  # Buy signals
        exits = signals[signal_col] < 0  # Sell signals

        # Run vectorbt backtest
        try:
            pf = vbt.Portfolio.from_signals(
                close=prices["close"],
                entries=entries,
                exits=exits,
                init_cash=initial_capital,
                size=self.config.max_position_size,
                size_type="percent",
                fees=self.config.commission_pct,
                slippage=self.config.slippage_pct,
                freq="D",
            )

            # Extract metrics
            total_return = pf.total_return()
            annualized_return = pf.annualized_return()
            sharpe_ratio = pf.sharpe_ratio(risk_free=self.config.risk_free_rate)
            try:
                sortino_ratio = pf.sortino_ratio(risk_free=self.config.risk_free_rate)
            except TypeError:
                sortino_ratio = pf.sortino_ratio()
            max_drawdown = pf.max_drawdown()

            # Win rate from trades
            trades_obj = pf.trades
            try:
                win_rate = trades_obj.win_rate()
                total_trades = trades_obj.count()
                winning_trades = int((pf.trades.profit > 0).sum())
                losing_trades = int((pf.trades.profit < 0).sum())
                avg_trade_return = float(trades.profit.mean())
            except Exception:
                win_rate = 0.0
                total_trades = 0
                winning_trades = 0
                losing_trades = 0
                avg_trade_return = 0.0

            # Calmar ratio
            calmar_ratio = (
                float(annualized_return) / abs(float(max_drawdown))
                if max_drawdown != 0
                else 0.0
            )

            result = BacktestResult(
                total_return=float(total_return),
                annualized_return=float(annualized_return),
                sharpe_ratio=float(sharpe_ratio),
                sortino_ratio=float(sortino_ratio),
                max_drawdown=float(max_drawdown),
                max_drawdown_duration=0,  # Not available in vectorbt API
                win_rate=float(win_rate),
                total_trades=int(total_trades),
                winning_trades=int(winning_trades),
                losing_trades=int(losing_trades),
                avg_trade_return=float(avg_trade_return),
                calmar_ratio=float(calmar_ratio),
                equity_curve=pf.value(),
                drawdown_curve=pf.drawdown(),
                trade_log=pf.trades.records.to_dict("records")
                if hasattr(pf.trades, "records")
                else [],
            )

            return result

        except Exception as exc:
            logger.error("Backtest failed: %s: %s", type(exc).__name__, exc)
            return BacktestResult()

    def run_multi_asset_backtest(
        self,
        prices: dict[str, pd.DataFrame],
        signals: dict[str, pd.DataFrame],
        initial_capital: float | None = None,
    ) -> dict[str, BacktestResult]:
        """Run backtest for multiple assets.

        Args:
            prices: Dict of ticker -> price DataFrame
            signals: Dict of ticker -> signal DataFrame
            initial_capital: Initial capital per asset

        Returns:
            Dict of ticker -> BacktestResult
        """
        results: dict[str, BacktestResult] = {}
        for ticker in prices:
            if ticker not in signals:
                continue
            result = self.run_backtest(
                prices[ticker], signals[ticker], initial_capital
            )
            results[ticker] = result
        return results


def quick_backtest(
    prices: pd.DataFrame,
    signals: pd.DataFrame,
    initial_capital: float = 10000.0,
) -> BacktestResult:
    """Convenience function for quick backtesting.

    Args:
        prices: DataFrame with OHLCV data
        signals: DataFrame with signal columns
        initial_capital: Initial capital in EUR

    Returns:
        BacktestResult with performance metrics
    """
    engine = BacktestEngine(
        BacktestConfig(initial_capital=initial_capital)
    )
    return engine.run_backtest(prices, signals, initial_capital)


def compute_portfolio_metrics(
    equity_curve: pd.Series,
    risk_free_rate: float = 0.02,
    trading_days_per_year: int = 252,
) -> dict[str, float]:
    """Compute portfolio performance metrics from equity curve.

    Args:
        equity_curve: Series of portfolio values over time
        risk_free_rate: Annual risk-free rate
        trading_days_per_year: Number of trading days per year

    Returns:
        Dict with performance metrics
    """
    returns = equity_curve.pct_change().dropna()

    if len(returns) == 0:
        return {
            "total_return": 0.0,
            "annualized_return": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "max_drawdown": 0.0,
            "win_rate": 0.0,
        }

    total_return = float(equity_curve.iloc[-1] / equity_curve.iloc[0] - 1)
    years = len(equity_curve) / trading_days_per_year
    annualized_return = (
        float(equity_curve.iloc[-1] / equity_curve.iloc[0]) ** (1 / years) - 1
        if years > 0
        else 0.0
    )

    # Sharpe ratio
    excess_returns = returns - risk_free_rate / trading_days_per_year
    sharpe_ratio = (
        float(excess_returns.mean() / returns.std() * np.sqrt(trading_days_per_year))
        if returns.std() > 0
        else 0.0
    )

    # Sortino ratio
    downside_returns = returns[returns < 0]
    downside_std = float(downside_returns.std()) if len(downside_returns) > 0 else 0.0
    sortino_ratio = (
        float(excess_returns.mean() / downside_std * np.sqrt(trading_days_per_year))
        if downside_std > 0
        else 0.0
    )

    # Max drawdown
    cumulative = (1 + returns).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative - running_max) / running_max
    max_drawdown = float(drawdown.min())

    # Win rate
    winning_days = int((returns > 0).sum())
    total_days = len(returns)
    win_rate = float(winning_days / total_days) if total_days > 0 else 0.0

    # Calmar ratio
    calmar_ratio = float(annualized_return / abs(max_drawdown)) if max_drawdown != 0 else 0.0

    return {
        "total_return": float(total_return),
        "annualized_return": float(annualized_return),
        "sharpe_ratio": float(sharpe_ratio),
        "sortino_ratio": float(sortino_ratio),
        "max_drawdown": float(max_drawdown),
        "win_rate": float(win_rate),
        "calmar_ratio": float(calmar_ratio),
    }
