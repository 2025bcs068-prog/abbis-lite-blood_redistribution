from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from abbis.audit import recent_events, record_decision
from abbis.data_pipeline import BLOOD_GROUPS, REPORTS
from abbis.engine import load_demo_data, make_suggestion
from scripts.prepare_data import prepare_redistribution_data
from scripts.evaluate_forecast import evaluate

st.set_page_config(page_title="ABBIS-Lite | Redistribution", page_icon="🩸", layout="wide")


@st.cache_data(show_spinner="Preparing the preserved synthetic data…")
def get_data():
    if not (REPORTS / "forecast_backtest.json").exists():
        evaluate()
    if not (REPORTS / "data_quality.json").exists():
        prepare_redistribution_data()
    return load_demo_data()


data = get_data()
metrics = data["forecast_metrics"]
units = data["units"]
facilities = data["facilities"].sort_values("name")
facility_labels = {
    row.facility_id: f"{row.name} ({row.facility_id})"
    for row in facilities.itertuples()
}

st.title("ABBIS-Lite · Blood redistribution review")
st.caption("Terumo BCT Africa Hackathon 2026 · Synthetic data snapshot through 31 October 2026")
st.warning("Historical demonstration only: the stock snapshot ends on 31 October 2026. Reconcile live stock and expiry before any real movement.")

eligible_count = int(units["eligible_for_redistribution"].astype(str).str.lower().eq("true").sum())
unsafe_stock = int(
    (units["status"].eq("in_stock")
     & ~units["eligible_for_redistribution"].astype(str).str.lower().eq("true")).sum()
)
col1, col2, col3, col4 = st.columns(4)
col1.metric("Eligible unit lots", f"{eligible_count:,}")
col2.metric("In-stock units held out", f"{unsafe_stock:,}")
col3.metric("28-day forecast WAPE", f"{metrics['model']['wape']:.1%}")
col4.metric("Baseline WAPE", f"{metrics['baseline']['wape']:.1%}")

review_tab, quality_tab, audit_tab = st.tabs(
    ["Review a shortage", "Data quality", "Decision audit"]
)

