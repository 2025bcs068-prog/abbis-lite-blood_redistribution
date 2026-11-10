# Data cleaning and safety policy

## Source and reproducibility

The original CSVs, dataset README, and dictionary are preserved in `data/raw/`. `python -m scripts.prepare_data` creates derived tables and a data-quality report. It does not rewrite source files. Each derived field is named so the original value remains available beside the cleaned interpretation.

## Decisions

| Issue | Handling | Reason |
|---|---|---|
| Facility names typed differently | Keep `facility_name_raw`; join to canonical name using `facility_id`; retain a mismatch flag | The dictionary says the ID is the source of truth. |
| Missing or `unknown` blood group | Preserve as unresolved; exclude from group-specific matching and forecasting | Inferring a blood group could create an unsafe match. |
| Duplicate donor signature | Flag records with the documented birth-date/sex/county/phone-last-four signature; do not merge | These are synthetic identifiers and a signature is not proof of identity. |
| Donation sooner than the stated minimum | Flag as a review issue; do not alter units or donor history | A timing anomaly should not silently rewrite source records. |
| Missing transfer receipt | Treat latest movement as location-uncertain; do not recommend the affected in-stock unit | Dispatch is not proof of receipt. |
| Sensor sentinels and missing hours | Mark sentinels invalid and preserve gaps; do not interpolate | An invented temperature could hide an excursion. |
| Reactive or unknown screening | Require explicit `non_reactive`; otherwise exclude | A negative or safe result must be explicit. |
| Unit status | Whitelist `in_stock`; exclude every other and future status | The source has no explicit quarantine field. A whitelist fails closed. |
| Cold-chain exposure | Exclude a unit marked exposed; also exclude any linked transfer whose cool-box maximum is above the documented 10 C threshold | Safety filters are hard constraints, not ranking features. |
| Expiry | Use the unit-level expiry date and sort ascending (FEFO); the end-of-day 31 Oct 2026 snapshot reconciles exactly when expiry is on or after that date | Lot-level dates are needed to avoid aggregate-only stock recommendations. |
| Location conflict | Exclude when a confirmed latest transfer destination disagrees with the unit snapshot | Conflicting location claims require reconciliation. |

No compatible-group substitution is attempted. Every suggestion requires a human decision. Accepting a suggestion writes a local decision event; it does not issue, dispatch, or release a unit.

