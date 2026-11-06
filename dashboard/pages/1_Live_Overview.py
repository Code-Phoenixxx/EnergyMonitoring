"""Page 1: Live Overview - Real-time machine gauges, plant line chart, and status badges."""

import os
from datetime import datetime, timedelta
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")

st.title("⚡ Live Plant Energy Overview")
st.caption("Real-time IIoT telemetry streaming from 6 virtual factory machines.")

col_head1, col_head2 = st.columns([4, 1])
with col_head2:
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.rerun()

# 1. Fetch machines list & live readings
try:
    machines_resp = requests.get(f"{API_URL}/machines", timeout=3.0)
    machines = machines_resp.json() if machines_resp.status_code == 200 else []
except Exception as e:
    machines = []
    st.error(f"Cannot connect to API at {API_URL}: {e}")

live_data = []
plant_total_kw = 0.0

for m in machines:
    mid = m["machine_id"]
    try:
        r = requests.get(f"{API_URL}/machines/{mid}/live", timeout=2.0)
        if r.status_code == 200:
            reading = r.json()
            reading["rated_power_kw"] = m["rated_power_kw"]
            reading["name"] = m["name"]
            live_data.append(reading)
            plant_total_kw += reading["power_kw"]
    except Exception:
        pass

# Top KPI row
kpi1, kpi2, kpi3, kpi4 = st.columns(4)
kpi1.metric("Total Plant Demand", f"{plant_total_kw:.1f} kW", delta="Contract: 250 kW")
active_count = sum(1 for d in live_data if d["state"] == "RUNNING")
kpi2.metric("Running Machines", f"{active_count} / {len(machines)}")
idle_count = sum(1 for d in live_data if d["state"] == "IDLE")
kpi3.metric("Idling Machines", f"{idle_count}", delta_color="inverse")
fault_count = sum(1 for d in live_data if d["state"] == "FAULT")
kpi4.metric("Faults Detected", f"{fault_count}", delta_color="inverse")

st.divider()

# 2. Machine Gauges and Status Badges
st.subheader("Machine Load Gauges & Operating Status")
cols = st.columns(3)

for idx, d in enumerate(live_data):
    col = cols[idx % 3]
    with col:
        pct_load = (d["power_kw"] / d["rated_power_kw"]) * 100.0 if d["rated_power_kw"] > 0 else 0
        state = d["state"]
        color = "green" if state == "RUNNING" else ("orange" if state == "IDLE" else ("red" if state == "FAULT" else "gray"))

        fig = go.Figure(go.Indicator(
            mode="gauge+number",
            value=d["power_kw"],
            title={"text": f"<b>{d['name']}</b><br><span style='color:{color}'>[{state}]</span>", "font": {"size": 14}},
            gauge={
                "axis": {"range": [0, d["rated_power_kw"] * 1.15]},
                "bar": {"color": color},
                "steps": [
                    {"range": [0, d["rated_power_kw"] * 0.35], "color": "#e9ecef"},
                    {"range": [d["rated_power_kw"] * 0.35, d["rated_power_kw"] * 0.85], "color": "#d1e7dd"},
                    {"range": [d["rated_power_kw"] * 0.85, d["rated_power_kw"] * 1.15], "color": "#f8d7da"},
                ],
                "threshold": {
                    "line": {"color": "red", "width": 3},
                    "thickness": 0.75,
                    "value": d["rated_power_kw"],
                },
            },
            number={"suffix": " kW", "font": {"size": 18}},
        ))
        fig.update_layout(height=220, margin=dict(l=15, r=15, t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)

        st.caption(
            f"V: {d['voltage']:.1f} V | I: {d['current']:.1f} A | PF: {d['power_factor']:.2f} | Meter: {d['energy_kwh']:.2f} kWh"
        )

st.divider()

# 3. Live Historical Line Chart
st.subheader("Recent Power Demand (Last 2 Hours)")
history_records = []
for m in machines:
    mid = m["machine_id"]
    try:
        h_resp = requests.get(f"{API_URL}/machines/{mid}/history?limit=120", timeout=2.0)
        if h_resp.status_code == 200:
            pts = h_resp.json().get("data", [])
            for pt in pts:
                history_records.append({
                    "time": pt["time"],
                    "machine": m["name"],
                    "power_kw": pt["power_kw"],
                })
    except Exception:
        pass

if history_records:
    hdf = pd.DataFrame(history_records)
    hdf["time"] = pd.to_datetime(hdf["time"])
    fig_line = px.line(
        hdf,
        x="time",
        y="power_kw",
        color="machine",
        title="Active Power Draw (kW) by Machine",
        labels={"power_kw": "Power (kW)", "time": "Timestamp"},
    )
    fig_line.update_layout(height=400, hovermode="x unified")
    st.plotly_chart(fig_line, use_container_width=True)
else:
    st.info("Awaiting telemetry history to render time-series trendline.")

