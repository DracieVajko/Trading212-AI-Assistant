# Rotation Plan (Advisory — No Orders Executed)

- **Plan**: `average-down`
- **Run ID**: `example-run-001`
- **Advisory note**: Average-down reduces losing positions by trim_pct; released capital simulated reinvested at same ticker with lower entry. Advisory only — no orders executed.
- **Config**: `trim_pct=30`, `target_ticker=TTWO`, `apy_rate=3.0%`
- **Source**: Portfolio snapshot from current run (`run_engine()`); tickers resolved via existing alias table.
- **Reconciliation**: `PASS` (delta=-0.44)
- **Provider chain**: Mistral (attribution: `Gemini` / `rate_limited`)
- **Rotation toggle**: `include_quantities=true`

> **Disclaimer**: This plan is advisory only. No orders are placed. The engine never executes trades; it produces recommendations. Actual portfolio adjustments must be confirmed by the user through the broker (Trading212) independently. Reconciliation status (PASS/FAIL) reflects broker-data agreement, not rotation-plan correctness.

## Rotation Recommendations

| # | Ticker | Action | Qty Change | Reason | Sim PNL (advisory) | Cycle |
|---|---|---|---|---|---|---|
| 1 | `TTWO` | `reduce` | `-0.70` | average-down: PPL=-19.68 EUR; trim 30% to reinvest at lower cost (simulated) | `-5.90` | 1 |
| 2 | `C7A0` | `reduce` | `-1.78` | average-down: PPL=-88.75 EUR; trim 30% to reinvest at lower cost (simulated) | `-26.62` | 2 |
| 3 | `EGT` | `reduce` | `-487.04` | average-down: PPL=-66.34 EUR; trim 30% to reinvest at lower cost (simulated) | `-19.90` | 3 |
| 4 | `CBRS` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 5 | `UEC` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 6 | `TUYA` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 7 | `1YD` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 8 | `NVD` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 9 | `IQQH` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 10 | `LITM` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 11 | `LAR0` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 12 | `INL` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 13 | `VWSB` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 14 | `DR4M` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 15 | `ENR` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 16 | `SU` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 17 | `ETN` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 18 | `GEV` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 19 | `SGLN` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 20 | `SSLN` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 21 | `GDGB` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 22 | `FB2A` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 23 | `SILG` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 24 | `ESIF` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 25 | `COPG` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 26 | `NCLR` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 27 | `QWTM` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 28 | `COCO` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 29 | `C` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 30 | `ABT` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 31 | `TROW` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 32 | `GD` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 33 | `BMY` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 34 | `AGNC` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 35 | `MCD` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 36 | `O` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 37 | `MAIN` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 38 | `LOW` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 39 | `SHW` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 40 | `ADC` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 41 | `RGLD` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |
| 42 | `GOOD` | `hold` | `+0.00` | average-down: max cycles (3) reached; hold remaining position | `+0.00` | 4 |

## Exit Status

| Metric | Value |
|--------|-------|
| Exit conditions met | `False` |
| Cycles simulated (max advisory) | `4` |
| Plan mode | `average-down` |

## Config Snapshot
```
include_quantities=True
rotation_plan=average-down
rotation_trim_pct=30
rotation_target=AAPL
apy_rate=3.0
```

---
*Generated by Portfolio AI Assistant — advisory rotation module (no execution authority). See docs/specs/2026-10-29-rotation-csv-toggle.md.*