# Changelog

## [Unreleased]

### Added
- Investment-policy profiles (`policy_profile`): `passive`, `long_term`,
  `medium_term`, `short_term`, `aggressive`, plus `custom` (default, no
  overlay). A profile sets eligible sleeves, sells on/off, position cap, cash
  floor, per-trade risk and trim fraction; it can block or resize a candidate
  but never creates a signal. Unknown names fail the policy as `INVALID`.
- The active profile and every overridden field are reported in the decision
  brief, the intelligence report and the run JSON.

## [1.0.0] - 2026-10-20

### Added
- Open-source community files and MIT license
