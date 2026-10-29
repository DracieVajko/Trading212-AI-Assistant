# Rotation Plan (Advisory — No Orders Executed)

- **Plan**: `cash-apy`
- **Run ID**: `example-run-001`
- **Advisory note**: Cash-apy reduces eligible positions fully, holds released EUR as simulated cash (APY rate 3.0%). Repurchase original ticker advised when simulated accumulation reaches original value. Advisory only — no orders executed.
- **Config**: `trim_pct=30`, `target_ticker=AAPL`, `apy_rate=3.0%`
- **Source**: Portfolio snapshot from current run (`run_engine()`); tickers resolved via existing alias table.
- **Reconciliation**: `PASS` (delta=-0.44)
- **Provider chain**: Mistral (attribution: `Gemini` / `rate_limited`)
- **Rotation toggle**: `include_quantities=true`

> **Disclaimer**: This plan is advisory only. No orders are placed. The engine never executes trades; it produces recommendations. Actual portfolio adjustments must be confirmed by the user through the broker (Trading212) independently. Reconciliation status (PASS/FAIL) reflects broker-data agreement, not rotation-plan correctness.

## Rotation Recommendations

| # | Ticker | Action | Qty Change | Reason | Sim PNL (advisory) | Cycle |
|---|---|---|---|---|---|---|
| 1 | `TTWO` | `reduce` | `-2.33` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'TTWO' when simulated APY accumulation + released EUR >= original cost. | `-19.68` | 1 |
| 2 | `TTWO` | `reinvest` | `+2.33` | cash-apy: simulated re-entry into 'TTWO' after APY accumulation; released EUR ~ 2.33 earns 3.0% APY. | `+0.00` | 1 |
| 3 | `DJGTEEX` | `reduce` | `-2.21` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'DJGTEEX' when simulated APY accumulation + released EUR >= original cost. | `+5.01` | 2 |
| 4 | `DJGTEEX` | `reinvest` | `+2.21` | cash-apy: simulated re-entry into 'DJGTEEX' after APY accumulation; released EUR ~ 2.21 earns 3.0% APY. | `+0.00` | 2 |
| 5 | `C7A0` | `reduce` | `-5.94` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'C7A0' when simulated APY accumulation + released EUR >= original cost. | `-88.75` | 3 |
| 6 | `C7A0` | `reinvest` | `+5.94` | cash-apy: simulated re-entry into 'C7A0' after APY accumulation; released EUR ~ 5.94 earns 3.0% APY. | `+0.00` | 3 |
| 7 | `EGT` | `reduce` | `-1623.46` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'EGT' when simulated APY accumulation + released EUR >= original cost. | `-66.34` | 4 |
| 8 | `EGT` | `reinvest` | `+1623.46` | cash-apy: simulated re-entry into 'EGT' after APY accumulation; released EUR ~ 1623.46 earns 3.0% APY. | `+0.00` | 4 |
| 9 | `CBRS` | `reduce` | `-1.40` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'CBRS' when simulated APY accumulation + released EUR >= original cost. | `-48.45` | 5 |
| 10 | `CBRS` | `reinvest` | `+1.40` | cash-apy: simulated re-entry into 'CBRS' after APY accumulation; released EUR ~ 1.40 earns 3.0% APY. | `+0.00` | 5 |
| 11 | `ERNX` | `reduce` | `-21.41` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'ERNX' when simulated APY accumulation + released EUR >= original cost. | `+0.54` | 6 |
| 12 | `ERNX` | `reinvest` | `+21.41` | cash-apy: simulated re-entry into 'ERNX' after APY accumulation; released EUR ~ 21.41 earns 3.0% APY. | `+0.00` | 6 |
| 13 | `UEC` | `reduce` | `-16.37` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'UEC' when simulated APY accumulation + released EUR >= original cost. | `-15.27` | 7 |
| 14 | `UEC` | `reinvest` | `+16.37` | cash-apy: simulated re-entry into 'UEC' after APY accumulation; released EUR ~ 16.37 earns 3.0% APY. | `+0.00` | 7 |
| 15 | `TUYA` | `reduce` | `-70.03` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'TUYA' when simulated APY accumulation + released EUR >= original cost. | `-10.10` | 8 |
| 16 | `TUYA` | `reinvest` | `+70.03` | cash-apy: simulated re-entry into 'TUYA' after APY accumulation; released EUR ~ 70.03 earns 3.0% APY. | `+0.00` | 8 |
| 17 | `1YD` | `reduce` | `-0.16` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker '1YD' when simulated APY accumulation + released EUR >= original cost. | `-1.20` | 9 |
| 18 | `1YD` | `reinvest` | `+0.16` | cash-apy: simulated re-entry into '1YD' after APY accumulation; released EUR ~ 0.16 earns 3.0% APY. | `+0.00` | 9 |
| 19 | `NVD` | `reduce` | `-0.26` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'NVD' when simulated APY accumulation + released EUR >= original cost. | `-1.72` | 10 |
| 20 | `NVD` | `reinvest` | `+0.26` | cash-apy: simulated re-entry into 'NVD' after APY accumulation; released EUR ~ 0.26 earns 3.0% APY. | `+0.00` | 10 |
| 21 | `NEE` | `reduce` | `-0.58` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'NEE' when simulated APY accumulation + released EUR >= original cost. | `+0.42` | 11 |
| 22 | `NEE` | `reinvest` | `+0.58` | cash-apy: simulated re-entry into 'NEE' after APY accumulation; released EUR ~ 0.58 earns 3.0% APY. | `+0.00` | 11 |
| 23 | `IQQH` | `reduce` | `-5.25` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'IQQH' when simulated APY accumulation + released EUR >= original cost. | `-3.44` | 12 |
| 24 | `IQQH` | `reinvest` | `+5.25` | cash-apy: simulated re-entry into 'IQQH' after APY accumulation; released EUR ~ 5.25 earns 3.0% APY. | `+0.00` | 12 |
| 25 | `LITM` | `reduce` | `-7.34` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'LITM' when simulated APY accumulation + released EUR >= original cost. | `-7.60` | 13 |
| 26 | `LITM` | `reinvest` | `+7.34` | cash-apy: simulated re-entry into 'LITM' after APY accumulation; released EUR ~ 7.34 earns 3.0% APY. | `+0.00` | 13 |
| 27 | `AMD` | `reduce` | `-0.08` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'AMD' when simulated APY accumulation + released EUR >= original cost. | `+0.87` | 14 |
| 28 | `AMD` | `reinvest` | `+0.08` | cash-apy: simulated re-entry into 'AMD' after APY accumulation; released EUR ~ 0.08 earns 3.0% APY. | `+0.00` | 14 |
| 29 | `LAR0` | `reduce` | `-0.17` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'LAR0' when simulated APY accumulation + released EUR >= original cost. | `-4.93` | 15 |
| 30 | `LAR0` | `reinvest` | `+0.17` | cash-apy: simulated re-entry into 'LAR0' after APY accumulation; released EUR ~ 0.17 earns 3.0% APY. | `+0.00` | 15 |
| 31 | `INL` | `reduce` | `-0.46` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'INL' when simulated APY accumulation + released EUR >= original cost. | `-2.66` | 16 |
| 32 | `INL` | `reinvest` | `+0.46` | cash-apy: simulated re-entry into 'INL' after APY accumulation; released EUR ~ 0.46 earns 3.0% APY. | `+0.00` | 16 |
| 33 | `VWSB` | `reduce` | `-1.32` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'VWSB' when simulated APY accumulation + released EUR >= original cost. | `-2.23` | 17 |
| 34 | `VWSB` | `reinvest` | `+1.32` | cash-apy: simulated re-entry into 'VWSB' after APY accumulation; released EUR ~ 1.32 earns 3.0% APY. | `+0.00` | 17 |
| 35 | `AAPL` | `reduce` | `-0.09` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'AAPL' when simulated APY accumulation + released EUR >= original cost. | `+2.67` | 18 |
| 36 | `AAPL` | `reinvest` | `+0.09` | cash-apy: simulated re-entry into 'AAPL' after APY accumulation; released EUR ~ 0.09 earns 3.0% APY. | `+0.00` | 18 |
| 37 | `APC` | `reduce` | `-0.08` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'APC' when simulated APY accumulation + released EUR >= original cost. | `+0.95` | 19 |
| 38 | `APC` | `reinvest` | `+0.08` | cash-apy: simulated re-entry into 'APC' after APY accumulation; released EUR ~ 0.08 earns 3.0% APY. | `+0.00` | 19 |
| 39 | `IBE` | `reduce` | `-1.15` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'IBE' when simulated APY accumulation + released EUR >= original cost. | `+2.17` | 20 |
| 40 | `IBE` | `reinvest` | `+1.15` | cash-apy: simulated re-entry into 'IBE' after APY accumulation; released EUR ~ 1.15 earns 3.0% APY. | `+0.00` | 20 |
| 41 | `DR4M` | `reduce` | `-5.29` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'DR4M' when simulated APY accumulation + released EUR >= original cost. | `-0.87` | 21 |
| 42 | `DR4M` | `reinvest` | `+5.29` | cash-apy: simulated re-entry into 'DR4M' after APY accumulation; released EUR ~ 5.29 earns 3.0% APY. | `+0.00` | 21 |
| 43 | `LIN` | `reduce` | `-0.05` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'LIN' when simulated APY accumulation + released EUR >= original cost. | `+2.29` | 22 |
| 44 | `LIN` | `reinvest` | `+0.05` | cash-apy: simulated re-entry into 'LIN' after APY accumulation; released EUR ~ 0.05 earns 3.0% APY. | `+0.00` | 22 |
| 45 | `AI` | `reduce` | `-0.12` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'AI' when simulated APY accumulation + released EUR >= original cost. | `+1.26` | 23 |
| 46 | `AI` | `reinvest` | `+0.12` | cash-apy: simulated re-entry into 'AI' after APY accumulation; released EUR ~ 0.12 earns 3.0% APY. | `+0.00` | 23 |
| 47 | `RWE` | `reduce` | `-0.36` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'RWE' when simulated APY accumulation + released EUR >= original cost. | `+0.30` | 24 |
| 48 | `RWE` | `reinvest` | `+0.36` | cash-apy: simulated re-entry into 'RWE' after APY accumulation; released EUR ~ 0.36 earns 3.0% APY. | `+0.00` | 24 |
| 49 | `APD` | `reduce` | `-0.08` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'APD' when simulated APY accumulation + released EUR >= original cost. | `+1.06` | 25 |
| 50 | `APD` | `reinvest` | `+0.08` | cash-apy: simulated re-entry into 'APD' after APY accumulation; released EUR ~ 0.08 earns 3.0% APY. | `+0.00` | 25 |
| 51 | `ENR` | `reduce` | `-0.16` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'ENR' when simulated APY accumulation + released EUR >= original cost. | `-0.95` | 26 |
| 52 | `ENR` | `reinvest` | `+0.16` | cash-apy: simulated re-entry into 'ENR' after APY accumulation; released EUR ~ 0.16 earns 3.0% APY. | `+0.00` | 26 |
| 53 | `SU` | `reduce` | `-0.09` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'SU' when simulated APY accumulation + released EUR >= original cost. | `-3.57` | 27 |
| 54 | `SU` | `reinvest` | `+0.09` | cash-apy: simulated re-entry into 'SU' after APY accumulation; released EUR ~ 0.09 earns 3.0% APY. | `+0.00` | 27 |
| 55 | `HTHIY` | `reduce` | `-0.64` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'HTHIY' when simulated APY accumulation + released EUR >= original cost. | `+1.86` | 28 |
| 56 | `HTHIY` | `reinvest` | `+0.64` | cash-apy: simulated re-entry into 'HTHIY' after APY accumulation; released EUR ~ 0.64 earns 3.0% APY. | `+0.00` | 28 |
| 57 | `ETN` | `reduce` | `-0.06` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'ETN' when simulated APY accumulation + released EUR >= original cost. | `-1.10` | 29 |
| 58 | `ETN` | `reinvest` | `+0.06` | cash-apy: simulated re-entry into 'ETN' after APY accumulation; released EUR ~ 0.06 earns 3.0% APY. | `+0.00` | 29 |
| 59 | `GEV` | `reduce` | `-0.03` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'GEV' when simulated APY accumulation + released EUR >= original cost. | `-1.85` | 30 |
| 60 | `GEV` | `reinvest` | `+0.03` | cash-apy: simulated re-entry into 'GEV' after APY accumulation; released EUR ~ 0.03 earns 3.0% APY. | `+0.00` | 30 |
| 61 | `FWRG` | `reduce` | `-2.43` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'FWRG' when simulated APY accumulation + released EUR >= original cost. | `+0.57` | 31 |
| 62 | `FWRG` | `reinvest` | `+2.43` | cash-apy: simulated re-entry into 'FWRG' after APY accumulation; released EUR ~ 2.43 earns 3.0% APY. | `+0.00` | 31 |
| 63 | `SGLN` | `reduce` | `-0.22` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'SGLN' when simulated APY accumulation + released EUR >= original cost. | `-0.49` | 32 |
| 64 | `SGLN` | `reinvest` | `+0.22` | cash-apy: simulated re-entry into 'SGLN' after APY accumulation; released EUR ~ 0.22 earns 3.0% APY. | `+0.00` | 32 |
| 65 | `SSLN` | `reduce` | `-0.34` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'SSLN' when simulated APY accumulation + released EUR >= original cost. | `-2.01` | 33 |
| 66 | `SSLN` | `reinvest` | `+0.34` | cash-apy: simulated re-entry into 'SSLN' after APY accumulation; released EUR ~ 0.34 earns 3.0% APY. | `+0.00` | 33 |
| 67 | `JEDG` | `reduce` | `-0.20` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'JEDG' when simulated APY accumulation + released EUR >= original cost. | `+0.00` | 34 |
| 68 | `JEDG` | `reinvest` | `+0.20` | cash-apy: simulated re-entry into 'JEDG' after APY accumulation; released EUR ~ 0.20 earns 3.0% APY. | `+0.00` | 34 |
| 69 | `GDGB` | `reduce` | `-0.15` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'GDGB' when simulated APY accumulation + released EUR >= original cost. | `-1.16` | 35 |
| 70 | `GDGB` | `reinvest` | `+0.15` | cash-apy: simulated re-entry into 'GDGB' after APY accumulation; released EUR ~ 0.15 earns 3.0% APY. | `+0.00` | 35 |
| 71 | `FB2A` | `reduce` | `-0.02` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'FB2A' when simulated APY accumulation + released EUR >= original cost. | `-1.70` | 36 |
| 72 | `FB2A` | `reinvest` | `+0.02` | cash-apy: simulated re-entry into 'FB2A' after APY accumulation; released EUR ~ 0.02 earns 3.0% APY. | `+0.00` | 36 |
| 73 | `IUVF` | `reduce` | `-0.76` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'IUVF' when simulated APY accumulation + released EUR >= original cost. | `+0.28` | 37 |
| 74 | `IUVF` | `reinvest` | `+0.76` | cash-apy: simulated re-entry into 'IUVF' after APY accumulation; released EUR ~ 0.76 earns 3.0% APY. | `+0.00` | 37 |
| 75 | `SILG` | `reduce` | `-0.40` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'SILG' when simulated APY accumulation + released EUR >= original cost. | `-1.97` | 38 |
| 76 | `SILG` | `reinvest` | `+0.40` | cash-apy: simulated re-entry into 'SILG' after APY accumulation; released EUR ~ 0.40 earns 3.0% APY. | `+0.00` | 38 |
| 77 | `ESIF` | `reduce` | `-0.80` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'ESIF' when simulated APY accumulation + released EUR >= original cost. | `-0.65` | 39 |
| 78 | `ESIF` | `reinvest` | `+0.80` | cash-apy: simulated re-entry into 'ESIF' after APY accumulation; released EUR ~ 0.80 earns 3.0% APY. | `+0.00` | 39 |
| 79 | `COPG` | `reduce` | `-0.24` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'COPG' when simulated APY accumulation + released EUR >= original cost. | `-0.96` | 40 |
| 80 | `COPG` | `reinvest` | `+0.24` | cash-apy: simulated re-entry into 'COPG' after APY accumulation; released EUR ~ 0.24 earns 3.0% APY. | `+0.00` | 40 |
| 81 | `AINF` | `reduce` | `-1.29` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'AINF' when simulated APY accumulation + released EUR >= original cost. | `+0.31` | 41 |
| 82 | `AINF` | `reinvest` | `+1.29` | cash-apy: simulated re-entry into 'AINF' after APY accumulation; released EUR ~ 1.29 earns 3.0% APY. | `+0.00` | 41 |
| 83 | `NATP` | `reduce` | `-0.68` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'NATP' when simulated APY accumulation + released EUR >= original cost. | `+0.34` | 42 |
| 84 | `NATP` | `reinvest` | `+0.68` | cash-apy: simulated re-entry into 'NATP' after APY accumulation; released EUR ~ 0.68 earns 3.0% APY. | `+0.00` | 42 |
| 85 | `NCLR` | `reduce` | `-0.34` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'NCLR' when simulated APY accumulation + released EUR >= original cost. | `-1.05` | 43 |
| 86 | `NCLR` | `reinvest` | `+0.34` | cash-apy: simulated re-entry into 'NCLR' after APY accumulation; released EUR ~ 0.34 earns 3.0% APY. | `+0.00` | 43 |
| 87 | `QWTM` | `reduce` | `-0.43` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'QWTM' when simulated APY accumulation + released EUR >= original cost. | `-0.65` | 44 |
| 88 | `QWTM` | `reinvest` | `+0.43` | cash-apy: simulated re-entry into 'QWTM' after APY accumulation; released EUR ~ 0.43 earns 3.0% APY. | `+0.00` | 44 |
| 89 | `WBIO` | `reduce` | `-0.49` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'WBIO' when simulated APY accumulation + released EUR >= original cost. | `+1.40` | 45 |
| 90 | `WBIO` | `reinvest` | `+0.49` | cash-apy: simulated re-entry into 'WBIO' after APY accumulation; released EUR ~ 0.49 earns 3.0% APY. | `+0.00` | 45 |
| 91 | `DRDR` | `reduce` | `-1.16` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'DRDR' when simulated APY accumulation + released EUR >= original cost. | `+1.33` | 46 |
| 92 | `DRDR` | `reinvest` | `+1.16` | cash-apy: simulated re-entry into 'DRDR' after APY accumulation; released EUR ~ 1.16 earns 3.0% APY. | `+0.00` | 46 |
| 93 | `IISU` | `reduce` | `-0.80` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'IISU' when simulated APY accumulation + released EUR >= original cost. | `+0.29` | 47 |
| 94 | `IISU` | `reinvest` | `+0.80` | cash-apy: simulated re-entry into 'IISU' after APY accumulation; released EUR ~ 0.80 earns 3.0% APY. | `+0.00` | 47 |
| 95 | `COFF` | `reduce` | `-0.13` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'COFF' when simulated APY accumulation + released EUR >= original cost. | `+0.34` | 48 |
| 96 | `COFF` | `reinvest` | `+0.13` | cash-apy: simulated re-entry into 'COFF' after APY accumulation; released EUR ~ 0.13 earns 3.0% APY. | `+0.00` | 48 |
| 97 | `COCO` | `reduce` | `-0.98` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'COCO' when simulated APY accumulation + released EUR >= original cost. | `-0.25` | 49 |
| 98 | `COCO` | `reinvest` | `+0.98` | cash-apy: simulated re-entry into 'COCO' after APY accumulation; released EUR ~ 0.98 earns 3.0% APY. | `+0.00` | 49 |
| 99 | `MSFT` | `reduce` | `-0.02` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'MSFT' when simulated APY accumulation + released EUR >= original cost. | `+1.11` | 50 |
| 100 | `MSFT` | `reinvest` | `+0.02` | cash-apy: simulated re-entry into 'MSFT' after APY accumulation; released EUR ~ 0.02 earns 3.0% APY. | `+0.00` | 50 |
| 101 | `AFL` | `reduce` | `-0.07` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'AFL' when simulated APY accumulation + released EUR >= original cost. | `+0.65` | 51 |
| 102 | `AFL` | `reinvest` | `+0.07` | cash-apy: simulated re-entry into 'AFL' after APY accumulation; released EUR ~ 0.07 earns 3.0% APY. | `+0.00` | 51 |
| 103 | `ECL` | `reduce` | `-0.03` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'ECL' when simulated APY accumulation + released EUR >= original cost. | `+0.76` | 52 |
| 104 | `ECL` | `reinvest` | `+0.03` | cash-apy: simulated re-entry into 'ECL' after APY accumulation; released EUR ~ 0.03 earns 3.0% APY. | `+0.00` | 52 |
| 105 | `CF` | `reduce` | `-0.07` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'CF' when simulated APY accumulation + released EUR >= original cost. | `+0.17` | 53 |
| 106 | `CF` | `reinvest` | `+0.07` | cash-apy: simulated re-entry into 'CF' after APY accumulation; released EUR ~ 0.07 earns 3.0% APY. | `+0.00` | 53 |
| 107 | `GWW` | `reduce` | `-0.01` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'GWW' when simulated APY accumulation + released EUR >= original cost. | `+0.60` | 54 |
| 108 | `GWW` | `reinvest` | `+0.01` | cash-apy: simulated re-entry into 'GWW' after APY accumulation; released EUR ~ 0.01 earns 3.0% APY. | `+0.00` | 54 |
| 109 | `C` | `reduce` | `-0.07` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'C' when simulated APY accumulation + released EUR >= original cost. | `-0.19` | 55 |
| 110 | `C` | `reinvest` | `+0.07` | cash-apy: simulated re-entry into 'C' after APY accumulation; released EUR ~ 0.07 earns 3.0% APY. | `+0.00` | 55 |
| 111 | `ADP` | `reduce` | `-0.03` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'ADP' when simulated APY accumulation + released EUR >= original cost. | `+0.70` | 56 |
| 112 | `ADP` | `reinvest` | `+0.03` | cash-apy: simulated re-entry into 'ADP' after APY accumulation; released EUR ~ 0.03 earns 3.0% APY. | `+0.00` | 56 |
| 113 | `WMT` | `reduce` | `-0.07` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'WMT' when simulated APY accumulation + released EUR >= original cost. | `+1.15` | 57 |
| 114 | `WMT` | `reinvest` | `+0.07` | cash-apy: simulated re-entry into 'WMT' after APY accumulation; released EUR ~ 0.07 earns 3.0% APY. | `+0.00` | 57 |
| 115 | `ITW` | `reduce` | `-0.03` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'ITW' when simulated APY accumulation + released EUR >= original cost. | `+0.22` | 58 |
| 116 | `ITW` | `reinvest` | `+0.03` | cash-apy: simulated re-entry into 'ITW' after APY accumulation; released EUR ~ 0.03 earns 3.0% APY. | `+0.00` | 58 |
| 117 | `BLK` | `reduce` | `-0.01` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'BLK' when simulated APY accumulation + released EUR >= original cost. | `+0.40` | 59 |
| 118 | `BLK` | `reinvest` | `+0.01` | cash-apy: simulated re-entry into 'BLK' after APY accumulation; released EUR ~ 0.01 earns 3.0% APY. | `+0.00` | 59 |
| 119 | `ROP` | `reduce` | `-0.02` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'ROP' when simulated APY accumulation + released EUR >= original cost. | `+0.98` | 60 |
| 120 | `ROP` | `reinvest` | `+0.02` | cash-apy: simulated re-entry into 'ROP' after APY accumulation; released EUR ~ 0.02 earns 3.0% APY. | `+0.00` | 60 |
| 121 | `PPG` | `reduce` | `-0.07` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'PPG' when simulated APY accumulation + released EUR >= original cost. | `+0.84` | 61 |
| 122 | `PPG` | `reinvest` | `+0.07` | cash-apy: simulated re-entry into 'PPG' after APY accumulation; released EUR ~ 0.07 earns 3.0% APY. | `+0.00` | 61 |
| 123 | `PEP` | `reduce` | `-0.06` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'PEP' when simulated APY accumulation + released EUR >= original cost. | `+0.07` | 62 |
| 124 | `PEP` | `reinvest` | `+0.06` | cash-apy: simulated re-entry into 'PEP' after APY accumulation; released EUR ~ 0.06 earns 3.0% APY. | `+0.00` | 62 |
| 125 | `CB` | `reduce` | `-0.02` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'CB' when simulated APY accumulation + released EUR >= original cost. | `+0.74` | 63 |
| 126 | `CB` | `reinvest` | `+0.02` | cash-apy: simulated re-entry into 'CB' after APY accumulation; released EUR ~ 0.02 earns 3.0% APY. | `+0.00` | 63 |
| 127 | `ABT` | `reduce` | `-0.08` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'ABT' when simulated APY accumulation + released EUR >= original cost. | `-0.12` | 64 |
| 128 | `ABT` | `reinvest` | `+0.08` | cash-apy: simulated re-entry into 'ABT' after APY accumulation; released EUR ~ 0.08 earns 3.0% APY. | `+0.00` | 64 |
| 129 | `TROW` | `reduce` | `-0.08` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'TROW' when simulated APY accumulation + released EUR >= original cost. | `-0.11` | 65 |
| 130 | `TROW` | `reinvest` | `+0.08` | cash-apy: simulated re-entry into 'TROW' after APY accumulation; released EUR ~ 0.08 earns 3.0% APY. | `+0.00` | 65 |
| 131 | `JPM` | `reduce` | `-0.02` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'JPM' when simulated APY accumulation + released EUR >= original cost. | `+0.00` | 66 |
| 132 | `JPM` | `reinvest` | `+0.02` | cash-apy: simulated re-entry into 'JPM' after APY accumulation; released EUR ~ 0.02 earns 3.0% APY. | `+0.00` | 66 |
| 133 | `GD` | `reduce` | `-0.02` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'GD' when simulated APY accumulation + released EUR >= original cost. | `-0.20` | 67 |
| 134 | `GD` | `reinvest` | `+0.02` | cash-apy: simulated re-entry into 'GD' after APY accumulation; released EUR ~ 0.02 earns 3.0% APY. | `+0.00` | 67 |
| 135 | `DUK` | `reduce` | `-0.07` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'DUK' when simulated APY accumulation + released EUR >= original cost. | `+0.59` | 68 |
| 136 | `DUK` | `reinvest` | `+0.07` | cash-apy: simulated re-entry into 'DUK' after APY accumulation; released EUR ~ 0.07 earns 3.0% APY. | `+0.00` | 68 |
| 137 | `RY` | `reduce` | `-0.04` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'RY' when simulated APY accumulation + released EUR >= original cost. | `+0.18` | 69 |
| 138 | `RY` | `reinvest` | `+0.04` | cash-apy: simulated re-entry into 'RY' after APY accumulation; released EUR ~ 0.04 earns 3.0% APY. | `+0.00` | 69 |
| 139 | `BMY` | `reduce` | `-0.13` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'BMY' when simulated APY accumulation + released EUR >= original cost. | `-0.16` | 70 |
| 140 | `BMY` | `reinvest` | `+0.13` | cash-apy: simulated re-entry into 'BMY' after APY accumulation; released EUR ~ 0.13 earns 3.0% APY. | `+0.00` | 70 |
| 141 | `BMO` | `reduce` | `-0.05` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'BMO' when simulated APY accumulation + released EUR >= original cost. | `+0.18` | 71 |
| 142 | `BMO` | `reinvest` | `+0.05` | cash-apy: simulated re-entry into 'BMO' after APY accumulation; released EUR ~ 0.05 earns 3.0% APY. | `+0.00` | 71 |
| 143 | `KO` | `reduce` | `-0.09` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'KO' when simulated APY accumulation + released EUR >= original cost. | `+0.62` | 72 |
| 144 | `KO` | `reinvest` | `+0.09` | cash-apy: simulated re-entry into 'KO' after APY accumulation; released EUR ~ 0.09 earns 3.0% APY. | `+0.00` | 72 |
| 145 | `MA` | `reduce` | `-0.01` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'MA' when simulated APY accumulation + released EUR >= original cost. | `+0.77` | 73 |
| 146 | `MA` | `reinvest` | `+0.01` | cash-apy: simulated re-entry into 'MA' after APY accumulation; released EUR ~ 0.01 earns 3.0% APY. | `+0.00` | 73 |
| 147 | `AGNC` | `reduce` | `-0.92` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'AGNC' when simulated APY accumulation + released EUR >= original cost. | `-1.15` | 74 |
| 148 | `AGNC` | `reinvest` | `+0.92` | cash-apy: simulated re-entry into 'AGNC' after APY accumulation; released EUR ~ 0.92 earns 3.0% APY. | `+0.00` | 74 |
| 149 | `CSCO` | `reduce` | `-0.07` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'CSCO' when simulated APY accumulation + released EUR >= original cost. | `+0.27` | 75 |
| 150 | `CSCO` | `reinvest` | `+0.07` | cash-apy: simulated re-entry into 'CSCO' after APY accumulation; released EUR ~ 0.07 earns 3.0% APY. | `+0.00` | 75 |
| 151 | `SLB` | `reduce` | `-0.15` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'SLB' when simulated APY accumulation + released EUR >= original cost. | `+0.40` | 76 |
| 152 | `SLB` | `reinvest` | `+0.15` | cash-apy: simulated re-entry into 'SLB' after APY accumulation; released EUR ~ 0.15 earns 3.0% APY. | `+0.00` | 76 |
| 153 | `MCD` | `reduce` | `-0.03` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'MCD' when simulated APY accumulation + released EUR >= original cost. | `-0.04` | 77 |
| 154 | `MCD` | `reinvest` | `+0.03` | cash-apy: simulated re-entry into 'MCD' after APY accumulation; released EUR ~ 0.03 earns 3.0% APY. | `+0.00` | 77 |
| 155 | `PG` | `reduce` | `-0.05` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'PG' when simulated APY accumulation + released EUR >= original cost. | `+1.03` | 78 |
| 156 | `PG` | `reinvest` | `+0.05` | cash-apy: simulated re-entry into 'PG' after APY accumulation; released EUR ~ 0.05 earns 3.0% APY. | `+0.00` | 78 |
| 157 | `JNJ` | `reduce` | `-0.03` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'JNJ' when simulated APY accumulation + released EUR >= original cost. | `+0.53` | 79 |
| 158 | `JNJ` | `reinvest` | `+0.03` | cash-apy: simulated re-entry into 'JNJ' after APY accumulation; released EUR ~ 0.03 earns 3.0% APY. | `+0.00` | 79 |
| 159 | `O` | `reduce` | `-0.15` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'O' when simulated APY accumulation + released EUR >= original cost. | `-0.30` | 80 |
| 160 | `O` | `reinvest` | `+0.15` | cash-apy: simulated re-entry into 'O' after APY accumulation; released EUR ~ 0.15 earns 3.0% APY. | `+0.00` | 80 |
| 161 | `MAIN` | `reduce` | `-0.15` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'MAIN' when simulated APY accumulation + released EUR >= original cost. | `-0.15` | 81 |
| 162 | `MAIN` | `reinvest` | `+0.15` | cash-apy: simulated re-entry into 'MAIN' after APY accumulation; released EUR ~ 0.15 earns 3.0% APY. | `+0.00` | 81 |
| 163 | `CNQ` | `reduce` | `-0.15` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'CNQ' when simulated APY accumulation + released EUR >= original cost. | `+1.07` | 82 |
| 164 | `CNQ` | `reinvest` | `+0.15` | cash-apy: simulated re-entry into 'CNQ' after APY accumulation; released EUR ~ 0.15 earns 3.0% APY. | `+0.00` | 82 |
| 165 | `NUE` | `reduce` | `-0.03` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'NUE' when simulated APY accumulation + released EUR >= original cost. | `+0.64` | 83 |
| 166 | `NUE` | `reinvest` | `+0.03` | cash-apy: simulated re-entry into 'NUE' after APY accumulation; released EUR ~ 0.03 earns 3.0% APY. | `+0.00` | 83 |
| 167 | `KMB` | `reduce` | `-0.08` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'KMB' when simulated APY accumulation + released EUR >= original cost. | `+0.37` | 84 |
| 168 | `KMB` | `reinvest` | `+0.08` | cash-apy: simulated re-entry into 'KMB' after APY accumulation; released EUR ~ 0.08 earns 3.0% APY. | `+0.00` | 84 |
| 169 | `LOW` | `reduce` | `-0.04` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'LOW' when simulated APY accumulation + released EUR >= original cost. | `-0.11` | 85 |
| 170 | `LOW` | `reinvest` | `+0.04` | cash-apy: simulated re-entry into 'LOW' after APY accumulation; released EUR ~ 0.04 earns 3.0% APY. | `+0.00` | 85 |
| 171 | `LTC` | `reduce` | `-0.19` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'LTC' when simulated APY accumulation + released EUR >= original cost. | `+0.53` | 86 |
| 172 | `LTC` | `reinvest` | `+0.19` | cash-apy: simulated re-entry into 'LTC' after APY accumulation; released EUR ~ 0.19 earns 3.0% APY. | `+0.00` | 86 |
| 173 | `BNS` | `reduce` | `-0.09` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'BNS' when simulated APY accumulation + released EUR >= original cost. | `+0.53` | 87 |
| 174 | `BNS` | `reinvest` | `+0.09` | cash-apy: simulated re-entry into 'BNS' after APY accumulation; released EUR ~ 0.09 earns 3.0% APY. | `+0.00` | 87 |
| 175 | `CVX` | `reduce` | `-0.04` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'CVX' when simulated APY accumulation + released EUR >= original cost. | `+1.16` | 88 |
| 176 | `CVX` | `reinvest` | `+0.04` | cash-apy: simulated re-entry into 'CVX' after APY accumulation; released EUR ~ 0.04 earns 3.0% APY. | `+0.00` | 88 |
| 177 | `TD` | `reduce` | `-0.07` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'TD' when simulated APY accumulation + released EUR >= original cost. | `+0.58` | 89 |
| 178 | `TD` | `reinvest` | `+0.07` | cash-apy: simulated re-entry into 'TD' after APY accumulation; released EUR ~ 0.07 earns 3.0% APY. | `+0.00` | 89 |
| 179 | `SHW` | `reduce` | `-0.03` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'SHW' when simulated APY accumulation + released EUR >= original cost. | `-0.27` | 90 |
| 180 | `SHW` | `reinvest` | `+0.03` | cash-apy: simulated re-entry into 'SHW' after APY accumulation; released EUR ~ 0.03 earns 3.0% APY. | `+0.00` | 90 |
| 181 | `IBM` | `reduce` | `-0.03` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'IBM' when simulated APY accumulation + released EUR >= original cost. | `+0.78` | 91 |
| 182 | `IBM` | `reinvest` | `+0.03` | cash-apy: simulated re-entry into 'IBM' after APY accumulation; released EUR ~ 0.03 earns 3.0% APY. | `+0.00` | 91 |
| 183 | `ADC` | `reduce` | `-0.12` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'ADC' when simulated APY accumulation + released EUR >= original cost. | `-0.48` | 92 |
| 184 | `ADC` | `reinvest` | `+0.12` | cash-apy: simulated re-entry into 'ADC' after APY accumulation; released EUR ~ 0.12 earns 3.0% APY. | `+0.00` | 92 |
| 185 | `EMR` | `reduce` | `-0.05` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'EMR' when simulated APY accumulation + released EUR >= original cost. | `+0.65` | 93 |
| 186 | `EMR` | `reinvest` | `+0.05` | cash-apy: simulated re-entry into 'EMR' after APY accumulation; released EUR ~ 0.05 earns 3.0% APY. | `+0.00` | 93 |
| 187 | `RGLD` | `reduce` | `-0.03` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'RGLD' when simulated APY accumulation + released EUR >= original cost. | `-0.08` | 94 |
| 188 | `RGLD` | `reinvest` | `+0.03` | cash-apy: simulated re-entry into 'RGLD' after APY accumulation; released EUR ~ 0.03 earns 3.0% APY. | `+0.00` | 94 |
| 189 | `CAH` | `reduce` | `-0.03` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'CAH' when simulated APY accumulation + released EUR >= original cost. | `+0.64` | 95 |
| 190 | `CAH` | `reinvest` | `+0.03` | cash-apy: simulated re-entry into 'CAH' after APY accumulation; released EUR ~ 0.03 earns 3.0% APY. | `+0.00` | 95 |
| 191 | `SYY` | `reduce` | `-0.10` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'SYY' when simulated APY accumulation + released EUR >= original cost. | `+0.23` | 96 |
| 192 | `SYY` | `reinvest` | `+0.10` | cash-apy: simulated re-entry into 'SYY' after APY accumulation; released EUR ~ 0.10 earns 3.0% APY. | `+0.00` | 96 |
| 193 | `GOOD` | `reduce` | `-0.71` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'GOOD' when simulated APY accumulation + released EUR >= original cost. | `-0.60` | 97 |
| 194 | `GOOD` | `reinvest` | `+0.71` | cash-apy: simulated re-entry into 'GOOD' after APY accumulation; released EUR ~ 0.71 earns 3.0% APY. | `+0.00` | 97 |
| 195 | `PNR` | `reduce` | `-0.13` | cash-apy: full reduction to cash; released EUR earns simulated 3.0% APY. Repurchase original ticker 'PNR' when simulated APY accumulation + released EUR >= original cost. | `+0.42` | 98 |
| 196 | `PNR` | `reinvest` | `+0.13` | cash-apy: simulated re-entry into 'PNR' after APY accumulation; released EUR ~ 0.13 earns 3.0% APY. | `+0.00` | 98 |

## Exit Status

| Metric | Value |
|--------|-------|
| Exit conditions met | `False` |
| Cycles simulated (max advisory) | `98` |
| Plan mode | `cash-apy` |

## Config Snapshot
```
include_quantities=True
rotation_plan=cash-apy
rotation_trim_pct=30
rotation_target=AAPL
apy_rate=3.0
```

---
*Generated by Portfolio AI Assistant — advisory rotation module (no execution authority). See docs/specs/2026-10-29-rotation-csv-toggle.md.*