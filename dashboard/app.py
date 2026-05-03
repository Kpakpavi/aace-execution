import os
from datetime import datetime

import requests
import streamlit as st

API_BASE_URL = os.environ.get("AACE_API_BASE_URL", "http://localhost:8000")


def format_timestamp(value):
    if not value:
        return "—"
    try:
        cleaned = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return str(value)


def format_score(value):
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return value


def fetch_opportunity_summary():
    try:
        response = requests.get(
            f"{API_BASE_URL}/analytics/opportunity-summary",
            headers={"X-API-Key": os.environ.get("AACE_API_KEY", "")},
            timeout=10,
        )
        response.raise_for_status()
        return response.json(), None
    except requests.RequestException as exc:
        return None, str(exc)


def fetch_top_products():
    try:
        response = requests.get(
            f"{API_BASE_URL}/analytics/top-products",
            headers={"X-API-Key": os.environ.get("AACE_API_KEY", "")},
            timeout=10,
        )
        response.raise_for_status()
        return response.json(), None
    except requests.RequestException as exc:
        return None, str(exc)


def fetch_alert_rate():
    try:
        response = requests.get(
            f"{API_BASE_URL}/analytics/alert-rate",
            headers={"X-API-Key": os.environ.get("AACE_API_KEY", "")},
            timeout=10,
        )
        response.raise_for_status()
        return response.json(), None
    except requests.RequestException as exc:
        return None, str(exc)


def fetch_high_score_opportunities(min_score=0.0):
    try:
        response = requests.get(
            f"{API_BASE_URL}/analytics/high-score-opportunities",
            headers={"X-API-Key": os.environ.get("AACE_API_KEY", "")},
            params={"min_score": min_score},
            timeout=10,
        )
        response.raise_for_status()
        return response.json(), None
    except requests.RequestException as exc:
        return None, str(exc)


def fetch_daily_opportunities():
    try:
        response = requests.get(
            f"{API_BASE_URL}/analytics/daily-opportunities",
            headers={"X-API-Key": os.environ.get("AACE_API_KEY", "")},
            timeout=10,
        )
        response.raise_for_status()
        return response.json(), None
    except requests.RequestException as exc:
        return None, str(exc)


st.set_page_config(page_title="AACE Dashboard", layout="wide")

st.title("AACE — Automated Deal Discovery Engine")
st.markdown(
    "*Real-time detection and ranking of arbitrage opportunities across sources*"
)
st.divider()

st.header("Opportunity Summary")
st.caption("High-level metrics across all detected opportunities.")

summary, error = fetch_opportunity_summary()
if error:
    st.error(f"Failed to load opportunity summary: {error}")
else:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Opportunities", summary["total_opportunities"])
    col2.metric("Alert Eligible", summary["alert_eligible"])
    col3.metric("No Alert", summary["no_alert"])
    col4.metric("Average Score", round(summary["average_score"], 2))

st.divider()

st.header("Top Products")
st.caption("Products generating the most opportunities.")

top_products, top_products_error = fetch_top_products()
if top_products_error:
    st.error(f"Failed to load top products: {top_products_error}")
else:
    rows = [
        {"product_id": item["product_id"], "opportunity_count": item["opportunity_count"]}
        for item in top_products
    ]
    st.table(rows)

st.divider()

st.header("Alert Rate")
st.caption("Share of opportunities that triggered an alert versus those that did not.")

alert_rate, alert_rate_error = fetch_alert_rate()
if alert_rate_error:
    st.error(f"Failed to load alert rate: {alert_rate_error}")
else:
    row1_col1, row1_col2, row1_col3 = st.columns(3)
    row1_col1.metric("Total Opportunities", alert_rate["total_opportunities"])
    row1_col2.metric("Alert Eligible", alert_rate["alert_eligible"])
    row1_col3.metric("No Alert", alert_rate["no_alert"])

    row2_col1, row2_col2 = st.columns(2)
    row2_col1.metric("Alert Rate", f"{alert_rate['alert_rate_percent']}%")
    row2_col2.metric("No Alert Rate", f"{alert_rate['no_alert_rate_percent']}%")

st.divider()

high_score, high_score_error = fetch_high_score_opportunities()
if high_score_error:
    st.error(f"Failed to load high-score opportunities: {high_score_error}")
