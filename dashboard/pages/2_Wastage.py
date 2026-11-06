"""Page 2: Wastage - Energy waste events table, type breakdown, and idle heatmap."""

import os
from datetime import datetime
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")

st.title("🚨 Energy Wastage & Anomaly Detection")
st.caption("AI/ML detection of idle waste, multi-variate anomalies, and peak demand spikes.")

# Fetch waste events
try:
    events_resp = requests.get(f"{API_URL}/waste-events?limit=200", timeout=3.0)
    events_data = events_resp.json().get("events", []) if events_resp.status_code == 200 else []
except Exception as e:
    events_data = []
    st.error(f"Cannot fetch waste events: {e}")

if not events_data:
    st.info("No wastage events logged yet. Once machines idle or trigger anomalies, incidents will appear here.")
else:
    df_events = pd.DataFrame(events_data)
    df_events["start_time"] = pd.to_datetime(df_events["start_time"])
    df_events["end_time"] = pd.to_datetime(df_events["end_time"])

    # High-level KPIs
    total_wasted_kwh = df_events["kwh_wasted"].sum()
    total_wasted_cost = df_events["cost_inr"].sum()
    anomaly_count = (df_events["event_type"] == "ANOMALY").sum()
    peak_count = (df_events["event_type"] == "PEAK_DEMAND").sum()

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Wasted Energy", f"{total_wasted_kwh:,.1f} kWh")
    k2.metric("Total Wasted Cost", f"₹ {total_wasted_cost:,.2f}")
    k3.metric("Anomalies Flagged", f"{anomaly_count}")
    k4.metric("Peak Demand Breaches", f"{peak_count}")

    st.divider()

    # Visualizations: Breakdown by Type & Machine
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Wastage Cost by Event Type")
        fig_type = px.pie(
            df_events,
            names="event_type",
            values="cost_inr",
            hole=0.45,
            color="event_type",
            color_discrete_map={
                "IDLE_WASTE": "#ffc107",
                "ANOMALY": "#dc3545",
                "PEAK_DEMAND": "#fd7e14",
            },
        )
        fig_type.update_layout(height=320, margin=dict(l=20, r=20, t=30, b=20))
        st.plotly_chart(fig_type, use_container_width=True)

    with c2:
        st.subheader("Wasted kWh by Machine")
        fig_mach = px.bar(
            df_events.groupby("machine_id")["kwh_wasted"].sum().reset_index(),
            x="machine_id",
            y="kwh_wasted",
            color="machine_id",
            title="Total Wasted kWh per Machine",
        )
        fig_mach.update_layout(height=320, margin=dict(l=20, r=20, t=30, b=20), showlegend=False)
        st.plotly_chart(fig_mach, use_container_width=True)

    st.divider()

    # Idle-Hours Heatmap by Machine and Hour of Day
    st.subheader("📅 Idle-Hours Wastage Heatmap (Machine vs. Hour of Day)")
    df_events["hour"] = df_events["start_time"].dt.hour
    heatmap_data = (
        df_events[df_events["event_type"] == "IDLE_WASTE"]
        .groupby(["machine_id", "hour"])["kwh_wasted"]
        .sum()
        .unstack(fill_value=0.0)
    )

    # Reindex for 0 to 23 hours
    for h in range(24):
        if h not in heatmap_data.columns:
            heatmap_data[h] = 0.0
    heatmap_data = heatmap_data.sort_index(axis=1)

    if not heatmap_data.empty:
        fig_heat = px.imshow(
            heatmap_data,
            labels=dict(x="Hour of Day (0-23)", y="Machine", color="Wasted kWh"),
            x=[f"{h:02d}:00" for h in heatmap_data.columns],
            y=heatmap_data.index,
            color_continuous_scale="Viridis",
            aspect="auto",
        )
        fig_heat.update_layout(height=280)
        st.plotly_chart(fig_heat, use_container_width=True)
    else:
        st.caption("Insufficient idle waste distribution data to plot 24h heatmap.")

    st.divider()

    # Detailed Incident Log Table sorted by cost
    st.subheader("📋 Waste Incident Log (Sorted by Financial Impact)")
    sorted_df = df_events.sort_values("cost_inr", ascending=False)
    st.dataframe(
        sorted_df[["id", "event_type", "machine_id", "start_time", "kwh_wasted", "cost_inr", "severity", "description"]],
        use_container_width=True,
        hide_index=True,
    )

