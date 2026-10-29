# Rotation Plan (Advisory — No Orders Executed)

- **Plan**: `short-rotation`
- **Run ID**: `example-run-001`
- **Advisory note**: Short-rotation reduces losing position by trim_pct, rotates released capital to target ticker. Re-entry into original ticker when target achieves PPL >= 0 (simulated future state). Advisory only — no orders executed; reconciliation status: PASS/FAIL per current run.
- **Config**: `trim_pct=30`, `target_ticker=AAPL`, `apy_rate=3.0%`
- **Source**: Portfolio snapshot from current run (`run_engine()`); tickers resolved via existing alias table.
- **Reconciliation**: `PASS` (delta=-0.44)
- **Provider chain**: Mistral (attribution: `Gemini` / `rate_limited`)
- **Rotation toggle**: `include_quantities=true`

> **Disclaimer**: This plan is advisory only. No orders are placed. The engine never executes trades; it produces recommendations. Actual portfolio adjustments must be confirmed by the user through the broker (Trading212) independently. Reconciliation status (PASS/FAIL) reflects broker-data agreement, not rotation-plan correctness.

## Rotation Recommendations

| # | Ticker | Action | Qty Change | Reason | Sim PNL (advisory) | Cycle |
|---|---|---|---|---|---|---|
| 1 | `TTWO` | `reduce` | `-0.70` | short-rotation: PPL=-19.68 EUR; reduce 30% and rotate released capital to target ticker 'AAPL' (simulated). Re-entry into original ticker when target achieves PPL >= 0. | `-5.90` | 1 |
| 2 | `AAPL` | `reinvest` | `+0.70` | short-rotation: temporary reinvestment into 'AAPL' (simulated) with released EUR | `+0.00` | 1 |
| 3 | `C7A0` | `reduce` | `-1.78` | short-rotation: PPL=-88.75 EUR; reduce 30% and rotate released capital to target ticker 'AAPL' (simulated). Re-entry into original ticker when target achieves PPL >= 0. | `-26.62` | 2 |
| 4 | `AAPL` | `reinvest` | `+1.78` | short-rotation: temporary reinvestment into 'AAPL' (simulated) with released EUR | `+0.00` | 2 |
| 5 | `EGT` | `reduce` | `-487.04` | short-rotation: PPL=-66.34 EUR; reduce 30% and rotate released capital to target ticker 'AAPL' (simulated). Re-entry into original ticker when target achieves PPL >= 0. | `-19.90` | 3 |
| 6 | `AAPL` | `reinvest` | `+487.04` | short-rotation: temporary reinvestment into 'AAPL' (simulated) with released EUR | `+0.00` | 3 |
| 7 | `CBRS` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 8 | `UEC` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 9 | `TUYA` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 10 | `1YD` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 11 | `NVD` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 12 | `IQQH` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 13 | `LITM` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 14 | `LAR0` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 15 | `INL` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 16 | `VWSB` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 17 | `DR4M` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 18 | `ENR` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 19 | `SU` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 20 | `ETN` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 21 | `GEV` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 22 | `SGLN` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 23 | `SSLN` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 24 | `GDGB` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 25 | `FB2A` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 26 | `SILG` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 27 | `ESIF` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 28 | `COPG` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 29 | `NCLR` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 30 | `QWTM` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 31 | `COCO` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 32 | `C` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 33 | `ABT` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 34 | `TROW` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 35 | `GD` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 36 | `BMY` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 37 | `AGNC` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 38 | `MCD` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 39 | `O` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 40 | `MAIN` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 41 | `LOW` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 42 | `SHW` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 43 | `ADC` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 44 | `RGLD` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |
| 45 | `GOOD` | `hold` | `+0.00` | short-rotation: max cycles (3) reached; hold | `+0.00` | 4 |

## Exit Status

| Metric | Value |
|--------|-------|
| Exit conditions met | `False` |
| Cycles simulated (max advisory) | `4` |
| Plan mode | `short-rotation` |

## Config Snapshot
```
include_quantities=True
rotation_plan=short-rotation
rotation_trim_pct=30
rotation_target=AAPL
apy_rate=3.0
```

---
*Generated by Portfolio AI Assistant — advisory rotation module (no execution authority). See docs/specs/2026-10-29-rotation-csv-toggle.md.*