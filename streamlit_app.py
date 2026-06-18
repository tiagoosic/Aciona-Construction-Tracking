from pathlib import Path

import base64
import altair as alt
import pandas as pd
import requests
import streamlit as st


BASE_DIR = Path(__file__).resolve().parent
LOGO_FILE = BASE_DIR / "assets" / "aciona_logo.svg"

PROJECTED_FILES = [
    BASE_DIR / "ipp_phase_1_projected_development_curve_hard_cost.csv",
    BASE_DIR / "ips_phase_1_projected_development_curve_hard_cost.csv",
    BASE_DIR / "isd_projected_development_curve_hard_cost.csv",
]

ACTUAL_FILES = [
    BASE_DIR / "ipp_phase_1_development_tracking_hard_cost_actual.csv",
    BASE_DIR / "isd_development_tracking_hard_cost_actual.csv",
]

HELMS_PROJECTED_FILE = BASE_DIR / "helms_projected_draw_schedule_summary.csv"
BASEROW_API_BASE = "https://api.baserow.io/api"
BASEROW_API_TOKEN_DEFAULT = ""
BASEROW_PROJECTED_TABLE_ID_DEFAULT = "1019681"
BASEROW_TRACKING_TABLE_ID_DEFAULT = "1019637"
BASEROW_CONTINGENCY_TABLE_ID_DEFAULT = "1035197"

BRAND_EBONY = "#3D3533"
BRAND_GOLD = "#CC9955"
BRAND_IVORY = "#F1E8D5"
BRAND_GRAPHITE = "#353535"
BRAND_TERRA = "#82613F"
BRAND_TERRA_SOFT = "#B79A78"
BRAND_PROJECTED_GRAY = "#9CA3AF"
BRAND_GRID = "#E5DCCB"
BRAND_BG = "#FBF8F1"
CONTINGENCY_MULTI_PALETTE = [
    "#5B8FD9",
    "#58B982",
    "#9B7AE5",
    "#D89A45",
    "#D96B6B",
    "#4EB8AD",
]
PROJECT_COLOR_PAIRS = [
    ("#1D4ED8", "#93C5FD"),
    ("#047857", "#86EFAC"),
    ("#7C3AED", "#C4B5FD"),
    ("#B45309", "#FDBA74"),
    ("#BE123C", "#FDA4AF"),
    ("#0F766E", "#99F6E4"),
]


st.set_page_config(
    page_title="Construction Tracking",
    page_icon="",
    layout="wide",
)


def to_number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str).str.replace(",", "", regex=False).str.replace("%", "", regex=False),
        errors="coerce",
    )


