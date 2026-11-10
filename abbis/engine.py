from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from .data_pipeline import AS_OF, BLOOD_GROUPS, PROCESSED, RAW, REPORTS


def load_demo_data() -> dict[str, pd.DataFrame | dict]:
    if not (PROCESSED / "units_eligibility.csv").exists():
        raise FileNotFoundError("Run `python -m scripts.prepare_data` first.")
    units = pd.read_csv(PROCESSED / "units_eligibility.csv", parse_dates=["expiry_date_parsed"])
    requests = pd.read_csv(RAW / "requests.csv", parse_dates=["requested_at"])
    facilities = pd.read_csv(RAW / "facilities.csv")
    routes = pd.read_csv(RAW / "routes.csv")
    forecasts = json.loads((REPORTS / "forecast_backtest.json").read_text(encoding="utf-8"))
    return {"units": units, "requests": requests, "facilities": facilities, "routes": routes, "forecast_metrics": forecasts}


def demand_estimate(
    requests: pd.DataFrame,
    facility_id: str,
    component: str,
    blood_group: str,
    as_of: pd.Timestamp = AS_OF,
    history_days: int = 28,
) -> dict:
    if blood_group not in BLOOD_GROUPS:
        return {"available": False, "reason": "Unknown or unsupported blood group."}
    start = as_of - pd.Timedelta(days=history_days - 1)
    subset = requests[
        requests["facility_id"].eq(facility_id)
        & requests["component_requested"].eq(component)
        & requests["patient_blood_group"].eq(blood_group)
        & requests["requested_at"].between(start, as_of + pd.Timedelta(days=1), inclusive="left")
    ]
    if subset.empty:
        return {
            "available": False,
            "reason": f"No observed {component} {blood_group} requests in the {history_days}-day history; use manual review.",
        }
    requested = pd.to_numeric(subset["units_requested"], errors="coerce").fillna(0)
    model_7d = float(requested.sum() * 7 / history_days)
    last7 = subset[subset["requested_at"] >= as_of - pd.Timedelta(days=6)]
    baseline_7d = float(pd.to_numeric(last7["units_requested"], errors="coerce").fillna(0).sum())
    return {
        "available": True,
        "history_rows": int(len(subset)),
        "history_units": float(requested.sum()),
        "model_7d": model_7d,
        "baseline_7d": baseline_7d,
        "history_days": history_days,
    }


def make_suggestion(
    data: dict,
    destination_id: str,
    component: str,
    blood_group: str,
) -> dict:
    units: pd.DataFrame = data["units"].copy()
    requests: pd.DataFrame = data["requests"]
    routes: pd.DataFrame = data["routes"]
    facilities: pd.DataFrame = data["facilities"]
    metrics: dict = data["forecast_metrics"]

    dest_forecast = demand_estimate(requests, destination_id, component, blood_group)
    eligible = units[units["eligible_for_redistribution"].astype(str).str.lower().eq("true")].copy()
    eligible = eligible[
        eligible["component"].eq(component) & eligible["blood_group"].eq(blood_group)
    ]
    dest_stock = int((eligible["current_facility_id"] == destination_id).sum())
    if not dest_forecast["available"]:
        return {
            "forecast": dest_forecast,
            "destination_stock": dest_stock,
            "shortage_units": None,
            "recommendation_units": [],
            "source_summary": pd.DataFrame(),
            "reason": dest_forecast["reason"],
        }

    choose_model = metrics["model"]["wape"] <= metrics["baseline"]["wape"]
    selected_forecast = dest_forecast["model_7d"] if choose_model else dest_forecast["baseline_7d"]
    shortage_units = max(0, math.ceil(selected_forecast - dest_stock))
    dest_forecast["selected_method"] = "trailing 28-day mean" if choose_model else "trailing 7-day baseline"
    dest_forecast["selected_7d"] = selected_forecast
    dest_forecast["wape"] = metrics["model"]["wape"] if choose_model else metrics["baseline"]["wape"]

    options = []
    summary_rows = []
    if shortage_units:
        sites = facilities.set_index("facility_id")
        routes_by_pair = routes.set_index(["from_facility_id", "to_facility_id"])
        for source_id, source_units in eligible.groupby("current_facility_id"):
            if source_id == destination_id:
                continue
            source_forecast = demand_estimate(requests, source_id, component, blood_group)
            # With no recent request history, preserve the source stock for manual review.
            if not source_forecast["available"]:
                continue
            source_model = (
                source_forecast["model_7d"]
                if metrics["model"]["wape"] <= metrics["baseline"]["wape"]
                else source_forecast["baseline_7d"]
            )
            source_stock = int(len(source_units))
            surplus = max(0, math.floor(source_stock - source_model))
            if not surplus:
                continue
            try:
                route = routes_by_pair.loc[(source_id, destination_id)]
            except KeyError:
                continue
            if isinstance(route, pd.DataFrame):
                route = route.iloc[0]
            travel_hours = float(route["typical_travel_hours"])
            source_name = str(sites.loc[source_id, "name"])
            summary_rows.append(
                {
                    "source_facility_id": source_id,
                    "source_facility": source_name,
                    "eligible_stock": source_stock,
                    "7_day_forecast": round(source_model, 2),
                    "stock_above_forecast": surplus,
                    "travel_hours": travel_hours,
                }
            )
            source_units = source_units.sort_values(
                ["expiry_date_parsed", "unit_id"], na_position="last"
            ).head(surplus)
            for _, unit in source_units.iterrows():
                options.append(
                    {
                        "unit_id": unit["unit_id"],
                        "source_facility_id": source_id,
                        "source_facility": source_name,
                        "expiry_date": unit["expiry_date_parsed"],
                        "days_to_expiry": int(unit["days_to_expiry"]),
                        "travel_hours": travel_hours,
                        "source_surplus": surplus,
                        "reason": "Exact component and group; in stock; non-reactive screen; no known temperature exposure; confirmed location; earliest expiry first.",
                    }
                )

    options.sort(key=lambda item: (item["expiry_date"], item["travel_hours"], item["unit_id"]))
    selected_units = options[:shortage_units]
    source_summary = pd.DataFrame(summary_rows).sort_values(
        ["travel_hours", "source_facility_id"]
    ) if summary_rows else pd.DataFrame()
    return {
        "forecast": dest_forecast,
        "destination_stock": dest_stock,
        "shortage_units": shortage_units,
        "recommendation_units": selected_units,
        "source_summary": source_summary,
        "reason": (
            "The quantity is capped by the forecasted gap and estimated source stock above its own 7-day demand."
            if selected_units
            else "No source has a confirmed, exact-group unit above its own estimated 7-day demand."
        ),
    }

