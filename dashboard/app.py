"""Streamlit multi-page dashboard application entrypoint."""

import os
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")

st.set_page_config(
    page_title="Smart Energy Monitoring | Industry 4.0",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling
st.markdown("""
<style>
    .metric-card {
        background-color: #f8f9fa;
        border-radius: 8px;
        padding: 15px;
        border-left: 5px solid #0d6efd;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .status-running { color: #198754; font-weight: bold; }
    .status-idle { color: #ffc107; font-weight: bold; }
    .status-fault { color: #dc3545; font-weight: bold; }
    .status-off { color: #6c757d; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

st.sidebar.title("⚡ IIoT Energy Hub")
st.sidebar.caption("Smart Industrial Energy Monitoring System | Industry 4.0")

# Fetch high-level summary
try:
    summary_resp = requests.get(f"{API_URL}/summary", timeout=2.0)
    if summary_resp.status_code == 200:
        summary = summary_resp.json()
        st.sidebar.metric("Plant Active Load", f"{summary['current_plant_kw']:.1f} kW")
        st.sidebar.metric("Today's Consumption", f"{summary['todays_kwh']:.1f} kWh")
        st.sidebar.metric("Today's Cost", f"₹ {summary['todays_cost_inr']:,.2f}")
        st.sidebar.metric("Carbon Footprint", f"{summary['todays_co2_kg']:.1f} kg CO₂")
    else:
        st.sidebar.warning("API connection established, awaiting telemetry.")
except Exception:
    st.sidebar.info("API offline (start backend at http://localhost:8000)")

st.title("🏭 Smart Industrial Energy Monitoring System")
st.markdown("""
Welcome to the **Virtual Factory Energy Operations Center**. This Industry 4.0 platform monitors real-time 
machine electrical telemetry over MQTT, analyzes energy wastage (idle draw, demand peaks, anomalies), 
and uses machine learning (LightGBM & Isolation Forest) to optimize operations, reduce costs (₹), 
and eliminate carbon emissions ($\text{CO}_2$).
""")

st.info("👈 Select a page from the sidebar to inspect Live Telemetry, Energy Wastage, Demand Forecasts, or Cost Savings.")

