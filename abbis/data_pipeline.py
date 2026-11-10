from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"
AS_OF = pd.Timestamp("2026-10-31")
BLOOD_GROUPS = {"O+", "A+", "B+", "AB+", "O-", "A-", "B-", "AB-"}
PRIMARY_KEYS = {
    "facilities": "facility_id",
    "donors": "donor_id",
    "drives": "drive_id",
    "donations": "donation_id",
    "units": "unit_id",
    "transfers": "transfer_id",
    "requests": "request_id",
    "power_outages": "outage_id",
}
TABLES = sorted(RAW.glob("*.csv"))


def _read(name: str, **kwargs) -> pd.DataFrame:
    return pd.read_csv(RAW / f"{name}.csv", **kwargs)


def _clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return " ".join(str(value).upper().split())


def _flag_report() -> dict:
    """Profile source data without changing or overwriting the raw files."""
    table_profiles = {}
    for path in TABLES:
        name = path.stem
        frame = pd.read_csv(path)
        profile = {
            "rows": int(len(frame)),
            "columns": list(frame.columns),
            "exact_duplicate_rows": int(frame.duplicated().sum()),
            "missing_by_column": {
                col: int(count)
                for col, count in frame.isna().sum().items()
                if count
            },
        }
        primary_key = PRIMARY_KEYS.get(name)
        if primary_key:
            profile["primary_key_blank"] = int(frame[primary_key].isna().sum())
            profile["primary_key_duplicates"] = int(frame[primary_key].duplicated().sum())
        table_profiles[name] = profile

    facilities = _read("facilities")
    requests = _read("requests")
    donors = _read("donors", keep_default_na=False)
    donations = _read("donations", parse_dates=["collection_date"])
    units = _read("units", parse_dates=["expiry_date"])
    transfers = _read("transfers", parse_dates=["dispatched_at", "received_at"])
    daily_stock = _read("daily_stock", parse_dates=["date"])
    temperature = _read("temperature_logs", parse_dates=["recorded_at"])

    duplicate_signature = donors.groupby(
        ["birth_date", "sex", "home_county", "phone_last4"], dropna=False
    )["donor_id"].agg(list)
    duplicate_signature = duplicate_signature[duplicate_signature.map(len) > 1]

    facility_names = facilities.set_index("facility_id")["name"]
    canonical = requests["facility_id"].map(facility_names)
    raw_name_exact_mismatch = requests["facility_name_raw"].fillna("") != canonical.fillna("")
    raw_name_normalized_mismatch = requests["facility_name_raw"].map(_clean_text) != canonical.map(_clean_text)

    donor_sex = donors.set_index("donor_id")["sex"].to_dict()
    donation_groups = donations[donations["outcome"] == "collected"].groupby("donor_id")
    too_soon = 0
    for donor_id, group in donation_groups:
        dates = sorted(pd.to_datetime(group["collection_date"]).dropna().dt.normalize().unique())
        months = 4 if donor_sex.get(donor_id) == "F" else 3
        for first, second in zip(dates, dates[1:]):
            if pd.Timestamp(first) + pd.DateOffset(months=months) > pd.Timestamp(second):
                too_soon += 1

    date_start = pd.Timestamp("2025-11-01")
    date_end = pd.Timestamp("2026-10-31")
    in_year_donations = donations["collection_date"].between(date_start, date_end, inclusive="both")

    unknown_emergency = (
        (requests["urgency"] == "emergency")
        & (requests["patient_blood_group"].astype(str).str.lower() == "unknown")
    )
    temps = pd.to_numeric(temperature["temp_c"], errors="coerce")
    sentinel = temps.isin([-99.0, 99.9, 0.0])
    valid_temp_outside = (~sentinel) & ((temps < 2.0) | (temps > 6.0))
    expected_hours = pd.date_range(
        "2025-11-01 00:00:00", "2026-10-31 23:00:00", freq="h"
    )
    expected_log_rows = len(expected_hours) * facilities["facility_id"].nunique()

    units_in_stock = units[units["status"] == "in_stock"].copy()
    units_in_stock["expiry_date"] = pd.to_datetime(units_in_stock["expiry_date"], errors="coerce")
    units_on_snapshot = units_in_stock[units_in_stock["expiry_date"] >= AS_OF]
    last_stock_date = daily_stock["date"].max()
    daily_last = daily_stock[daily_stock["date"] == last_stock_date].groupby(
        ["facility_id", "component", "blood_group"], as_index=False
    )["units_in_stock_end_of_day"].sum()
    unit_last = units_on_snapshot.groupby(
        ["current_facility_id", "component", "blood_group"], as_index=False
    ).size().rename(columns={"current_facility_id": "facility_id", "size": "unit_count"})
    reconcile = daily_last.merge(
        unit_last,
        on=["facility_id", "component", "blood_group"],
        how="outer",
    ).fillna({"units_in_stock_end_of_day": 0, "unit_count": 0})
    reconcile["difference"] = (
        reconcile["units_in_stock_end_of_day"] - reconcile["unit_count"]
    )

    transfer_temp = pd.to_numeric(transfers["coolbox_max_temp_c"], errors="coerce")
    unit_exposed = units_in_stock["temp_excursion_exposed"].astype(str).str.lower().isin(
        {"true", "1", "yes"}
    )
    donations_lookup = donations.set_index("donation_id")["screening_result"]
    units["source_screening_result"] = units["donation_id"].map(donations_lookup)
    reactive_stock = int(
        ((units["status"] == "in_stock") & (units["source_screening_result"] == "reactive")).sum()
    )

    return {
        "as_of_date": AS_OF.date().isoformat(),
        "table_profiles": table_profiles,
        "quality_findings": {
            "donor_duplicate_signature_pairs": int(len(duplicate_signature)),
            "donor_rows_in_duplicate_signatures": int(duplicate_signature.map(len).sum()),
            "donors_missing_blood_group": int(donors["blood_group"].astype(str).str.strip().eq("").sum()),
            "request_facility_name_exact_mismatches": int(raw_name_exact_mismatch.sum()),
            "request_facility_name_mismatches_after_case_space_normalization": int(raw_name_normalized_mismatch.sum()),
            "requests_with_unknown_group_and_emergency_urgency": int(unknown_emergency.sum()),
            "emergency_requests": int((requests["urgency"] == "emergency").sum()),
            "transfers_missing_receipt_time": int(transfers["received_at"].isna().sum()),
            "temperature_sentinel_glitches_observed": int(sentinel.sum()),
            "temperature_sentinel_glitches_claimed_in_dataset_readme": 60,
            "temperature_valid_readings_outside_documented_2_to_6_c_range": int(valid_temp_outside.sum()),
            "temperature_rows_observed": int(len(temperature)),
            "temperature_rows_expected_for_full_year": int(expected_log_rows),
            "temperature_rows_missing_from_full_year_grid": int(max(0, expected_log_rows - temperature[["facility_id", "recorded_at"]].drop_duplicates().shape[0])),
            "collected_donation_gaps_below_3_or_4_calendar_months": int(too_soon),
            "donation_rows_total": int(len(donations)),
            "donation_rows_inside_dataset_year": int(in_year_donations.sum()),
            "donation_rows_before_dataset_year": int((donations["collection_date"] < date_start).sum()),
            "units_in_stock_at_snapshot": int(len(units_in_stock)),
            "eligible_by_status_and_expiry_before_other_safety_flags": int(len(units_on_snapshot)),
            "in_stock_units_with_temperature_exposure_flag": int(unit_exposed.sum()),
            "in_stock_units_linked_to_reactive_screening": reactive_stock,
            "coolbox_readings_above_10_c": int((transfer_temp > 10.0).sum()),
            "last_snapshot_stock_groups": int(len(reconcile)),
            "last_snapshot_stock_group_reconciliations_exact": int(reconcile["difference"].eq(0).sum()),
            "last_snapshot_absolute_unit_difference": int(reconcile["difference"].abs().sum()),
            "route_rows": int(len(_read("routes"))),
            "route_pairs_unique": int(_read("routes")[["from_facility_id", "to_facility_id"]].drop_duplicates().shape[0]),
            "units_with_quarantine_status": int(units["status"].astype(str).str.lower().str.contains("quarant", na=False).sum()),
            "unit_status_values": sorted(units["status"].dropna().astype(str).unique().tolist()),
            "valid_blood_groups_in_unit_table": bool(units["blood_group"].dropna().isin(BLOOD_GROUPS).all()),
        },
    }


