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

# ---------------------------------------------------------------------------
# Live worker output (v0.1.0 scheduled worker)
# ---------------------------------------------------------------------------


def fetch_worker_opportunities(limit: int = 25, platform: str | None = None):
    try:
        params: dict[str, object] = {"limit": limit}
        if platform:
            params["platform"] = platform
        response = requests.get(
            f"{API_BASE_URL}/worker-opportunities",
            params=params,
            headers={"X-API-Key": os.environ.get("AACE_API_KEY", "")},
            timeout=10,
        )
        response.raise_for_status()
        return response.json(), None
    except requests.RequestException as exc:
        return None, str(exc)


# ---------------------------------------------------------------------------
# Resale platform fees + shipping estimate (used by Best Profit panel below)
# ---------------------------------------------------------------------------

# Headline fee = combined seller fee (referral + payment processing) as a
# percentage of the final sale price. Numbers based on each platform's
# published 2026 standard seller terms.
PLATFORM_FEES = {
    "eBay": 0.1325,                       # 13.25% final value fee
    "Amazon": 0.15,                       # ~15% referral fee (varies by category)
    "StockX": 0.125,                      # 9.5% transaction + 3% payment
    "Mercari": 0.129,                     # 10% seller + 2.9% payment
    "FB Marketplace (National)": 0.05,    # 5% shipping orders
    "FB Marketplace (Local)": 0.0,        # 0% local pickup
}
DEFAULT_SHIPPING_ESTIMATE = 8.0           # Flat $8 — typical small parcel rate


def calc_profit(buy_price: float, resale_price: float, platform: str, shipping: float):
    """Net profit + ROI after marketplace fees and shipping."""
    fee_rate = PLATFORM_FEES.get(platform, 0.0)
    fee = round(resale_price * fee_rate, 2)
    net = round(resale_price - buy_price - fee - shipping, 2)
    roi = round((net / buy_price) * 100, 1) if buy_price > 0 else 0.0
    return fee, net, roi


# ---------------------------------------------------------------------------
# Best Profit — rank cross-source matches by net profit after fees
# ---------------------------------------------------------------------------

st.header("Best Profit Opportunities")
st.caption(
    "Cross-source matches ranked by net profit after marketplace fees and "
    "shipping. Best margin first. Adjust the platform and shipping estimate "
    "to model different resale strategies."
)

col_a, col_b = st.columns([2, 1])
with col_a:
    selected_platform = st.selectbox(
        "Resale platform",
        options=list(PLATFORM_FEES.keys()),
        index=0,  # eBay
    )
with col_b:
    shipping_estimate = st.number_input(
        "Shipping estimate ($)",
        min_value=0.0, max_value=200.0,
        value=DEFAULT_SHIPPING_ESTIMATE, step=1.0,
    )

# Pass the selected platform so the API enriches each row with a
# resale-comp lookup (Keepa for Amazon, SerpAPI for others, with a
# deterministic mock fallback while real API keys are being provisioned).
worker_opps, worker_err = fetch_worker_opportunities(
    limit=100, platform=selected_platform
)
if worker_err:
    st.error(f"Failed to load worker opportunities: {worker_err}")
elif not worker_opps:
    st.info(
        "No worker opportunities yet. Once the worker ships its first deal, "
        "it'll appear here ranked by net profit."
    )
