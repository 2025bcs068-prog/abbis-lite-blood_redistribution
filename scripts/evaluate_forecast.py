from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from abbis.data_pipeline import RAW, REPORTS


def evaluate() -> dict:
    requests = pd.read_csv(RAW / "requests.csv", parse_dates=["requested_at"])
    known_groups = {"O+", "A+", "B+", "AB+", "O-", "A-", "B-", "AB-"}
    supported_components = {"RBC", "PLT", "FFP"}
    requests = requests[
        requests["patient_blood_group"].isin(known_groups)
        & requests["component_requested"].isin(supported_components)
        & requests["requested_at"].notna()
    ].copy()
    requests["request_day"] = requests["requested_at"].dt.normalize()
    requests["units_requested"] = pd.to_numeric(
        requests["units_requested"], errors="coerce"
    ).fillna(0)
    daily = requests.pivot_table(
        index="request_day",
        columns=["facility_id", "patient_blood_group", "component_requested"],
        values="units_requested",
        aggfunc="sum",
        fill_value=0,
    )
    dates = pd.date_range("2025-11-01", "2026-10-31", freq="D")
    daily = daily.reindex(dates, fill_value=0).fillna(0)

    absolute_error_7d: list[float] = []
    absolute_error_28d: list[float] = []
    actual_total = 0.0
    origins = pd.date_range("2026-01-01", "2026-10-24", freq="7D")
    origins_used = 0
    for origin in origins:
        history = daily.loc[origin - pd.Timedelta(days=28) : origin - pd.Timedelta(days=1)]
        actual_window = daily.loc[origin : origin + pd.Timedelta(days=6)]
        if len(history) != 28 or len(actual_window) != 7:
            continue
        actual = actual_window.sum(axis=0).to_numpy(dtype=float)
        pred_7d = history.tail(7).mean(axis=0).to_numpy(dtype=float) * 7
        pred_28d = history.mean(axis=0).to_numpy(dtype=float) * 7
        absolute_error_7d.extend(np.abs(actual - pred_7d).tolist())
        absolute_error_28d.extend(np.abs(actual - pred_28d).tolist())
        actual_total += float(actual.sum())
        origins_used += 1

    if not origins_used or actual_total <= 0:
        raise ValueError("Not enough known-group history to evaluate the 7-day horizon")

    wape_baseline = float(sum(absolute_error_7d) / actual_total)
    wape_model = float(sum(absolute_error_28d) / actual_total)
    result = {
        "data": "synthetic starter dataset, requests.csv",
        "target": "units_requested by facility, known patient blood group, and component",
        "unknown_group_requests_excluded": True,
        "backtest": "rolling origin, non-overlapping 7-day horizons, 28 days of prior history",
        "first_origin": "2026-01-01",
        "last_origin": "2026-10-24",
        "origins": origins_used,
        "facility_group_component_series": int(daily.shape[1]),
        "request_rows_in_scope": int(len(requests)),
        "held_out_units_total": int(actual_total),
        "baseline": {
            "name": "trailing 7-day mean",
            "wape": wape_baseline,
            "mae_units_per_series_horizon": float(np.mean(absolute_error_7d)),
        },
        "model": {
            "name": "trailing 28-day mean",
            "wape": wape_model,
            "mae_units_per_series_horizon": float(np.mean(absolute_error_28d)),
        },
        "relative_wape_reduction": float((wape_baseline - wape_model) / wape_baseline),
        "uncertainty_note": "WAPE is a broad error measure on synthetic held-out history, not a clinical confidence interval.",
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "forecast_backtest.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    _write_markdown(result)
    return result


def _write_markdown(result: dict) -> None:
    baseline = result["baseline"]
    model = result["model"]
    reduction = result["relative_wape_reduction"] * 100
    content = f"""# Demand forecast backtest

**Result:** trailing 28-day mean WAPE {model['wape']:.3f}; trailing 7-day mean baseline WAPE {baseline['wape']:.3f}. The 28-day model reduced WAPE by {reduction:.1f}% relative to the baseline in this evaluation.

- Data: {result['data']}
- Target: {result['target']}
- Design: {result['backtest']}
- Origins: {result['origins']} weekly origins from {result['first_origin']} through {result['last_origin']}
- Series: {result['facility_group_component_series']}
- Request rows in scope: {result['request_rows_in_scope']:,}
- Held-out requested units across scored horizons: {result['held_out_units_total']:,}
- MAE per series-horizon: model {model['mae_units_per_series_horizon']:.3f}; baseline {baseline['mae_units_per_series_horizon']:.3f}
- Unknown-group requests are excluded from group-specific forecasts.

WAPE is weighted absolute error divided by total actual demand; lower is better. This is a synthetic-data backtest, not evidence of real-world performance. The error is substantial, so each forecast is labelled uncertain and the human remains responsible for a decision. It is not a clinical confidence interval.

Reproduce with `python -m scripts.evaluate_forecast`.
"""
    (REPORTS / "forecast_backtest.md").write_text(content, encoding="utf-8")


if __name__ == "__main__":
    result = evaluate()
    print(
        f"7-day WAPE: 28-day mean {result['model']['wape']:.3f}; "
        f"7-day baseline {result['baseline']['wape']:.3f}"
    )