def prepare_redistribution_data() -> dict:
    """Create traceable derived tables; source CSVs are read-only inputs."""
    PROCESSED.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)

    facilities = _read("facilities")
    facility_names = facilities.set_index("facility_id")["name"]
    donations = _read("donations", keep_default_na=False)
    units = _read("units", keep_default_na=False)
    transfers = _read("transfers", keep_default_na=False)
    requests = _read("requests", keep_default_na=False)

    # The dictionary says facility_id is authoritative. Keep the typed label too.
    requests["facility_name_canonical"] = requests["facility_id"].map(facility_names).fillna("")
    requests["facility_name_mismatch"] = requests.apply(
        lambda row: _clean_text(row["facility_name_raw"])
        != _clean_text(row["facility_name_canonical"]),
        axis=1,
    )
    requests["blood_group_known"] = requests["patient_blood_group"].isin(BLOOD_GROUPS)
    requests.to_csv(PROCESSED / "requests_normalized.csv", index=False)

    transfer_times = transfers.copy()
    transfer_times["dispatched_at_parsed"] = pd.to_datetime(
        transfer_times["dispatched_at"], errors="coerce"
    )
    transfer_times["received_at_parsed"] = pd.to_datetime(
        transfer_times["received_at"], errors="coerce"
    )
    transfer_times["coolbox_max_temp_c_numeric"] = pd.to_numeric(
        transfer_times["coolbox_max_temp_c"], errors="coerce"
    )
    transfer_times["receipt_confirmed"] = transfer_times["received_at_parsed"].notna()
    # The dictionary defines a cool-box maximum above 10 C as an excursion.
    transfer_times["temperature_excursion"] = (
        transfer_times["coolbox_max_temp_c_numeric"] > 10.0
    )
    transfer_times.to_csv(PROCESSED / "transfers_flagged.csv", index=False)

    latest_move = (
        transfer_times.sort_values(["unit_id", "dispatched_at_parsed", "transfer_id"])
        .groupby("unit_id", as_index=False)
        .tail(1)
        .set_index("unit_id")
    )
    latest_unconfirmed = set(
        latest_move.index[~latest_move["receipt_confirmed"]]
    )
    last_move_to = latest_move["to_facility_id"].to_dict()
    last_move_confirmed = latest_move["receipt_confirmed"].to_dict()
    any_transfer_excursion = set(
        transfer_times.loc[transfer_times["temperature_excursion"], "unit_id"]
    )

    screening = donations.set_index("donation_id")["screening_result"].to_dict()
    units["source_screening_result"] = units["donation_id"].map(screening).fillna("")
    units["expiry_date_parsed"] = pd.to_datetime(units["expiry_date"], errors="coerce")
    units["source_screening_safe"] = units["source_screening_result"].eq("non_reactive")
    units["unit_temperature_safe"] = units["temp_excursion_exposed"].astype(str).str.lower().isin(
        {"false", "0", "no"}
    )
    units["latest_transfer_confirmed"] = units["unit_id"].map(last_move_confirmed).fillna(True)
    units["latest_transfer_destination"] = units["unit_id"].map(last_move_to).fillna("")
    units["location_conflict"] = (
        units["latest_transfer_confirmed"]
        & units["latest_transfer_destination"].ne("")
        & units["latest_transfer_destination"].ne(units["current_facility_id"])
    )
    units["transfer_temperature_safe"] = ~units["unit_id"].isin(any_transfer_excursion)
    units["known_group"] = units["blood_group"].isin(BLOOD_GROUPS)
    units["expiry_safe_as_of"] = units["expiry_date_parsed"].ge(AS_OF)
    units["eligible_for_redistribution"] = (
        units["status"].eq("in_stock")
        & units["expiry_safe_as_of"]
        & units["source_screening_safe"]
        & units["unit_temperature_safe"]
        & units["transfer_temperature_safe"]
        & units["latest_transfer_confirmed"]
        & ~units["location_conflict"]
        & units["known_group"]
        & units["current_facility_id"].isin(set(facilities["facility_id"]))
    )

    reason_columns = [
        ("status_not_in_stock", ~units["status"].eq("in_stock")),
        ("expired_or_expiry_unknown", ~units["expiry_safe_as_of"]),
        ("reactive_or_screening_unknown", ~units["source_screening_safe"]),
        ("temperature_exposure_flag_or_unknown", ~units["unit_temperature_safe"]),
        ("transfer_temperature_excursion", ~units["transfer_temperature_safe"]),
        ("latest_transfer_unconfirmed", ~units["latest_transfer_confirmed"]),
        ("transfer_location_conflict", units["location_conflict"]),
        ("blood_group_unknown_or_invalid", ~units["known_group"]),
        (
            "current_location_unknown",
            ~units["current_facility_id"].isin(set(facilities["facility_id"])),
        ),
    ]
    units["exclusion_reasons"] = [
        ";".join(label for label, mask in reason_columns if bool(mask.loc[index]))
        for index in units.index
    ]
    units["days_to_expiry"] = (units["expiry_date_parsed"] - AS_OF).dt.days
    units.to_csv(PROCESSED / "units_eligibility.csv", index=False)

    report = _flag_report()
    report["derived_inventory"] = {
        "eligible_units": int(units["eligible_for_redistribution"].sum()),
        "excluded_in_stock_units": int(
            (units["status"].eq("in_stock") & ~units["eligible_for_redistribution"]).sum()
        ),
        "in_stock_latest_moves_unconfirmed": int(
            (units["status"].eq("in_stock") & units["unit_id"].isin(latest_unconfirmed)).sum()
        ),
        "in_stock_location_conflicts": int(
            (units["status"].eq("in_stock") & units["location_conflict"]).sum()
        ),
        "in_stock_units_with_transfer_excursion": int(
            (units["status"].eq("in_stock") & ~units["transfer_temperature_safe"]).sum()
        ),
        "policy": [
            "only status=in_stock is considered",
            "source donation must be explicitly non_reactive",
            "expiry date must be on or after the 2026-10-31 end-of-day snapshot date",
            "exclude unit-level temperature exposure and any transfer cool-box excursion above 10 C",
            "exclude a latest transfer without receipt confirmation and confirmed transfer/location conflicts",
            "require an exact, known blood group; do not substitute",
            "select units in earliest-expiry-first order",
        ],
    }
    (REPORTS / "data_quality.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    _write_quality_markdown(report)
    return report


def _write_quality_markdown(report: dict) -> None:
    q = report["quality_findings"]
    d = report["derived_inventory"]
    table_rows = []
    for name, profile in report["table_profiles"].items():
        missing = sum(profile["missing_by_column"].values())
        table_rows.append(
            f"| `{name}.csv` | {profile['rows']:,} | {len(profile['columns'])} | {missing:,} | {profile['exact_duplicate_rows']:,} |"
        )
    rows = "\n".join(table_rows)
    content = f"""# Starter-data quality report

Generated from the unchanged CSV files in `data/raw/` by `python -m scripts.prepare_data`.
Dataset cut-off: {report['as_of_date']} EAT. These are synthetic records, not operational findings.

## Table profile

| Table | Rows | Columns | Missing cells | Exact duplicate rows |
|---|---:|---:|---:|---:|
{rows}

## Findings that affect redistribution

- **Facility label noise:** {q['request_facility_name_exact_mismatches']:,} / 17,430 request labels differ from the canonical facility name; {q['request_facility_name_mismatches_after_case_space_normalization']:,} still differ after case and whitespace normalization. The pipeline keeps the raw label and uses `facility_id` for the canonical join.
- **Uncertain movement:** {q['transfers_missing_receipt_time']:,} / 35,181 transfers have no `received_at`. Any in-stock unit whose latest dispatched move is unconfirmed is held out of suggestions until reconciled.
- **Temperature logger quality:** {q['temperature_sentinel_glitches_observed']:,} sentinel readings (`-99.0`, `99.9`, `0.0`) were observed; the dataset README says 60. We flag the observed sentinels and do not interpolate them. There are {q['temperature_valid_readings_outside_documented_2_to_6_c_range']:,} other readings outside the documented 2-6 C range for red cells/whole blood. {q['temperature_rows_missing_from_full_year_grid']:,} hourly rows are absent from the full-year facility/time grid; gaps remain missing.
- **Unknown blood group:** {q['donors_missing_blood_group']:,} donor records lack a group. {q['requests_with_unknown_group_and_emergency_urgency']:,} of {q['emergency_requests']:,} emergency requests say `unknown`. Unknown groups are never matched or imputed.
- **Potential duplicate donors:** {q['donor_duplicate_signature_pairs']:,} two-record signatures share birth date, sex, county and made-up phone last four digits ({q['donor_rows_in_duplicate_signatures']:,} rows). These are review candidates only; records are not auto-merged.
- **Donation interval flags:** {q['collected_donation_gaps_below_3_or_4_calendar_months']:,} collected-donation intervals are shorter than the dataset's stated 3-month/4-month minimum. They are surfaced for review and do not alter blood-unit records.
- **Documentation count differences:** the CSV has {q['donation_rows_total']:,} donation rows; {q['donation_rows_inside_dataset_year']:,} fall within the stated year and {q['donation_rows_before_dataset_year']:,} precede it, consistent with pre-period opening stock. The README's stated 60 temperature glitches differ from the {q['temperature_sentinel_glitches_observed']:,} found in the CSV.

## Reconciliation and safety checks

- The last daily-stock snapshot contains {q['last_snapshot_stock_groups']:,} facility/component/group rows. All {q['last_snapshot_stock_group_reconciliations_exact']:,} reconcile exactly with unit-level `status=in_stock` records whose expiry date is on or after 31 October 2026; total absolute difference is {q['last_snapshot_absolute_unit_difference']:,} units.
- The units table status values are `{', '.join(q['unit_status_values'])}`. It has no explicit quarantine status or field, so the pipeline fails closed: only an explicit `in_stock` status can pass; any other or future status is excluded.
- {q['in_stock_units_with_temperature_exposure_flag']:,} in-stock units are marked temperature-exposed. {q['in_stock_units_linked_to_reactive_screening']:,} in-stock units link to reactive screening in this data. {q['coolbox_readings_above_10_c']:,} transfers have a recorded cool-box maximum above 10 C.
- Of {q['route_rows']:,} route records, {q['route_pairs_unique']:,} origin/destination pairs are unique.
- After all filters, {d['eligible_units']:,} units are eligible for a suggestion and {d['excluded_in_stock_units']:,} in-stock units are excluded. See `data/processed/units_eligibility.csv` for row-level reasons.

## Cleaning decisions

1. Preserve each source CSV byte-for-byte under `data/raw/`; never rewrite raw input.
2. Add canonical facility names from `facility_id` while retaining each typed facility name.
3. Treat blank, `unknown`, invalid, or unsupported blood groups as unresolved; do not impute or substitute.
4. Flag sensor sentinels and missing hours; do not replace them with invented temperatures.
5. Keep donor duplicate signatures and short donation intervals as review flags, not automatic edits.
6. Require explicit non-reactive screening, in-stock status, in-date expiry, no unit or transfer excursion, and a confirmed, consistent location before a unit can be suggested.
7. Rank eligible units by earliest expiry first. Every suggested unit remains subject to human review.

"""
    (REPORTS / "data_quality.md").write_text(content, encoding="utf-8")

