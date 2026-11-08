"""Excel export of holdings: standalone vs PIE-grouped."""

from __future__ import annotations

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

_HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_TITLE_FONT = Font(bold=True, size=12)


def _pos_display(pos: dict) -> str:
    sym = str(pos.get("symbol") or pos.get("ticker") or "")
    # display = symbol without broker suffix, uppercased
    return sym.split("_")[0].upper() if sym else ""


def _build_rows_for_positions(
    positions: list[dict],
    names: dict[str, str] | None,
    total_equity: float,
    pie_name: str | None = None,
) -> list[list[Any]]:
    rows = []
    for pos in positions:
        if not isinstance(pos, dict):
            continue
        disp = _pos_display(pos)
        if not disp:
            continue
        name = ""
        if names and disp in names:
            name = names[disp]
        elif pos.get("name"):
            name = str(pos.get("name"))
        qty = pos.get("quantity") or pos.get("qty") or 0
        avg = pos.get("average_price_eur") or pos.get("averagePrice") or pos.get("avg_cost") or 0
        cur = pos.get("current_price_eur") or pos.get("currentPrice") or pos.get("current_price") or 0
        val = pos.get("value_eur") or pos.get("market_value") or pos.get("value") or 0
        pnl = pos.get("unrealized_pnl") or pos.get("ppl") or pos.get("pnl_eur") or 0
        pnl_pct = pos.get("pnl_pct") or 0
        weight = (float(val) / total_equity * 100.0) if total_equity else 0.0
        row = [disp, name, qty, avg, cur, val, pnl, pnl_pct, round(weight, 2)]
        if pie_name is not None:
            row.append(pie_name)
        rows.append(row)
    return rows


def export_holdings_excel(
    t212_data: dict | None,
    pie_blocks: list[dict] | None,
    names: dict[str, str] | None = None,
    output_path: str | Path | None = None,
) -> Path:
    """Write an Excel workbook with standalone and PIE-grouped holdings."""
    if output_path is None:
        output_path = ROOT / "reports" / "current" / "holdings.xlsx"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # total equity
    total_equity = 0.0
    if isinstance(t212_data, dict):
        try:
            total_equity = float((t212_data.get("account_summary") or {}).get("total_equity", 0) or 0)
        except (TypeError, ValueError):
            total_equity = 0.0

    # authoritative positions
    positions = []
    if isinstance(t212_data, dict):
        try:
            from investment_engine.portfolio import t212_view
            positions = t212_view.authoritative_positions(t212_data)
        except Exception:
            positions = list(t212_data.get("all_positions") or t212_data.get("positions") or [])

    # PIE membership: set of display symbols that appear in any pie's holdings
    pie_holdings_map: dict[str, str] = {}  # display -> pie name
    pie_all_positions: list[tuple[str, dict]] = []  # (pie_name, pos_dict)
    for block in (pie_blocks or []):
        if not isinstance(block, dict):
            continue
        pie_name = str(block.get("name", "PIE"))
        for h in (block.get("holdings") or []):
            if not isinstance(h, dict):
                continue
            sl = str(h.get("slice", "")).strip().upper().split("_")[0]
            if sl:
                pie_holdings_map[sl] = pie_name

    # Build standalone rows: positions not in any PIE
    standalone_positions = []
    for pos in positions:
        disp = _pos_display(pos)
        if disp and disp not in pie_holdings_map:
            standalone_positions.append(pos)

    # Build PIE rows: positions that are in a PIE, with pie name
    pie_positions = []
    for pos in positions:
        disp = _pos_display(pos)
        if disp and disp in pie_holdings_map:
            pie_positions.append((pie_holdings_map[disp], pos))

    wb = Workbook()

    # --- Standalone sheet ---
    ws = wb.active
    ws.title = "Standalone"
    headers = ["Ticker", "Company", "Quantity", "Avg Price", "Current Price", "Value (EUR)", "P&L (EUR)", "P&L %", "Weight %"]
    ws.append(headers)
    for c in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center")
    for row in _build_rows_for_positions(standalone_positions, names, total_equity):
        ws.append(row)
    # format
    for r in range(2, ws.max_row + 1):
        for col, fmt in ((3, "#,##0.0000"), (4, "#,##0.00"), (5, "#,##0.00"), (6, "#,##0.00"), (7, "#,##0.00"), (8, "0.00"), (9, "0.00")):
            ws.cell(row=r, column=col).number_format = fmt
    ws.freeze_panes = "A2"
    for i, w in enumerate([10, 30, 12, 12, 12, 14, 12, 8, 8], 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # --- PIE holdings sheet ---
    ws2 = wb.create_sheet("PIE Holdings")
    headers2 = ["PIE", "Ticker", "Company", "Quantity", "Avg Price", "Current Price", "Value (EUR)", "P&L (EUR)", "P&L %", "Weight %"]
    ws2.append(headers2)
    for c in range(1, len(headers2) + 1):
        cell = ws2.cell(row=1, column=c)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center")
    # group by pie
    by_pie: dict[str, list] = {}
    for pie_name, pos in pie_positions:
        by_pie.setdefault(pie_name, []).append(pos)
    for pie_name in sorted(by_pie):
        for row in _build_rows_for_positions(by_pie[pie_name], names, total_equity, pie_name=pie_name):
            ws2.append(row)
    for r in range(2, ws2.max_row + 1):
        for col, fmt in ((4, "#,##0.0000"), (5, "#,##0.00"), (6, "#,##0.00"), (7, "#,##0.00"), (8, "#,##0.00"), (9, "0.00"), (10, "0.00")):
            ws2.cell(row=r, column=col).number_format = fmt
    ws2.freeze_panes = "A2"
    for i, w in enumerate([22, 10, 30, 12, 12, 12, 14, 12, 8, 8], 1):
        ws2.column_dimensions[get_column_letter(i)].width = w

    # --- Summary sheet ---
    ws3 = wb.create_sheet("Summary")
    ws3.append(["Metric", "Value"])
    ws3.cell(row=1, column=1).fill = _HEADER_FILL
    ws3.cell(row=1, column=2).fill = _HEADER_FILL
    ws3.cell(row=1, column=1).font = _HEADER_FONT
    ws3.cell(row=1, column=2).font = _HEADER_FONT
    ws3.append(["Total equity (EUR)", total_equity])
    ws3.append(["Standalone positions", len(standalone_positions)])
    ws3.append(["PIE positions", len(pie_positions)])
    ws3.append(["PIE groups", len(by_pie)])
    ws3.column_dimensions["A"].width = 30
    ws3.column_dimensions["B"].width = 20

    wb.save(str(output_path))
    return output_path
