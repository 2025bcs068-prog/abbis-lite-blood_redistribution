# Demand forecast backtest

**Result:** trailing 28-day mean WAPE 0.723; trailing 7-day mean baseline WAPE 0.852. The 28-day model reduced WAPE by 15.2% relative to the baseline in this evaluation.

- Data: synthetic starter dataset, requests.csv
- Target: units_requested by facility, known patient blood group, and component
- Design: rolling origin, non-overlapping 7-day horizons, 28 days of prior history
- Origins: 43 weekly origins from 2026-01-01 through 2026-10-24
- Series: 420
- Request rows in scope: 16,988
- Held-out requested units across scored horizons: 27,602
- MAE per series-horizon: model 1.105; baseline 1.303
- Unknown-group requests are excluded from group-specific forecasts.

WAPE is weighted absolute error divided by total actual demand; lower is better. This is a synthetic-data backtest, not evidence of real-world performance. The error is substantial, so each forecast is labelled uncertain and the human remains responsible for a decision. It is not a clinical confidence interval.

Reproduce with `python -m scripts.evaluate_forecast`.
