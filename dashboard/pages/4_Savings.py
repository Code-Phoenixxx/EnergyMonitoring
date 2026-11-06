"""Page 4: Savings - Ranked energy recommendations, rupee savings, and CO2 reduction."""

import os
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")

st.title("💰 Energy & Cost Savings Recommendations")
st.caption("Actionable Industry 4.0 recommendations synthesized from waste events and load shifting.")

try:
    recs_resp = requests.get(f"{API_URL}/recommendations", timeout=3.0)
    recs_data = recs_resp.json() if recs_resp.status_code == 200 else []
except Exception as e:
    recs_data = []
    st.error(f"Cannot load recommendations: {e}")

if recs_data:
    rdf = pd.DataFrame(recs_data)

    total_inr = rdf["estimated_monthly_inr_saved"].sum()
    total_kwh = rdf["estimated_monthly_kwh_saved"].sum()
    total_co2 = rdf["co2_avoided_kg"].sum()

    # Top Savings Summary Cards
    sc1, sc2, sc3 = st.columns(3)
    sc1.metric("Total Monthly Savings Potential", f"₹ {total_inr:,.2f}", delta="Annual: ₹ {:,.0f}".format(total_inr * 12))
    sc2.metric("Monthly Energy Reductions", f"{total_kwh:,.1f} kWh", delta="Annual: {:,.0f} kWh".format(total_kwh * 12))
    sc3.metric("Avoided Carbon Emissions", f"{total_co2:,.1f} kg CO₂", delta="Annual: {:,.1f} t CO₂".format(total_co2 * 12 / 1000.0))

    st.divider()

    # Visual Breakdown of Savings by Action
    st.subheader("Financial Savings Breakdown by Machine")
    fig_bar = px.bar(
        rdf,
        x="machine_id",
        y="estimated_monthly_inr_saved",
        color="priority_rank",
        text_auto=".2s",
        title="Monthly Rupee (₹) Savings by Equipment",
        labels={"estimated_monthly_inr_saved": "Estimated ₹ / Month", "machine_id": "Machine", "priority_rank": "Priority"},
        color_continuous_scale="Teal",
    )
    fig_bar.update_layout(height=350)
    st.plotly_chart(fig_bar, use_container_width=True)

    st.divider()

    # Ranked Recommendations Cards
    st.subheader("📋 Prioritized Action Items")

    for _, row in rdf.sort_values("priority_rank").iterrows():
        p_color = "#dc3545" if row["priority_rank"] == 1 else ("#fd7e14" if row["priority_rank"] == 2 else "#0d6efd")
        st.markdown(f"""
        <div style="border: 1px solid #dee2e6; border-left: 6px solid {p_color}; border-radius: 6px; padding: 16px; margin-bottom: 12px; background-color: #ffffff;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <h4 style="margin: 0; color: #212529;">Priority {row['priority_rank']}: <b>{row['machine_id'].upper()}</b></h4>
                <span style="background-color: {p_color}22; color: {p_color}; font-weight: bold; padding: 4px 10px; border-radius: 4px;">
                    ₹ {row['estimated_monthly_inr_saved']:,.2f} / mo
                </span>
            </div>
            <p style="margin: 8px 0; color: #495057; font-size: 15px;">{row['action']}</p>
            <div style="font-size: 13px; color: #6c757d;">
                ⚡ <b>{row['estimated_monthly_kwh_saved']:,.1f} kWh/mo</b> saved &nbsp;|&nbsp; 
                🌱 <b>{row['co2_avoided_kg']:,.1f} kg CO₂/mo</b> avoided &nbsp;|&nbsp; 
                Status: <span style="color: #198754; font-weight: bold;">{row['status']}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
else:
    st.info("No recommendations synthesized yet.")