else:
    rows = []
    # Track which comp source was used so we can show a banner about
    # whether we're on real or mocked resale data.
    comp_sources: set[str] = set()
    for opp in worker_opps:
        buy_price = float(opp.get("min_price") or 0)

        # Prefer the real resale-comp avg when the API returned one;
        # fall back to the legacy max_price proxy so the dashboard keeps
        # working if the comps client is unavailable.
        resale_avg = opp.get("resale_avg")
        if resale_avg is not None:
            resale_price = float(resale_avg)
            comp_source = opp.get("resale_source") or "?"
        else:
            resale_price = float(opp.get("max_price") or 0)
            comp_source = "proxy"
        comp_sources.add(comp_source)

        fee, net, roi = calc_profit(
            buy_price, resale_price, selected_platform, shipping_estimate
        )
        # Detection count: how many times the worker has re-found this
        # same deal across ticks. High values mean it's persistent —
        # worth acting on. The API returns the latest snapshot per
        # opportunity_id so each row here is already deduped.
        detections = opp.get("detections")
        try:
            detections_n = int(detections) if detections is not None else 1
        except (TypeError, ValueError):
            detections_n = 1
        rows.append({
            "Product": opp.get("product_key", ""),
            "Sources": opp.get("sources", ""),
            "Buy $": round(buy_price, 2),
            "Resale $": round(resale_price, 2),
            "Comp": comp_source,
            "Fee $": fee,
            "Ship $": round(shipping_estimate, 2),
            "Net Profit $": net,
            "ROI %": roi,
            "Seen": detections_n,
            "Detected": format_timestamp(opp.get("detected_at")),
            "Webhook": opp.get("delivery_status", ""),
        })
    rows.sort(key=lambda r: r["Net Profit $"], reverse=True)

    total_count = len(rows)
    profitable_total = sum(1 for r in rows if r["Net Profit $"] > 0)
    st.success(
        f"{total_count} opportunities · {profitable_total} profitable on "
        f"{selected_platform} after fees + ${shipping_estimate:.0f} shipping"
    )

    # Tell the operator what the resale prices are based on. Today most
    # rows use mock comps; once Keepa/SerpAPI keys land, the source label
    # will read "keepa" or "serpapi" instead.
    if comp_sources:
        readable = ", ".join(sorted(comp_sources))
        if comp_sources == {"proxy"}:
            st.caption(
                "Resale prices are using the legacy ``max_price`` proxy "
                "(highest observed source price). Add a Keepa or SerpAPI "
                "key to surface real sold-comp data."
            )
        elif "mock" in comp_sources and len(comp_sources) == 1:
            st.caption(
                "Resale prices are mocked sold-comp data (deterministic). "
                "Swap to real comps by configuring Keepa (Amazon) or "
                "SerpAPI (other platforms) credentials in the API service."
            )
        else:
            st.caption(f"Resale price sources in this view: {readable}.")

    # ----- Operator filters -------------------------------------------
    # Four controls in a single row so the table stays the focal point:
    #   1. Profitable-only toggle (defaults ON — operators almost always
    #      want this; loss-making rows are useful only when stress-testing
    #      the fee model)
    #   2. Min ROI % slider (0..200) — filter by margin %
    #   3. Min Net Profit $ — dollar-amount floor
    #   4. Product search — case-insensitive substring on Product column
    f_col1, f_col2, f_col3, f_col4 = st.columns([1, 1.4, 1.4, 2])
    with f_col1:
        profitable_only = st.toggle(
            "Profitable only",
            value=True,
            help="Hide opportunities with negative or zero net profit",
        )
    with f_col2:
        min_roi = st.slider(
            "Min ROI %", min_value=0, max_value=200, value=0, step=5,
            help="Hide rows below this ROI floor",
        )
    with f_col3:
        min_net = st.number_input(
            "Min Net Profit $",
            min_value=0.0, max_value=10_000.0,
            value=0.0, step=1.0,
            help="Hide rows below this absolute profit floor",
        )
    with f_col4:
        search_term = st.text_input(
            "Search product",
            value="",
            placeholder="e.g. watch, tv, vacuum, headphones",
            help="Case-insensitive match against the Product column",
        )

    # Apply filters in declaration order. Each filter narrows the set.
    filtered_rows = rows
    if profitable_only:
        filtered_rows = [r for r in filtered_rows if r["Net Profit $"] > 0]
    if min_roi > 0:
        filtered_rows = [r for r in filtered_rows if r["ROI %"] >= min_roi]
    if min_net > 0:
        filtered_rows = [r for r in filtered_rows if r["Net Profit $"] >= min_net]
    if search_term.strip():
        needle = search_term.strip().lower()
        filtered_rows = [
            r for r in filtered_rows if needle in str(r["Product"]).lower()
        ]

    # Tell the operator how many rows survived the filter — quickly
    # tells them "your floor is too tight" if everything disappears.
    if len(filtered_rows) != total_count:
        st.caption(
            f"Showing **{len(filtered_rows)}** of {total_count} after filters."
        )

    st.dataframe(
        filtered_rows,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Net Profit $": st.column_config.NumberColumn(
                "Net Profit $",
                format="$%.2f",
                help="Resale price − Buy price − Marketplace fee − Shipping",
            ),
            "ROI %": st.column_config.NumberColumn(
                "ROI %",
                format="%.1f%%",
                help="Net profit as a percentage of buy price",
            ),
            "Buy $": st.column_config.NumberColumn("Buy $", format="$%.2f"),
            "Resale $": st.column_config.NumberColumn(
                "Resale $",
                format="$%.2f",
                help=(
                    "Estimated resale price on the selected platform. "
                    "Sourced from the resale-comps client (Keepa / SerpAPI / "
                    "mock) when available, otherwise the legacy max_price "
                    "proxy."
                ),
            ),
            "Comp": st.column_config.TextColumn(
                "Comp",
                help=(
                    "Where the resale price came from: keepa (real Amazon "
                    "sold history), serpapi (Google Shopping snapshot), "
                    "mock (deterministic stand-in), or proxy (max observed "
                    "source price)."
                ),
            ),
            "Fee $": st.column_config.NumberColumn("Fee $", format="$%.2f"),
            "Ship $": st.column_config.NumberColumn("Ship $", format="$%.2f"),
            "Seen": st.column_config.NumberColumn(
                "Seen",
                format="%d×",
                help=(
                    "How many times the worker has re-found this same "
                    "deal across ticks. High values mean the deal is "
                    "persistent — worth acting on. Each row here is "
                    "deduped to one entry per opportunity."
                ),
            ),
        },
    )

    # CSV export — uses the currently-filtered rows, not the full table,
    # so the operator gets exactly what they're looking at.
    if filtered_rows:
        import csv
        import io

        csv_buffer = io.StringIO()
        writer = csv.DictWriter(csv_buffer, fieldnames=list(filtered_rows[0].keys()))
        writer.writeheader()
        writer.writerows(filtered_rows)
        csv_bytes = csv_buffer.getvalue().encode("utf-8")

        # Filename includes platform + UTC timestamp so multiple exports
        # don't clobber each other in the operator's Downloads folder.
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        platform_slug = (
            selected_platform.lower()
            .replace(" ", "_")
            .replace("(", "")
            .replace(")", "")
        )
        st.download_button(
            label=f"⬇ Download {len(filtered_rows)} rows as CSV",
            data=csv_bytes,
            file_name=f"aace_opportunities_{platform_slug}_{ts}.csv",
            mime="text/csv",
            help="Exports exactly the rows currently visible above",
        )
st.divider()

# ---------------------------------------------------------------------------
# Legacy panels (Opportunity Summary, Top Products, Alert Rate, Hot Deals,
# High-Score Opportunities, Daily Opportunities) were hidden on 2026-06-08
# as part of the reseller-profit pivot. They read from the old 6-stage
# pipeline tables and show empty data under the v0.1 worker.
#
# Fetch helpers above (fetch_opportunity_summary, fetch_top_products,
# fetch_alert_rate, fetch_high_score_opportunities, fetch_daily_opportunities)
# are kept defined so the panels can be rewired against worker_opportunities
# data in Sprint 4 (Platform Expansion).
# ---------------------------------------------------------------------------

st.caption(
    "More analytics panels (daily trends, top products, score distribution) "
    "are coming in Sprint 4 once we have richer historical data."
)