def parse_date(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce")


@st.cache_data
def load_projected() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in PROJECTED_FILES:
        if not path.exists():
            continue
        df = pd.read_csv(path)
        df = df.rename(columns={"Month": "Month"})
        frames.append(
            pd.DataFrame(
                {
                    "Project": df["Project"].astype(str),
                    "Month": parse_date(df["Month"]),
                    "Phase": df.get("Phase", "Construction"),
                    "Projected Monthly Hard Cost": to_number(df["Projected Monthly Hard Cost"]),
                    "Projected Cumulative Hard Cost": to_number(df["Projected Cumulative Hard Cost"]),
                    "Projected Monthly Completion %": to_number(df["Projected Monthly Completion %"]),
                    "Projected Cumulative Completion %": to_number(df["Projected Cumulative Completion %"]),
                    "Projected Completion Date": parse_date(df["Projected Completion Date"]),
                    "Source": path.name,
                }
            )
        )

    if HELMS_PROJECTED_FILE.exists():
        df = pd.read_csv(HELMS_PROJECTED_FILE)
        hard = to_number(df["Projected Hard Costs"])
        cumulative_hard = hard.cumsum()
        total_hard = cumulative_hard.max()
        completion_date = parse_date(df["Month"]).max()
        frames.append(
            pd.DataFrame(
                {
                    "Project": "Helms",
                    "Month": parse_date(df["Month"]),
                    "Phase": df.get("Phase", "Construction").fillna(""),
                    "Projected Monthly Hard Cost": hard,
                    "Projected Cumulative Hard Cost": cumulative_hard,
                    "Projected Monthly Completion %": (hard / total_hard * 100).round(2)
                    if total_hard
                    else 0,
                    "Projected Cumulative Completion %": (cumulative_hard / total_hard * 100).round(2)
                    if total_hard
                    else 0,
                    "Projected Completion Date": completion_date,
                    "Source": HELMS_PROJECTED_FILE.name,
                }
            )
        )

    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out = out.dropna(subset=["Month"]).sort_values(["Project", "Month"])
    out["Period"] = out["Month"].dt.to_period("M").astype(str)
    return out


@st.cache_data
def load_actual() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in ACTUAL_FILES:
        if not path.exists():
            continue
        df = pd.read_csv(path)
        frames.append(
            pd.DataFrame(
                {
                    "Record Name": df.get("Record Name", ""),
                    "Project": df["Project"].astype(str),
                    "Report Month": parse_date(df["Report Month"]),
                    "Monthly Hard Cost": to_number(df["Monthly Hard Cost"]),
                    "Cumulative Hard Cost": to_number(df["Cumulative Hard Cost"]),
                    "Monthly Completion %": to_number(df["Monthly Completion %"]),
                    "Cumulative Completion %": to_number(df["Cumulative Completion %"]),
                    "Forecast Completion Date": parse_date(df["Forecast Completion Date"]),
                    "Source": path.name,
                }
            )
        )

    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out = out.dropna(subset=["Report Month"]).sort_values(["Project", "Report Month"])
    out["Period"] = out["Report Month"].dt.to_period("M").astype(str)
    return out


def get_secret(name: str, default: str = "") -> str:
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def require_password() -> None:
    password = get_secret("DASHBOARD_PASSWORD", "")
    if not password:
        return

    if st.session_state.get("authenticated"):
        return

    st.title("Construction Tracking")
    entered = st.text_input("Password", type="password")
    if entered == password:
        st.session_state["authenticated"] = True
        st.rerun()
    elif entered:
        st.error("Invalid password.")
    st.stop()


def fetch_baserow_rows(token: str, table_id: str, api_base: str = BASEROW_API_BASE) -> list[dict]:
    if not token or not table_id:
        return []

    rows: list[dict] = []
    url = f"{api_base.rstrip('/')}/database/rows/table/{table_id}/"
    params = {"user_field_names": "true", "size": 200}
    headers = {"Authorization": f"Token {token}"}

    while url:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        rows.extend(payload.get("results", []))
        url = payload.get("next")
        params = None

    return rows


def link_value(value):
    if isinstance(value, list):
        if not value:
            return ""
        first = value[0]
        if isinstance(first, dict):
            return str(first.get("value") or first.get("name") or first.get("id") or "")
        return str(first)
    if isinstance(value, dict):
        return str(value.get("value") or value.get("name") or value.get("id") or "")
    return value


def baserow_rows_to_projected(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    required = [
        "Project",
        "Month",
        "Phase",
        "Projected Monthly Hard Cost",
        "Projected Cumulative Hard Cost",
        "Projected Monthly Completion %",
        "Projected Cumulative Completion %",
        "Projected Completion Date",
        "Curve Month No",
    ]
    for col in required:
        if col not in df:
            df[col] = pd.NA
    out = pd.DataFrame(
        {
            "Project": df["Project"].map(link_value).astype(str),
            "Month": parse_date(df["Month"]),
            "Phase": df["Phase"].map(link_value).astype(str),
            "Projected Monthly Hard Cost": to_number(df["Projected Monthly Hard Cost"]),
            "Projected Cumulative Hard Cost": to_number(df["Projected Cumulative Hard Cost"]),
            "Projected Monthly Completion %": to_number(df["Projected Monthly Completion %"]),
            "Projected Cumulative Completion %": to_number(df["Projected Cumulative Completion %"]),
            "Projected Completion Date": parse_date(df["Projected Completion Date"]),
            "Curve Month No": to_number(df["Curve Month No"]),
            "Source": "Baserow",
        }
    )
    out = out.dropna(subset=["Month"]).sort_values(["Project", "Month"])
    out["Period"] = out["Month"].dt.to_period("M").astype(str)
    return out


def baserow_rows_to_actual(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    required = [
        "Record Name",
        "Project",
        "Report Month",
        "Monthly Hard Cost",
        "Cumulative Hard Cost",
        "Monthly Completion %",
        "Cumulative Completion %",
        "Forecast Completion Date",
        "Actual Month No",
    ]
    for col in required:
        if col not in df:
            df[col] = pd.NA
    out = pd.DataFrame(
        {
            "Record Name": df["Record Name"].fillna("").astype(str),
            "Project": df["Project"].map(link_value).astype(str),
            "Report Month": parse_date(df["Report Month"]),
            "Monthly Hard Cost": to_number(df["Monthly Hard Cost"]),
            "Cumulative Hard Cost": to_number(df["Cumulative Hard Cost"]),
            "Monthly Completion %": to_number(df["Monthly Completion %"]),
            "Cumulative Completion %": to_number(df["Cumulative Completion %"]),
            "Forecast Completion Date": parse_date(df["Forecast Completion Date"]),
            "Actual Month No": to_number(df["Actual Month No"]),
            "Source": "Baserow",
        }
    )
    out = out.dropna(subset=["Report Month"]).sort_values(["Project", "Report Month"])
    out["Period"] = out["Report Month"].dt.to_period("M").astype(str)
    return out


def baserow_rows_to_contingency(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    required = [
        "Name",
        "Project",
        "Project Text",
        "Report Date",
        "Report Month",
        "Draw Number",
        "Original Contingency",
        "Current Contingency",
        "Monthly Contingency Change",
        "Total Reallocated",
        "Contingency Drawn To Date",
        "Remaining Contingency",
    ]
    for col in required:
        if col not in df:
            df[col] = pd.NA

    project = df["Project"].map(link_value).astype(str)
    project_text = df["Project Text"].fillna("").astype(str)
    project = project.where(project.str.strip() != "", project_text)
    project = project.where(project.str.strip() != "", df["Name"].fillna("").astype(str).str.split(" - ").str[0])

    out = pd.DataFrame(
        {
            "Name": df["Name"].fillna("").astype(str),
            "Project": project,
            "Report Date": parse_date(df["Report Date"]),
            "Report Month Label": df["Report Month"].fillna("").astype(str),
            "Draw Number": to_number(df["Draw Number"]),
            "Original Contingency": to_number(df["Original Contingency"]),
            "Current Contingency": to_number(df["Current Contingency"]),
            "Monthly Contingency Change": to_number(df["Monthly Contingency Change"]),
            "Total Reallocated": to_number(df["Total Reallocated"]),
            "Contingency Drawn To Date": to_number(df["Contingency Drawn To Date"]),
            "Remaining Contingency": to_number(df["Remaining Contingency"]),
            "Source": "Baserow",
        }
    )
    out = out.dropna(subset=["Report Date"]).sort_values(["Project", "Report Date"])
    out["Period"] = out["Report Date"].dt.to_period("M").astype(str)
    return out


def load_baserow_data(
    token: str,
    projected_table_id: str,
    tracking_table_id: str,
    contingency_table_id: str,
    api_base: str,
):
    projected_rows = fetch_baserow_rows(token, projected_table_id, api_base)
    actual_rows = fetch_baserow_rows(token, tracking_table_id, api_base)
    contingency_rows = fetch_baserow_rows(token, contingency_table_id, api_base)
    return (
        baserow_rows_to_projected(projected_rows),
        baserow_rows_to_actual(actual_rows),
        baserow_rows_to_contingency(contingency_rows),
    )


def normalize_projected_completion_month(projected: pd.DataFrame) -> pd.DataFrame:
    if projected.empty:
        return projected
    required = {"Month", "Projected Completion Date", "Projected Cumulative Completion %"}
    if not required.issubset(projected.columns):
        return projected

    out = projected.copy()
    mask = (
        out["Projected Completion Date"].notna()
        & (out["Month"] > out["Projected Completion Date"])
        & (out["Projected Cumulative Completion %"] >= 100)
    )
    out.loc[mask, "Month"] = out.loc[mask, "Projected Completion Date"]
    out = out.sort_values(["Project", "Month"])
    out["Period"] = out["Month"].dt.to_period("M").astype(str)
    return out


def trim_after_completion(
    df: pd.DataFrame,
    project_col: str,
    date_col: str,
    cumulative_pct_col: str,
    monthly_col: str | None = None,
) -> pd.DataFrame:
    if df.empty or cumulative_pct_col not in df:
        return df

    frames: list[pd.DataFrame] = []
    for _, group in df.sort_values([project_col, date_col]).groupby(project_col, dropna=False):
        if monthly_col and monthly_col in group:
            positive_monthly = group[group[monthly_col].fillna(0) > 0]
            if not positive_monthly.empty:
                last_positive_date = positive_monthly[date_col].iloc[-1]
                frames.append(group[group[date_col] <= last_positive_date])
                continue

        completed = group[group[cumulative_pct_col] >= 100]
        if completed.empty:
            frames.append(group)
            continue
        first_complete_date = completed[date_col].iloc[0]
        frames.append(group[group[date_col] <= first_complete_date])

    if not frames:
        return df
    return pd.concat(frames, ignore_index=True)


def add_month_number(df: pd.DataFrame, project_col: str, date_col: str, output_col: str) -> pd.DataFrame:
    if df.empty:
        return df

    out = df.copy()
    if output_col not in out:
        out[output_col] = pd.NA

    computed = (
        out.sort_values([project_col, date_col])
        .groupby(project_col, dropna=False)
        .cumcount()
        + 1
    )
    out[output_col] = pd.to_numeric(out[output_col], errors="coerce").fillna(computed).astype(int)
    return out


def money(value: float | int | None) -> str:
    if pd.isna(value):
        return "-"
    return f"US$ {value:,.0f}"


def money_mm(value: float | int | None) -> str:
    if pd.isna(value):
        return "-"
    formatted = f"{value / 1_000_000:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"US$ {formatted}MM"


def signed_money_mm(value: float | int | None) -> str:
    if pd.isna(value):
        return "-"
    sign = "+" if value >= 0 else "-"
    formatted = f"{abs(value) / 1_000_000:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{sign}US$ {formatted}MM"


def signed_money(value: float | int | None) -> str:
    if pd.isna(value):
        return "-"
    sign = "+" if value >= 0 else "-"
    return f"{sign}US$ {abs(value):,.0f}"


def compact_signed_money(value: float | int | None) -> str:
    if pd.isna(value):
        return ""
    sign = "+" if value >= 0 else "-"
    absolute = abs(float(value))
    if absolute >= 1_000_000:
        formatted = f"{absolute / 1_000_000:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{sign}US$ {formatted}MM"
    if absolute >= 1_000:
        return f"{sign}US$ {absolute / 1_000:,.0f}K"
    return f"{sign}US$ {absolute:,.0f}"


def pct(value: float | int | None) -> str:
    if pd.isna(value):
        return "-"
    return f"{value:.1f}%"


def signed_pct(value: float | int | None) -> str:
    if pd.isna(value):
        return "-"
    rounded = round(float(value), 1)
    if rounded.is_integer():
        return f"{rounded:+.0f}%"
    return f"{rounded:+.1f}%"


def month_count(start, end) -> str:
    if pd.isna(start) or pd.isna(end):
        return "-"
    start = pd.to_datetime(start)
    end = pd.to_datetime(end)
    months = (end.year - start.year) * 12 + (end.month - start.month) + 1
    return f"{months:.0f}"


def date_label(value) -> str:
    if pd.isna(value):
        return "-"
    return pd.to_datetime(value).strftime("%b/%y")


def asset_data_uri(path: Path) -> str:
    if not path.exists():
        return ""
    mime = "image/svg+xml" if path.suffix.lower() == ".svg" else "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def metric_pair_html(title: str, left_label: str, left_value: str, right_label: str, right_value: str) -> str:
    return f"""
    <div class="metric-card">
      <div class="metric-title">{title}</div>
      <div class="metric-grid">
        <div>
          <div class="metric-label">{left_label}</div>
          <div class="metric-value">{left_value}</div>
        </div>
        <div>
          <div class="metric-label">{right_label}</div>
          <div class="metric-value">{right_value}</div>
        </div>
      </div>
    </div>
    """


def metric_trio_html(
    title: str,
    first_label: str,
    first_value: str,
    second_label: str,
    second_value: str,
    third_label: str,
    third_value: str,
) -> str:
    return f"""
    <div class="metric-card">
      <div class="metric-title">{title}</div>
      <div class="metric-grid metric-grid-3">
        <div>
          <div class="metric-label">{first_label}</div>
          <div class="metric-value">{first_value}</div>
        </div>
        <div>
          <div class="metric-label">{second_label}</div>
          <div class="metric-value">{second_value}</div>
        </div>
        <div>
          <div class="metric-label">{third_label}</div>
          <div class="metric-value">{third_value}</div>
        </div>
      </div>
    </div>
    """


def mm_axis(title: str = "US$") -> alt.Axis:
    return alt.Axis(title=title, labelExpr="datum.value == 0 ? '0' : format(datum.value / 1000000, '.0f') + 'MM'")


def compact_usd_axis(title: str = "US$") -> alt.Axis:
    return alt.Axis(
        title=title,
        labelExpr=(
            "datum.value == 0 ? '0' : "
            "abs(datum.value) >= 1000000 ? format(datum.value / 1000000, '.1f') + 'MM' : "
            "format(datum.value / 1000, '.0f') + 'K'"
        ),
    )


def project_color_map(projects: list[str]) -> tuple[list[str], list[str]]:
    domain: list[str] = []
    colors: list[str] = []
    for index, project in enumerate(projects):
        actual_color, projected_color = PROJECT_COLOR_PAIRS[index % len(PROJECT_COLOR_PAIRS)]
        domain.extend([f"{project} - Actual", f"{project} - Projected"])
        colors.extend([actual_color, projected_color])
    return domain, colors


def contingency_color_scale(projects: list[str]) -> alt.Scale:
    palette = [BRAND_EBONY] if len(projects) <= 1 else CONTINGENCY_MULTI_PALETTE
    return alt.Scale(domain=projects, range=[palette[index % len(palette)] for index in range(len(projects))])


def line_chart(df: pd.DataFrame, y_field: str, title: str, y_title: str) -> alt.Chart:
    return (
        alt.Chart(df)
        .mark_line(point=True, strokeWidth=3)
        .encode(
            x=alt.X("Date:T", title="Month"),
            y=alt.Y(f"{y_field}:Q", title=y_title),
            color=alt.Color(
                "Series:N",
                title="",
                scale=alt.Scale(
                    domain=["Actual", "Projected"],
                    range=[BRAND_EBONY, BRAND_GOLD],
                ),
            ),
            tooltip=[
                alt.Tooltip("Date:T", title="Month", format="%b %Y"),
                alt.Tooltip("Series:N"),
                alt.Tooltip(f"{y_field}:Q", title=y_title, format=",.2f"),
            ],
        )
        .properties(height=320, title=title)
        .configure_axis(labelColor=BRAND_GRAPHITE, titleColor=BRAND_GRAPHITE, gridColor=BRAND_GRID)
        .configure_legend(labelColor=BRAND_GRAPHITE, titleColor=BRAND_GRAPHITE)
    )


def add_elapsed_month(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["Date"] = parse_date(out["Date"])
    if "MonthNo" in out and out["MonthNo"].notna().any():
        out["Month No"] = pd.to_numeric(out["MonthNo"], errors="coerce")
        missing = out["Month No"].isna()
        if not missing.any():
            return out
    else:
        missing = pd.Series(True, index=out.index)

    start = out.groupby("Series")["Date"].transform("min")
    computed = (
        (out["Date"].dt.year - start.dt.year) * 12
        + (out["Date"].dt.month - start.dt.month)
        + 1
    )
    out.loc[missing, "Month No"] = computed.loc[missing]
    return out


def add_aligned_display_date(df: pd.DataFrame) -> pd.DataFrame:
    out = add_elapsed_month(df)
    out["Date"] = parse_date(out["Date"])

    actual_start = out.loc[out["Series"].astype(str).str.contains("Actual"), "Date"].min()
    if pd.isna(actual_start):
        actual_start = out["Date"].min()

    start_period = pd.Period(actual_start, freq="M")
    out["Display Date"] = out["Month No"].fillna(1).astype(int).map(
        lambda month_no: (start_period + int(month_no) - 1).to_timestamp("M")
    )
    return out


def cumulative_cost_chart(
    df: pd.DataFrame,
    title: str,
    label_all_points: bool = False,
    timeline_basis: str = "Calendar date",
) -> alt.Chart:
    df = df.copy()
    tooltip = [
        alt.Tooltip("Date:T", title="Month", format="%b %Y"),
        alt.Tooltip("Series:N"),
        alt.Tooltip("Value:Q", title="Cumulative hard cost", format=",.0f"),
        alt.Tooltip("CompletionPct:Q", title="Completion", format=".1f"),
    ]
    if timeline_basis == "Month since start":
        df = add_aligned_display_date(df)
        x_encoding = alt.X(
            "yearmonth(Display Date):O",
            title=None,
            axis=alt.Axis(format="%b/%y", labelAngle=0, labelPadding=12),
        )
        tooltip.insert(1, alt.Tooltip("Month No:Q", title="Month #", format=".0f"))
        tooltip.insert(2, alt.Tooltip("Display Date:T", title="Aligned month", format="%b/%y"))
    else:
        x_encoding = alt.X(
            "yearmonth(Date):O",
            title=None,
            axis=alt.Axis(format="%b/%y", labelAngle=0, labelPadding=12),
        )

    if "ColorSeries" in df.columns:
        color_field = "ColorSeries:N"
        projects_for_colors = sorted(df["Project"].dropna().astype(str).unique().tolist())
        color_domain, color_range = project_color_map(projects_for_colors)
        detail_encoding = ["Series:N"]
    elif "Type" in df.columns:
        color_field = "Type:N"
        color_domain, color_range = ["Actual", "Projected"], [BRAND_EBONY, BRAND_GOLD]
        detail_encoding = ["Series:N"]
    else:
        color_field = "Series:N"
        color_domain, color_range = ["Actual", "Projected"], [BRAND_EBONY, BRAND_GOLD]
        detail_encoding = []

    base = alt.Chart(df).encode(
        x=x_encoding,
        y=alt.Y("Value:Q", axis=mm_axis("US$")),
        color=alt.Color(
            color_field,
            title="",
            scale=alt.Scale(
                domain=color_domain,
                range=color_range,
            ),
        ),
        detail=detail_encoding,
        tooltip=tooltip,
    )
    line = base.mark_line(point=True, strokeWidth=3)

    all_labels_df = df.dropna(subset=["Value"]).sort_values(["Series", "Date"]).copy()
    latest_labels_df = all_labels_df.groupby("Series", as_index=False).tail(1).copy()
    labels_df = all_labels_df.copy()
    if not label_all_points:
        labels_df = latest_labels_df
    elif "Month No" in labels_df:
        spaced_labels_df = labels_df[
            (labels_df["Month No"] == 1)
            | (labels_df["Month No"] % 3 == 0)
            | (labels_df["CompletionPct"] >= 99.5)
        ].copy()
        labels_df = (
            pd.concat([spaced_labels_df, latest_labels_df], ignore_index=True)
            .drop_duplicates(subset=["Series", "Date", "Value"], keep="last")
            .sort_values(["Series", "Date"])
        )
    labels_df["Completion Label"] = labels_df["CompletionPct"].map(
        lambda value: "" if pd.isna(value) else f"{value:.1f}%"
    )
    label_halo = (
        alt.Chart(labels_df)
        .mark_text(
            align="center",
            dy=-12,
            fontSize=11,
            fontWeight="bold",
            color="white",
            stroke="white",
            strokeWidth=4,
        )
        .encode(
            x=x_encoding,
            y=alt.Y("Value:Q"),
            text="Completion Label:N",
        )
    )
    label_text = (
        alt.Chart(labels_df)
        .mark_text(align="center", dy=-12, fontSize=11, fontWeight="bold")
        .encode(
            x=x_encoding,
            y=alt.Y("Value:Q"),
            color=alt.Color(
                color_field,
                title="",
                scale=alt.Scale(
                    domain=color_domain,
                    range=color_range,
                ),
            ),
            text="Completion Label:N",
        )
    )
    return (
        (line + label_halo + label_text)
        .properties(
            height=380,
            padding={"bottom": 35, "right": 35},
            title=title,
        )
        .configure_axis(labelColor=BRAND_GRAPHITE, titleColor=BRAND_GRAPHITE, gridColor=BRAND_GRID)
        .configure_legend(labelColor=BRAND_GRAPHITE, titleColor=BRAND_GRAPHITE)
        .configure_title(color=BRAND_EBONY, fontSize=15, anchor="start")
    )


def aggregate_portfolio(projected: pd.DataFrame, actual: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    total_projected_cost = (
        projected.sort_values("Month")
        .groupby("Project")["Projected Cumulative Hard Cost"]
        .max()
        .sum()
    )

    projected_agg = pd.DataFrame()
    if not projected.empty:
        projected_agg = (
            projected.groupby("Period", as_index=False)
            .agg(
                {
                    "Month": "min",
                    "Projected Monthly Hard Cost": "sum",
                    "Projected Completion Date": "max",
                }
            )
            .sort_values("Month")
        )
        projected_agg["Project"] = "All projects"
        projected_agg["Phase"] = "Construction"
        projected_agg["Projected Cumulative Hard Cost"] = projected_agg[
            "Projected Monthly Hard Cost"
        ].cumsum()
        if total_projected_cost:
            projected_agg["Projected Monthly Completion %"] = (
                projected_agg["Projected Monthly Hard Cost"] / total_projected_cost * 100
            ).round(2)
            projected_agg["Projected Cumulative Completion %"] = (
                projected_agg["Projected Cumulative Hard Cost"] / total_projected_cost * 100
            ).round(2)
        else:
            projected_agg["Projected Monthly Completion %"] = pd.NA
            projected_agg["Projected Cumulative Completion %"] = pd.NA
        projected_agg["Source"] = "Consolidated"
        projected_agg = add_month_number(projected_agg, "Project", "Month", "Curve Month No")

    actual_agg = pd.DataFrame()
    if not actual.empty:
        actual_agg = (
            actual.groupby("Period", as_index=False)
            .agg(
                {
                    "Report Month": "min",
                    "Monthly Hard Cost": "sum",
                    "Forecast Completion Date": "max",
                }
            )
            .sort_values("Report Month")
        )
        actual_agg["Record Name"] = actual_agg["Period"]
        actual_agg["Project"] = "All projects"
        actual_agg["Cumulative Hard Cost"] = actual_agg["Monthly Hard Cost"].cumsum()
        if total_projected_cost:
            actual_agg["Monthly Completion %"] = (
                actual_agg["Monthly Hard Cost"] / total_projected_cost * 100
            ).round(2)
            actual_agg["Cumulative Completion %"] = (
                actual_agg["Cumulative Hard Cost"] / total_projected_cost * 100
            ).round(2)
        else:
            actual_agg["Monthly Completion %"] = pd.NA
            actual_agg["Cumulative Completion %"] = pd.NA
        actual_agg["Source"] = "Consolidated"
        actual_agg = add_month_number(actual_agg, "Project", "Report Month", "Actual Month No")

    return projected_agg, actual_agg


def project_cumulative_detail(projected: pd.DataFrame, actual: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    if not projected.empty:
        frames.append(
            projected.rename(
                columns={
                    "Month": "Date",
                    "Projected Cumulative Hard Cost": "Value",
                    "Projected Cumulative Completion %": "CompletionPct",
                    "Curve Month No": "MonthNo",
                }
            )
            .assign(Type="Projected")
            [["Date", "Project", "Type", "Value", "CompletionPct", "MonthNo"]]
        )
    if not actual.empty:
        frames.append(
            actual.rename(
                columns={
                    "Report Month": "Date",
                    "Cumulative Hard Cost": "Value",
                    "Cumulative Completion %": "CompletionPct",
                    "Actual Month No": "MonthNo",
                }
            )
            .assign(Type="Actual")
            [["Date", "Project", "Type", "Value", "CompletionPct", "MonthNo"]]
        )
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out["Series"] = out["Project"].astype(str) + " - " + out["Type"].astype(str)
    out["ColorSeries"] = out["Series"]
    return out


def build_comparison(
    projected: pd.DataFrame,
    actual: pd.DataFrame,
    timeline_basis: str = "Calendar date",
) -> pd.DataFrame:
    if timeline_basis == "Month since start":
        key = "Month No"
        p = projected[
            [
                "Curve Month No",
                "Month",
                "Projected Monthly Hard Cost",
                "Projected Cumulative Hard Cost",
                "Projected Monthly Completion %",
                "Projected Cumulative Completion %",
            ]
        ].rename(columns={"Curve Month No": key, "Month": "Projected Month"})
        actual_key_col = "Actual Month No"
    else:
        key = "Period"
        p = projected[
            [
                "Period",
                "Month",
                "Projected Monthly Hard Cost",
                "Projected Cumulative Hard Cost",
                "Projected Monthly Completion %",
                "Projected Cumulative Completion %",
            ]
        ].rename(columns={"Month": "Projected Month"})
        actual_key_col = "Period"

    if actual.empty:
        p["Report Month"] = pd.NaT
        p["Monthly Hard Cost"] = pd.NA
        p["Cumulative Hard Cost"] = pd.NA
        p["Monthly Completion %"] = pd.NA
        p["Cumulative Completion %"] = pd.NA
        return p

    a = actual[
        [
            actual_key_col,
            "Report Month",
            "Monthly Hard Cost",
            "Cumulative Hard Cost",
            "Monthly Completion %",
            "Cumulative Completion %",
        ]
    ].rename(columns={actual_key_col: key})
    merged = p.merge(a, on=key, how="outer").sort_values(key)
    merged["Cumulative Cost Variance"] = (
        merged["Cumulative Hard Cost"] - merged["Projected Cumulative Hard Cost"]
    )
    merged["Completion Variance %"] = (
        merged["Cumulative Completion %"] - merged["Projected Cumulative Completion %"]
    )
    return merged


def comparable_projected_row(
    projected: pd.DataFrame,
    latest_actual_row,
    timeline_basis: str,
):
    if projected.empty or latest_actual_row is None:
        return None

    if timeline_basis == "Month since start" and "Curve Month No" in projected:
        target_month = latest_actual_row.get("Actual Month No")
        if pd.notna(target_month):
            matched = projected[pd.to_numeric(projected["Curve Month No"], errors="coerce") <= target_month]
            if not matched.empty:
                return matched.sort_values("Curve Month No").iloc[-1]

    report_month = latest_actual_row.get("Report Month")
    if pd.notna(report_month):
        matched = projected[projected["Month"].dt.to_period("M") <= pd.to_datetime(report_month).to_period("M")]
        if not matched.empty:
            return matched.sort_values("Month").iloc[-1]

    return None


def latest_contingency_by_project(contingency: pd.DataFrame) -> pd.DataFrame:
    if contingency.empty:
        return contingency
    return (
        contingency.sort_values(["Project", "Report Date"])
        .groupby("Project", as_index=False)
        .tail(1)
        .sort_values("Project")
    )


def contingency_metrics(contingency: pd.DataFrame, selected_project: str) -> dict:
    if contingency.empty:
        return {
            "latest_date": pd.NaT,
            "original": None,
            "remaining": None,
            "reallocated": None,
            "drawn": None,
            "remaining_pct": None,
        }

    if selected_project == "All projects":
        latest = latest_contingency_by_project(contingency)
        latest_date = latest["Report Date"].max()
        original = latest["Original Contingency"].sum(min_count=1)
        remaining = latest["Remaining Contingency"].sum(min_count=1)
        reallocated = latest["Total Reallocated"].sum(min_count=1)
        drawn = latest["Contingency Drawn To Date"].sum(min_count=1)
    else:
        latest = contingency.sort_values("Report Date").tail(1)
        latest_date = latest["Report Date"].iloc[0] if not latest.empty else pd.NaT
        original = latest["Original Contingency"].iloc[0] if not latest.empty else None
        remaining = latest["Remaining Contingency"].iloc[0] if not latest.empty else None
        reallocated = latest["Total Reallocated"].iloc[0] if not latest.empty else None
        drawn = latest["Contingency Drawn To Date"].iloc[0] if not latest.empty else None

    remaining_pct = None
    if original is not None and pd.notna(original) and original != 0 and remaining is not None and pd.notna(remaining):
        remaining_pct = remaining / original * 100

    return {
        "latest_date": latest_date,
        "original": original,
        "remaining": remaining,
        "reallocated": reallocated,
        "drawn": drawn,
        "remaining_pct": remaining_pct,
    }


def contingency_line_chart(contingency: pd.DataFrame, title: str) -> alt.Chart:
    df = contingency.copy()
    if df.empty:
        return alt.Chart(pd.DataFrame())

    df["Remaining Label"] = df["Remaining Contingency"].map(
        lambda value: "" if pd.isna(value) else f"{value / 1_000_000:.2f}MM"
    )
    projects = sorted(df["Project"].dropna().astype(str).unique())
    latest_labels = df.sort_values(["Project", "Report Date"]).groupby("Project", as_index=False).tail(1)

    line = (
        alt.Chart(df)
        .mark_line(point=True, strokeWidth=3)
        .encode(
            x=alt.X("yearmonth(Report Date):O", title=None, axis=alt.Axis(format="%b/%y", labelAngle=0)),
            y=alt.Y("Remaining Contingency:Q", axis=mm_axis("US$")),
            color=alt.Color("Project:N", title="", scale=contingency_color_scale(projects)),
            tooltip=[
                alt.Tooltip("Project:N"),
                alt.Tooltip("Report Date:T", title="Month", format="%b/%y"),
                alt.Tooltip("Remaining Contingency:Q", title="Remaining", format=",.0f"),
                alt.Tooltip("Total Reallocated:Q", title="Total reallocated", format=",.0f"),
            ],
        )
    )
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#B91C1C", strokeDash=[5, 5]).encode(y="y:Q")
    labels = (
        alt.Chart(latest_labels)
        .mark_text(align="left", dx=8, dy=-8, fontSize=11, fontWeight="bold")
        .encode(
            x=alt.X("yearmonth(Report Date):O"),
            y=alt.Y("Remaining Contingency:Q"),
            color=alt.Color("Project:N", title="", scale=contingency_color_scale(projects)),
            text="Remaining Label:N",
        )
    )
    return (
        (line + zero + labels)
        .properties(height=320, title=title, padding={"bottom": 25, "right": 45})
        .configure_axis(labelColor=BRAND_GRAPHITE, titleColor=BRAND_GRAPHITE, gridColor=BRAND_GRID)
        .configure_legend(labelColor=BRAND_GRAPHITE, titleColor=BRAND_GRAPHITE)
        .configure_title(color=BRAND_EBONY, fontSize=15, anchor="start")
    )


def contingency_change_chart(contingency: pd.DataFrame) -> alt.Chart:
    df = contingency.copy()
    if df.empty:
        return alt.Chart(pd.DataFrame())
    df["Project"] = df["Project"].astype(str)
    projects = sorted(df["Project"].dropna().unique())
    single_project = len(projects) <= 1
    df["Direction"] = df["Monthly Contingency Change"].map(
        lambda value: "Increase" if pd.notna(value) and value >= 0 else "Decrease"
    )
    totals = (
        df.groupby("Report Date", as_index=False)["Monthly Contingency Change"]
        .sum(min_count=1)
        .dropna(subset=["Monthly Contingency Change"])
    )
    totals = totals[totals["Monthly Contingency Change"] != 0].copy()
    totals["Change Label"] = totals["Monthly Contingency Change"].map(compact_signed_money)
    max_abs = df["Monthly Contingency Change"].abs().max() if not df.empty else 1
    label_offset = max(max_abs * 0.06, 25_000)
    totals["Label Y"] = totals["Monthly Contingency Change"].map(
        lambda value: value + label_offset if value >= 0 else value - label_offset
    )

    color_encoding = (
        alt.Color(
            "Direction:N",
            title="",
            scale=alt.Scale(domain=["Increase", "Decrease"], range=[BRAND_EBONY, BRAND_GOLD]),
        )
        if single_project
        else alt.Color("Project:N", title="", scale=contingency_color_scale(projects))
    )

    encodings = {
        "x": alt.X("yearmonth(Report Date):O", title=None, axis=alt.Axis(format="%b/%y", labelAngle=0)),
        "y": alt.Y("Monthly Contingency Change:Q", axis=compact_usd_axis("US$")),
        "color": color_encoding,
        "order": alt.Order("Project:N"),
        "tooltip": [
            alt.Tooltip("Project:N"),
            alt.Tooltip("Direction:N"),
            alt.Tooltip("Report Date:T", title="Month", format="%b/%y"),
            alt.Tooltip("Monthly Contingency Change:Q", title="Monthly change", format=",.0f"),
        ],
    }
    label_encodings = {
        "x": alt.X("yearmonth(Report Date):O"),
        "y": alt.Y("Label Y:Q", axis=compact_usd_axis("US$")),
        "text": alt.Text("Change Label:N"),
        "tooltip": [
            alt.Tooltip("Report Date:T", title="Month", format="%b/%y"),
            alt.Tooltip("Monthly Contingency Change:Q", title="Monthly total", format=",.0f"),
        ],
    }

    bars = (
        alt.Chart(df)
        .mark_bar()
        .encode(**encodings)
    )
    labels = (
        alt.Chart(totals)
        .mark_text(fontSize=11, fontWeight="bold", color=BRAND_EBONY)
        .encode(**label_encodings)
    )
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=BRAND_GRID).encode(y="y:Q")

    return (
        (zero + bars + labels)
        .properties(height=300, title="Monthly Contingency Change", padding={"top": 15, "bottom": 25})
        .configure_axis(labelColor=BRAND_GRAPHITE, titleColor=BRAND_GRAPHITE, gridColor=BRAND_GRID)
        .configure_header(labelColor=BRAND_GRAPHITE, titleColor=BRAND_GRAPHITE)
        .configure_legend(labelColor=BRAND_GRAPHITE, titleColor=BRAND_GRAPHITE)
        .configure_title(color=BRAND_EBONY, fontSize=15, anchor="start")
    )


def contingency_status(row: pd.Series) -> str:
    remaining = row.get("Remaining Contingency")
    original = row.get("Original Contingency")
    if pd.isna(remaining):
        return "-"
    if remaining < 0:
        return "Deficit"
    if pd.notna(original) and original != 0 and remaining / original < 0.25:
        return "Low Reserve"
    return "OK"


def format_contingency_table(rows: pd.DataFrame) -> pd.DataFrame:
    table = rows.copy()
    table["Status"] = table.apply(contingency_status, axis=1)
    table["Report Date"] = table["Report Date"].map(date_label)
    money_cols = [
        "Original Contingency",
        "Remaining Contingency",
        "Monthly Contingency Change",
        "Total Reallocated",
        "Contingency Drawn To Date",
    ]
    for col in money_cols:
        if col in table:
            formatter = signed_money if col in {"Monthly Contingency Change", "Total Reallocated"} else money
            table[col] = table[col].map(formatter)
    return table


require_password()

logo_uri = asset_data_uri(LOGO_FILE)
st.markdown(
    """
    <style>
    .stApp {
        background: #FBF8F1;
        color: #3D3533;
    }
    [data-testid="stHeader"] {
        background: #FBF8F1;
    }
    [data-testid="stToolbar"] {
        background: #FBF8F1;
    }
    .block-container {
        padding-top: 2.2rem;
    }
    [data-testid="stSidebar"] {
        background: #F1E8D5;
        border-right: 1px solid #E1D4BC;
    }
    .sidebar-logo-footer {
        margin-top: 34px;
        padding-top: 18px;
        border-top: 1px solid #E1D4BC;
    }
    .sidebar-logo-footer img {
        width: 142px;
        height: auto;
        display: block;
    }
    h1, h2, h3, h4, h5, h6 {
        color: #3D3533 !important;
    }
    [data-testid="stMetricValue"] {
        color: #3D3533;
    }
    .metric-card {
        border: 1px solid #E1D4BC;
        border-radius: 8px;
        padding: 16px 18px;
        background: #FFFDF8;
        min-height: 118px;
        box-shadow: 0 1px 8px rgba(61, 53, 51, 0.05);
    }
    .metric-title {
        color: #82613F;
        font-size: 0.82rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.03em;
        margin-bottom: 14px;
    }
    .metric-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 18px;
    }
    .metric-grid-3 {
        grid-template-columns: 1fr 1fr 1fr;
        gap: 14px;
    }
    .metric-label {
        color: #82613F;
        font-size: 0.78rem;
        margin-bottom: 5px;
        white-space: nowrap;
    }
    .metric-value {
        color: #3D3533;
        font-size: 1.45rem;
        line-height: 1.1;
        font-weight: 500;
        white-space: nowrap;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
st.title("Construction Tracking")

api_base = get_secret("BASEROW_API_BASE", BASEROW_API_BASE)
baserow_token = get_secret("BASEROW_API_TOKEN", BASEROW_API_TOKEN_DEFAULT)
projected_table_id = str(get_secret("BASEROW_PROJECTED_TABLE_ID", BASEROW_PROJECTED_TABLE_ID_DEFAULT))
tracking_table_id = str(get_secret("BASEROW_TRACKING_TABLE_ID", BASEROW_TRACKING_TABLE_ID_DEFAULT))
contingency_table_id = str(get_secret("BASEROW_CONTINGENCY_TABLE_ID", BASEROW_CONTINGENCY_TABLE_ID_DEFAULT))

if not baserow_token:
    st.error("Missing BASEROW_API_TOKEN. Add it in Streamlit secrets before publishing.")
    st.stop()

try:
    projected_df, actual_df, contingency_df = load_baserow_data(
        baserow_token,
        projected_table_id,
        tracking_table_id,
        contingency_table_id,
        api_base,
    )
except Exception as exc:
    st.error(f"Baserow connection failed: {exc}")
    st.stop()

projected_df = normalize_projected_completion_month(projected_df)
projected_df = trim_after_completion(
    projected_df,
    "Project",
    "Month",
    "Projected Cumulative Completion %",
    "Projected Monthly Hard Cost",
)
actual_df = trim_after_completion(
    actual_df,
    "Project",
    "Report Month",
    "Cumulative Completion %",
    "Monthly Hard Cost",
)
projected_df = add_month_number(projected_df, "Project", "Month", "Curve Month No")
actual_df = add_month_number(actual_df, "Project", "Report Month", "Actual Month No")

if projected_df.empty and actual_df.empty and contingency_df.empty:
    st.error("No Baserow rows found for the configured tables.")
    st.stop()

projects = sorted(
    set(projected_df.get("Project", pd.Series(dtype=str)))
    .union(actual_df.get("Project", pd.Series(dtype=str)))
    .union(contingency_df.get("Project", pd.Series(dtype=str)))
)
if not projects:
    st.warning("No rows loaded yet.")
    st.stop()
selected_project = st.sidebar.selectbox("Project", ["All projects"] + projects)
timeline_basis = st.sidebar.radio(
    "Timeline basis",
    ["Calendar date", "Month since start"],
    index=1,
    help=(
        "Calendar date shows schedule delay. Month since start aligns projected and actual curves "
        "by their first available month."
    ),
)
if logo_uri:
    st.sidebar.markdown(
        f"""
        <div class="sidebar-logo-footer">
          <img src="{logo_uri}" alt="Aciona logo" />
        </div>
        """,
        unsafe_allow_html=True,
    )

if selected_project == "All projects":
    p, a = aggregate_portfolio(projected_df, actual_df)
    c = contingency_df.copy()
else:
    p = projected_df[projected_df["Project"] == selected_project].copy()
    a = actual_df[actual_df["Project"] == selected_project].copy()
    c = contingency_df[contingency_df["Project"] == selected_project].copy()

if p.empty:
    st.warning("No projected curve found for this project.")
if a.empty:
    st.warning("No actual tracking found for this project yet.")

latest_actual = a.sort_values("Report Month").tail(1)
latest_projected = p.sort_values("Month").tail(1)

latest_actual_row = latest_actual.iloc[0] if not latest_actual.empty else None
latest_projected_row = latest_projected.iloc[0] if not latest_projected.empty else None
comparable_projected = comparable_projected_row(p, latest_actual_row, timeline_basis)
projected_start = p["Month"].min() if not p.empty else pd.NaT
projected_completion_date = (
    latest_projected_row["Projected Completion Date"] if latest_projected_row is not None else pd.NaT
)

actual_completion = latest_actual_row["Cumulative Completion %"] if latest_actual_row is not None else None
projected_completion = (
    comparable_projected["Projected Cumulative Completion %"] if comparable_projected is not None else None
)
projected_cumulative_hard_cost = (
    comparable_projected["Projected Cumulative Hard Cost"] if comparable_projected is not None else None
)
actual_cumulative_hard_cost = (
    latest_actual_row["Cumulative Hard Cost"] if latest_actual_row is not None else None
)
cost_delta = (
    actual_cumulative_hard_cost - projected_cumulative_hard_cost
    if actual_cumulative_hard_cost is not None
    and projected_cumulative_hard_cost is not None
    and pd.notna(actual_cumulative_hard_cost)
    and pd.notna(projected_cumulative_hard_cost)
    else None
)
completion_delta = (
    actual_completion - projected_completion
    if actual_completion is not None
    and projected_completion is not None
    and pd.notna(actual_completion)
    and pd.notna(projected_completion)
    else None
)

card1, card2, card3 = st.columns(3)
with card1:
    st.markdown(
        metric_trio_html(
            "Cost",
            "Actual",
            money_mm(actual_cumulative_hard_cost),
            "Projected",
            money_mm(projected_cumulative_hard_cost),
            "Variance",
            signed_money_mm(cost_delta),
        ),
        unsafe_allow_html=True,
    )
with card2:
    st.markdown(
        metric_trio_html(
            "Completion",
            "Actual",
            pct(actual_completion),
            "Projected",
            pct(projected_completion),
            "Variance",
            signed_pct(completion_delta),
        ),
        unsafe_allow_html=True,
    )
with card3:
    st.markdown(
        metric_trio_html(
            "Timeline",
            "Start",
            date_label(projected_start),
            "Projected Completion",
            date_label(projected_completion_date),
            "Months",
            month_count(projected_start, projected_completion_date),
        ),
        unsafe_allow_html=True,
    )

st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)

if not p.empty or not a.empty:
    cumulative = []
    if not p.empty:
        cumulative.append(
            p.rename(
                columns={
                    "Month": "Date",
                    "Projected Cumulative Hard Cost": "Value",
                    "Projected Cumulative Completion %": "CompletionPct",
                    "Curve Month No": "MonthNo",
                }
            )
            .assign(Series="Projected")
            [["Date", "Series", "Value", "CompletionPct", "MonthNo"]]
        )
    if not a.empty:
        cumulative.append(
            a.rename(
                columns={
                    "Report Month": "Date",
                    "Cumulative Hard Cost": "Value",
                    "Cumulative Completion %": "CompletionPct",
                    "Actual Month No": "MonthNo",
                }
            )
            .assign(Series="Actual")
            [["Date", "Series", "Value", "CompletionPct", "MonthNo"]]
        )
    if cumulative:
        st.altair_chart(
            cumulative_cost_chart(
                pd.concat(cumulative, ignore_index=True),
                "Cumulative Hard Cost",
                label_all_points=True,
                timeline_basis=timeline_basis,
            ),
            use_container_width=True,
        )

    if selected_project == "All projects":
        detail = project_cumulative_detail(projected_df, actual_df)
        if not detail.empty:
            st.altair_chart(
                cumulative_cost_chart(
                    detail,
                    "Cumulative Hard Cost by Project",
                    timeline_basis=timeline_basis,
                ),
                use_container_width=True,
            )

    monthly = []
    if not p.empty:
        monthly.append(
            p.rename(
                columns={
                    "Month": "Date",
                    "Projected Monthly Hard Cost": "Value",
                    "Curve Month No": "MonthNo",
                }
            )
            .assign(Series="Projected")
            [["Date", "Series", "Value", "MonthNo"]]
        )
    if not a.empty:
        monthly.append(
            a.rename(
                columns={
                    "Report Month": "Date",
                    "Monthly Hard Cost": "Value",
                    "Actual Month No": "MonthNo",
                }
            )
            .assign(Series="Actual")
            [["Date", "Series", "Value", "MonthNo"]]
        )
    if monthly:
        monthly_df = pd.concat(monthly, ignore_index=True)
        if timeline_basis == "Month since start":
            monthly_df = add_aligned_display_date(monthly_df)
            monthly_x = alt.X(
                "yearmonth(Display Date):O",
                title=None,
                axis=alt.Axis(format="%b/%y"),
            )
            monthly_tooltip = [
                alt.Tooltip("Date:T", title="Original month", format="%b/%y"),
                alt.Tooltip("Display Date:T", title="Aligned month", format="%b/%y"),
                alt.Tooltip("Month No:Q", title="Month #", format=".0f"),
                alt.Tooltip("Series:N"),
                alt.Tooltip("Value:Q", title="US$", format=",.0f"),
            ]
        else:
            monthly_x = alt.X(
                "yearmonth(Date):O",
                title=None,
                axis=alt.Axis(format="%b/%y"),
            )
            monthly_tooltip = [
                alt.Tooltip("Date:T", title="Month", format="%b/%y"),
                alt.Tooltip("Series:N"),
                alt.Tooltip("Value:Q", title="US$", format=",.0f"),
            ]

        chart = (
            alt.Chart(monthly_df)
            .mark_bar()
            .encode(
                x=monthly_x,
                y=alt.Y("Value:Q", axis=mm_axis("US$")),
                color=alt.Color(
                    "Series:N",
                    title="",
                    scale=alt.Scale(
                        domain=["Actual", "Projected"],
                        range=[BRAND_EBONY, BRAND_GOLD],
                    ),
                ),
                xOffset="Series:N",
                tooltip=monthly_tooltip,
            )
            .properties(height=320, title="Monthly Hard Cost")
            .configure_axis(labelColor=BRAND_GRAPHITE, titleColor=BRAND_GRAPHITE, gridColor=BRAND_GRID)
            .configure_legend(labelColor=BRAND_GRAPHITE, titleColor=BRAND_GRAPHITE)
            .configure_title(color=BRAND_EBONY, fontSize=15, anchor="start")
        )
        st.altair_chart(chart, use_container_width=True)

st.markdown("<div style='height: 36px;'></div>", unsafe_allow_html=True)
st.subheader("Contingency")

if c.empty:
    st.info("No contingency tracking rows found for this selection.")
else:
    contingency_summary = contingency_metrics(c, selected_project)
    cont_col1, cont_col2 = st.columns(2)
    with cont_col1:
        st.markdown(
            metric_trio_html(
                "Contingency Reserve",
                "Original",
                money(contingency_summary["original"]),
                "Remaining",
                money(contingency_summary["remaining"]),
                "Remaining %",
                pct(contingency_summary["remaining_pct"]),
            ),
            unsafe_allow_html=True,
        )
    with cont_col2:
        st.markdown(
            metric_trio_html(
                "Contingency Movement",
                "Reallocated",
                signed_money(contingency_summary["reallocated"]),
                "Drawn",
                money(contingency_summary["drawn"]),
                "Latest Report",
                date_label(contingency_summary["latest_date"]),
            ),
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)

    chart_df = c.copy()
    if selected_project == "All projects":
        line_title = "Remaining Contingency by Project"
    else:
        line_title = "Remaining Contingency"
    st.altair_chart(contingency_line_chart(chart_df, line_title), use_container_width=True)

    st.altair_chart(contingency_change_chart(chart_df), use_container_width=True)

    latest_rows = latest_contingency_by_project(c) if selected_project == "All projects" else c.sort_values("Report Date")
    display_cols = [
        "Project",
        "Report Month Label",
        "Status",
        "Original Contingency",
        "Remaining Contingency",
        "Monthly Contingency Change",
        "Total Reallocated",
        "Contingency Drawn To Date",
    ]
    display_rows = format_contingency_table(latest_rows)
    st.dataframe(
        display_rows[display_cols].rename(
            columns={
                "Report Month Label": "Report Month",
                "Original Contingency": "Original",
                "Remaining Contingency": "Remaining",
                "Monthly Contingency Change": "Monthly Change",
                "Total Reallocated": "Total Reallocated",
                "Contingency Drawn To Date": "Drawn To Date",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

