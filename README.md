# ABBIS-Lite: Blood Redistribution

Terumo BCT Africa Hackathon 2026 · Challenge area: Redistribution

## The problem

Blood service coordinators need to spot a likely shortfall at one facility while suitable stock may be available elsewhere. Messy facility labels, stale movement records, expiry, screening status and cold-chain exposure make a simple stock total unsafe to act on.

This prototype uses the organisers' synthetic Kenya-modelled starter dataset, with an inventory snapshot through 31 October 2026. It is not evidence about real facilities.

## What we built

- What works now: being built during the official 24-hour window; the first slice will cover data quality, expiry-aware stock, exact-group redistribution suggestions, and human review.
- What is mocked or not finished: no live blood-service integration, dispatch, clinical authorization, multi-user authentication, or synchronization between devices.

Demo video (3 minutes or less): pending
Live demo: pending · Test log-in: not applicable to this local prototype

## How to run it

Setup and launch instructions will be completed with the working slice.

## Architecture

See [the architecture diagram](docs/architecture.md). The workflow reads the synthetic source tables, flags data issues, applies hard stock-safety filters, ranks possible donor units, and records a human decision locally. It does not dispatch blood or make a transfusion decision.

## AI and data

- What the AI or data feature does: estimate short-horizon demand from recent request history, then identify eligible exact-group units that can be considered for redistribution.
- Baseline we compared against: a trailing 7-day mean demand estimate.
- Result: see [the rolling backtest](reports/forecast_backtest.md); the comparison uses the synthetic request history and a 7-day forecast horizon.
- How a user sees the reason for a recommendation: eligibility checks, source surplus, recipient forecast, route time, and expiry date are shown.
- Who approves it (Accept / Change / Reject): a human reviewer chooses Accept, Change, or Reject. Acceptance records a decision only; it does not move inventory.
- What happens if the AI is wrong or offline: the measured baseline and last available stock snapshot remain visible; if recent data is unavailable, the app makes no forecast-driven suggestion. The local prototype can record a review without an external connection.

## Data

The source CSVs and dictionary are in [`data/raw/`](data/raw/). They are synthetic and were supplied in the hackathon Applicant's Kit. No real donor, patient, or facility records are used. Raw files are preserved; repeatable flags and normalized outputs are written separately under `data/processed/`.

## African conditions

This is a small local prototype designed to keep the data and review workflow available on one laptop. It does not yet synchronize offline decisions across devices or support SMS/USSD. Facility names and connectivity fields remain configurable data rather than code constants.

## AI tools we used

OpenAI Codex was used during the build window for data profiling, code drafting, and documentation. Team members are expected to review and explain every submitted change.

## Team

| Name | Role | Country | Presenting Friday (in person / online) |
|------|------|---------|-----------------------------------------|
| Biyimbwa Elijah Simwogerere | Team lead, backend, architecture | Uganda | TBD |
| Kissa Keith Ndiema | Backend, AI/data | Uganda | TBD |
| Okori Sadrach | AI/data | Uganda | TBD |
| Tusiime Betty | Frontend | Uganda | TBD |
| Kisembo Stephen | AI/data, frontend |  | TBD |

## Known limits and next steps

- The inputs are a synthetic year ending 31 October 2026; they are not live stock feeds.
- Exact blood-group matching is the only matching mode. Unknown groups and unconfirmed movements are excluded from unit suggestions.
- The recommendation is decision support, not authorization to move or transfuse blood.
- The local audit log records the name entered by the reviewer; it is not authenticated identity or a tamper-proof audit service.
- Add a real two-role authorization model, cross-device offline sync, and expert review before any operational use.

