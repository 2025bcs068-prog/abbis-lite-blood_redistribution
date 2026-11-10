# Starter-data quality report

Generated from the unchanged CSV files in `data/raw/` by `python -m scripts.prepare_data`.
Dataset cut-off: 2026-10-31 EAT. These are synthetic records, not operational findings.

## Table profile

| Table | Rows | Columns | Missing cells | Exact duplicate rows |
|---|---:|---:|---:|---:|
| `daily_stock.csv` | 185,785 | 5 | 0 | 0 |
| `donations.csv` | 47,363 | 11 | 101,731 | 0 |
| `donors.csv` | 43,363 | 11 | 506 | 0 |
| `drives.csv` | 1,091 | 8 | 0 | 0 |
| `facilities.csv` | 47 | 15 | 36 | 0 |
| `power_outages.csv` | 2,609 | 6 | 0 | 0 |
| `requests.csv` | 17,430 | 17 | 16,746 | 0 |
| `routes.csv` | 2,162 | 5 | 0 | 0 |
| `temperature_logs.csv` | 399,280 | 3 | 0 | 0 |
| `transfers.csv` | 35,181 | 10 | 30,897 | 0 |
| `units.csv` | 49,426 | 13 | 28,442 | 0 |

## Findings that affect redistribution

- **Facility label noise:** 1,852 / 17,430 request labels differ from the canonical facility name; 710 still differ after case and whitespace normalization. The pipeline keeps the raw label and uses `facility_id` for the canonical join.
- **Uncertain movement:** 1,046 / 35,181 transfers have no `received_at`. Any in-stock unit whose latest dispatched move is unconfirmed is held out of suggestions until reconciled.
- **Temperature logger quality:** 55 sentinel readings (`-99.0`, `99.9`, `0.0`) were observed; the dataset README says 60. We flag the observed sentinels and do not interpolate them. There are 4,607 other readings outside the documented 2-6 C range for red cells/whole blood. 12,440 hourly rows are absent from the full-year facility/time grid; gaps remain missing.
- **Unknown blood group:** 506 donor records lack a group. 442 of 8,768 emergency requests say `unknown`. Unknown groups are never matched or imputed.
- **Potential duplicate donors:** 452 two-record signatures share birth date, sex, county and made-up phone last four digits (904 rows). These are review candidates only; records are not auto-merged.
- **Donation interval flags:** 98 collected-donation intervals are shorter than the dataset's stated 3-month/4-month minimum. They are surfaced for review and do not alter blood-unit records.
- **Documentation count differences:** the CSV has 47,363 donation rows; 45,699 fall within the stated year and 1,664 precede it, consistent with pre-period opening stock. The README's stated 60 temperature glitches differ from the 55 found in the CSV.

## Reconciliation and safety checks

- The last daily-stock snapshot contains 509 facility/component/group rows. All 509 reconcile exactly with unit-level `status=in_stock` records whose expiry date is on or after 31 October 2026; total absolute difference is 0 units.
- The units table status values are `discarded_temperature, expired, in_stock, transfused`. It has no explicit quarantine status or field, so the pipeline fails closed: only an explicit `in_stock` status can pass; any other or future status is excluded.
- 111 in-stock units are marked temperature-exposed. 0 in-stock units link to reactive screening in this data. 0 transfers have a recorded cool-box maximum above 10 C.
- Of 2,162 route records, 2,162 origin/destination pairs are unique.
- After all filters, 8,531 units are eligible for a suggestion and 135 in-stock units are excluded. See `data/processed/units_eligibility.csv` for row-level reasons.

## Cleaning decisions

1. Preserve each source CSV byte-for-byte under `data/raw/`; never rewrite raw input.
2. Add canonical facility names from `facility_id` while retaining each typed facility name.
3. Treat blank, `unknown`, invalid, or unsupported blood groups as unresolved; do not impute or substitute.
4. Flag sensor sentinels and missing hours; do not replace them with invented temperatures.
5. Keep donor duplicate signatures and short donation intervals as review flags, not automatic edits.
6. Require explicit non-reactive screening, in-stock status, in-date expiry, no unit or transfer excursion, and a confirmed, consistent location before a unit can be suggested.
7. Rank eligible units by earliest expiry first. Every suggested unit remains subject to human review.