else:
    st.header("🔥 Hot Deals")
    st.caption("Top 3 highest-scoring opportunities right now.")
    hot_deals = sorted(
        high_score,
        key=lambda x: x.get("score") or 0,
        reverse=True,
    )[:3]

    if hot_deals:
        hot_cols = st.columns(3)
        for col, item in zip(hot_cols, hot_deals):
            alert_decision = item.get("alert_decision")
            if alert_decision == "ALERT_ELIGIBLE":
                decision_color = "green"
            elif alert_decision == "NO_ALERT":
                decision_color = "red"
            else:
                decision_color = "gray"

            with col.container(border=True):
                st.markdown(f"## 🔥 {item.get('product_id')}")
                st.metric("Score", format_score(item.get("score")))
                st.markdown(
                    f"### :{decision_color}[{alert_decision}]"
                )
                st.caption(f"Timestamp: {format_timestamp(item.get('opportunity_timestamp'))}")

    st.write("")
    st.divider()

    st.header("High-Score Opportunities")
    st.caption("Browse, filter, and sort all opportunities above the score threshold.")

    filter_col1, filter_col2, filter_col3 = st.columns(3)
    with filter_col1:
        min_score = st.slider(
            "Minimum Score",
            min_value=0.0,
            max_value=100.0,
            value=0.0,
            step=0.5,
        )
    with filter_col2:
        unique_products = sorted(
            {item.get("product_id") for item in high_score if item.get("product_id")}
        )
        product_choice = st.selectbox(
            "Product",
            options=["All products"] + unique_products,
        )
    with filter_col3:
        sort_choice = st.selectbox(
            "Sort by",
            options=["Score: high to low", "Newest first", "Product ID"],
        )

    filtered = [
        item
        for item in high_score
        if (item.get("score") or 0) >= min_score
        and (product_choice == "All products" or item.get("product_id") == product_choice)
    ]

    if sort_choice == "Score: high to low":
        filtered.sort(key=lambda x: x.get("score") or 0, reverse=True)
    elif sort_choice == "Newest first":
        filtered.sort(key=lambda x: x.get("opportunity_timestamp") or "", reverse=True)
    elif sort_choice == "Product ID":
        filtered.sort(key=lambda x: x.get("product_id") or "")

    if not filtered:
        st.info("No opportunities match the selected filters.")
    else:
        for item in filtered:
            product_id = item.get("product_id")
            score = item.get("score")
            alert_decision = item.get("alert_decision")
            result_classification = item.get("result_classification")
            opportunity_timestamp = item.get("opportunity_timestamp")

            if alert_decision == "ALERT_ELIGIBLE":
                decision_color = "green"
            elif alert_decision == "NO_ALERT":
                decision_color = "red"
            else:
                decision_color = "gray"

            with st.expander(f"Product: {product_id}"):
                with st.container(border=True):
                    st.subheader(f"Product: {product_id}")
                    col1, col2 = st.columns(2)
                    col1.metric("Score", format_score(score))
                    col2.markdown(
                        f"**Alert Decision:** :{decision_color}[{alert_decision}]"
                    )
                    st.markdown(f"**Result Classification:** {result_classification}")
                    st.caption(f"Timestamp: {format_timestamp(opportunity_timestamp)}")

                st.markdown("### Raw Data")
                st.json(item)
            st.write("")

st.divider()

st.header("Daily Opportunities")
st.caption("Daily volume of opportunities and alert outcomes over time.")

daily, daily_error = fetch_daily_opportunities()
if daily_error:
    st.error(f"Failed to load daily opportunities: {daily_error}")
else:
    rows = [
        {
            "day": item.get("day"),
            "opportunity_count": item.get("opportunity_count"),
            "alert_eligible_count": item.get("alert_eligible_count"),
            "no_alert_count": item.get("no_alert_count"),
        }
        for item in daily
    ]
    chart_data = {
        "day": [r["day"] for r in rows],
        "opportunity_count": [r["opportunity_count"] for r in rows],
        "alert_eligible_count": [r["alert_eligible_count"] for r in rows],
        "no_alert_count": [r["no_alert_count"] for r in rows],
    }
    st.line_chart(
        chart_data,
        x="day",
        y=["opportunity_count", "alert_eligible_count", "no_alert_count"],
    )
    st.table(rows)