with review_tab:
    st.subheader("Shortage estimate and candidate units")
    left, right = st.columns([1, 2])
    with left:
        destination_id = st.selectbox(
            "Receiving facility",
            list(facility_labels),
            index=(list(facility_labels).index("HSP-018") if "HSP-018" in facility_labels else 0),
            format_func=lambda facility_id: facility_labels[facility_id],
        )
        component = st.selectbox("Component", ["RBC", "PLT", "FFP"], index=0)
        group_options = sorted(BLOOD_GROUPS)
        blood_group = st.selectbox("Exact blood group", group_options, index=group_options.index("A+"))
        st.info("Only an exact component and blood-group match is considered. No substitution is attempted.")

    suggestion = make_suggestion(data, destination_id, component, blood_group)
    forecast = suggestion["forecast"]
    with right:
        if not forecast["available"]:
            st.warning(f"No forecast: {forecast['reason']}")
            st.metric("Eligible local stock", suggestion["destination_stock"])
            st.write("Fallback: use the stock snapshot and a human's local assessment. No transfer suggestion was generated.")
        else:
            fc1, fc2, fc3 = st.columns(3)
            fc1.metric("Eligible local stock", suggestion["destination_stock"])
            fc2.metric("Expected demand · next 7 days", f"{forecast['selected_7d']:.1f} units")
            fc3.metric("Planning gap", f"{suggestion['shortage_units']} units")
            st.caption(
                f"Estimate: {forecast['selected_method']}; evaluated WAPE {forecast['wape']:.1%}. "
                "This synthetic backtest error is high and is not a confidence interval. Treat the estimate as uncertain."
            )
            st.write(suggestion["reason"])

    candidates = suggestion["recommendation_units"]
    if candidates:
        candidate_frame = pd.DataFrame(candidates)
        st.markdown("#### FEFO-ranked candidate units")
        st.caption(
            f"The estimated gap is {suggestion['shortage_units']} units; "
            f"{len(candidates)} eligible units remain after source reserves."
        )
        source_summary = suggestion["source_summary"]
        if not source_summary.empty:
            st.dataframe(source_summary, use_container_width=True, hide_index=True)
        display = candidate_frame.copy()
        display["expiry_date"] = pd.to_datetime(display["expiry_date"]).dt.date.astype(str)
        st.dataframe(
            display[["unit_id", "source_facility", "expiry_date", "days_to_expiry", "travel_hours", "reason"]],
            use_container_width=True,
            hide_index=True,
        )
        source_ids = list(dict.fromkeys(item["source_facility_id"] for item in candidates))
        source_id = st.selectbox(
            "Source facility for this review",
            source_ids,
            format_func=lambda facility_id: facility_labels.get(facility_id, facility_id),
        )
        source_candidates = [item for item in candidates if item["source_facility_id"] == source_id]
        proposed = len(source_candidates)
        st.caption(
            "The source retains its recent 7-day forecasted demand. Candidate units are limited to the remaining estimated surplus."
        )
        with st.form("decision_form"):
            reviewer = st.text_input("Reviewer name (demo record; not authenticated)")
            reviewer_role = st.selectbox("Reviewer role", ["Supply coordinator", "Receiving facility officer"])
            decision = st.radio("Decision", ["Accept", "Change", "Reject"], horizontal=True)
            qty = st.number_input(
                "Units to approve",
                min_value=1,
                max_value=max(1, proposed),
                value=max(1, proposed),
                disabled=(decision == "Reject"),
            )
            reason = st.text_input("Reason or change note", placeholder="Required for Change or Reject")
            submitted = st.form_submit_button("Record human decision")
        if submitted:
            if not reviewer.strip():
                st.error("Enter the reviewer name for the local audit record.")
            elif decision in {"Change", "Reject"} and not reason.strip():
                st.error("Add a reason for a changed or rejected suggestion.")
            else:
                chosen_qty = 0 if decision == "Reject" else int(qty)
                chosen_units = [item["unit_id"] for item in source_candidates[:chosen_qty]]
                record_decision(
                    reviewer_name=reviewer,
                    reviewer_role=reviewer_role,
                    decision=decision,
                    reason=reason or "Accepted as suggested by reviewer.",
                    destination_facility_id=destination_id,
                    source_facility_id=source_id,
                    component=component,
                    blood_group=blood_group,
                    proposed_quantity=proposed,
                    decision_quantity=chosen_qty,
                    selected_unit_ids=chosen_units,
                )
                st.success(f"{decision} recorded locally. No inventory movement was executed.")
                st.rerun()
    elif forecast.get("available"):
        st.info("No eligible source units are available above the estimated source reserve. Use manual coordination.")

    with st.expander("How the recommendation is formed"):
        st.markdown(
            "- Forecast a 7-day demand from the trailing 28-day mean when its rolling backtest beats the trailing 7-day baseline.\n"
            "- Estimate a source's own 7-day demand and retain that reserve; if source history is missing, do not suggest its stock.\n"
            "- Require explicit in-stock status, non-reactive screening, known exact group, unexpired unit, no temperature exposure, and confirmed location.\n"
            "- Sort candidates by earliest expiry, then route time. An Accept decision only records a human choice."
        )

with quality_tab:
    st.subheader("Data-quality evidence")
    quality = json.loads((REPORTS / "data_quality.json").read_text(encoding="utf-8"))
    q = quality["quality_findings"]
    st.markdown(
        f"- **Facility labels:** {q['request_facility_name_exact_mismatches']:,} request labels differ from the canonical facility name; facility IDs resolve the join.\n"
        f"- **Unconfirmed transfers:** {q['transfers_missing_receipt_time']:,} rows; latest unconfirmed moves are held out.\n"
        f"- **Unknown group:** {q['donors_missing_blood_group']:,} donor records lack a group; {q['requests_with_unknown_group_and_emergency_urgency']:,} emergency requests have unknown group.\n"
        f"- **Temperature:** {q['temperature_sentinel_glitches_observed']} sentinels and {q['temperature_rows_missing_from_full_year_grid']:,} missing hourly rows; neither is imputed.\n"
        f"- **Unit snapshot:** {q['last_snapshot_stock_group_reconciliations_exact']:,}/{q['last_snapshot_stock_groups']:,} aggregate groups reconcile to unit lots."
    )
    st.dataframe(pd.DataFrame(quality["table_profiles"]).T, use_container_width=True)
    st.markdown("Full report: `reports/data_quality.md`.")

with audit_tab:
    st.subheader("Local decision audit")
    events = recent_events()
    if events:
        audit_frame = pd.DataFrame(events)
        audit_frame["selected_unit_ids"] = audit_frame["selected_unit_ids"].apply(
            lambda value: ", ".join(json.loads(value))
        )
        st.dataframe(audit_frame, use_container_width=True, hide_index=True)
    else:
        st.info("No review decisions recorded on this laptop yet.")
    st.caption("The log is local SQLite data. Reviewer names are entered text, not verified identities or secure authentication.")

