"""
AI Construction Timeline Analyzer - app.py

Dependencies:
    pip install streamlit pandas plotly reportlab openpyxl

Run:
    streamlit run app.py
"""

import io
from datetime import datetime
from typing import Tuple, List

import pandas as pd
import plotly.express as px
import streamlit as st
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Frame

# -------------------------
# App config & styling
# -------------------------
st.set_page_config(page_title="AI Construction Timeline Analyzer", layout="wide")

PRIMARY_BLUE = "#0b57a4"  # professional blue
ACCENT_BLUE = "#1e88e5"
BG = "#f7fbff"

# Basic top-level layout
st.markdown(
    f"""
    <style>
    .stApp {{ background-color: {BG}; }}
    .title {{ color: {PRIMARY_BLUE}; font-size: 34px; font-weight:700; }}
    .subtle {{ color: #333; }}
    .stButton>button {{ background-color: {PRIMARY_BLUE}; color: white; }}
    .upload-box .stFileUpload input {{ border-radius: 6px; }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown("<div class='title'>AI Construction Timeline Analyzer</div>", unsafe_allow_html=True)
st.markdown("<div class='subtle'>Upload planned timeline and actual progress Excel files, then click Analyse Project.</div>", unsafe_allow_html=True)
st.write("---")

# -------------------------
# Helper functions
# -------------------------
def robust_date_parse(series: pd.Series) -> pd.Series:
    """Try to robustly convert series to datetime, preserving NaT where parse fails."""
    # If already datetime
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series)
    # Try to convert with pandas
    return pd.to_datetime(series, errors="coerce", infer_datetime_format=True)


def find_column(df: pd.DataFrame, target_keywords: List[str]) -> str:
    """
    Find the first column in df whose name contains all target keywords (case-insensitive).
    target_keywords: list of keywords that should each appear in column name (AND).
    Returns column name or '' if not found.
    """
    lower_cols = {c.lower(): c for c in df.columns}
    for col_low, col_orig in lower_cols.items():
        if all(k.lower() in col_low for k in target_keywords):
            return col_orig
    return ""


def infer_columns(planned: pd.DataFrame, actual: pd.DataFrame) -> Tuple[dict, str]:
    """
    Infer useful columns. Returns mapping and message.
    mapping contains keys:
        'task', 'phase' (optional), 'start_planned', 'end_planned', 'start_actual', 'end_actual'
    """
    mapping = {}
    warn_msgs = []

    # Task column (must exist in both)
    task_col = None
    for candidate in ["Task", "task", "TASK", "Activity", "activity", "Name", "name"]:
        if candidate in planned.columns and candidate in actual.columns:
            task_col = candidate
            break
    if task_col is None:
        # try case-insensitive find where any column name matches 'task' substring
        task_col = find_column(planned, ["task"]) or find_column(actual, ["task"])
        if task_col:
            # ensure both df have a column matching that substring; if not, we will use closest matches
            if task_col not in planned.columns:
                # find any planned col with 'task' substring
                for c in planned.columns:
                    if "task" in c.lower():
                        task_col = c
                        break
    if task_col is None:
        # give last chance: pick the first common column name
        common = set(planned.columns).intersection(set(actual.columns))
        if common:
            task_col = list(common)[0]
            warn_msgs.append(f"No explicit Task-like column found. Using common column '{task_col}' as Task.")
        else:
            raise ValueError("Could not find a common 'Task' column in the two uploaded files. "
                             "Please ensure both Excel files contain a matching column such as 'Task'.")

    mapping["task"] = task_col

    # Phase column (optional)
    phase_col = None
    for c in ["Phase", "phase", "Phase Name", "phase name", "Stage", "stage"]:
        if c in planned.columns or c in actual.columns:
            phase_col = c if (c in planned.columns or c in actual.columns) else None
            if phase_col:
                break
    if phase_col is None:
        # try substring
        for c in planned.columns:
            if "phase" in c.lower() or "stage" in c.lower():
                phase_col = c
                break
        if not phase_col:
            for c in actual.columns:
                if "phase" in c.lower() or "stage" in c.lower():
                    phase_col = c
                    break
    mapping["phase"] = phase_col

    # Date columns: try a few patterns
    # Planned
    sp = find_column(planned, ["start", "planned"]) or find_column(planned, ["start"])
    ep = find_column(planned, ["end", "planned"]) or find_column(planned, ["end"])
    # Actual
    sa = find_column(actual, ["start", "actual"]) or find_column(actual, ["start"])
    ea = find_column(actual, ["end", "actual"]) or find_column(actual, ["end"])

    if not (ep and ea):
        # if we couldn't find based on both planned/actual qualifiers, attempt broader matching:
        # If planned has columns like 'Start Date' and 'End Date' and actual too, use them.
        sp_alt = find_column(planned, ["start", "date"]) or find_column(planned, ["start"])
        ep_alt = find_column(planned, ["end", "date"]) or find_column(planned, ["end"])
        sa_alt = find_column(actual, ["start", "date"]) or find_column(actual, ["start"])
        ea_alt = find_column(actual, ["end", "date"]) or find_column(actual, ["end"])
        sp = sp or sp_alt
        ep = ep or ep_alt
        sa = sa or sa_alt
        ea = ea or ea_alt

    mapping["start_planned"] = sp or ""
    mapping["end_planned"] = ep or ""
    mapping["start_actual"] = sa or ""
    mapping["end_actual"] = ea or ""

    # Notify if we couldn't infer fully
    if not mapping["end_planned"]:
        warn_msgs.append("Could not auto-detect 'End Planned' column in Planned file. "
                         "Please ensure a column with 'end' and 'planned' (or similar) exists.")
    if not mapping["end_actual"]:
        warn_msgs.append("Could not auto-detect 'End Actual' column in Actual file. "
                         "Please ensure a column with 'end' and 'actual' (or similar) exists.")

    return mapping, "\n".join(warn_msgs)


def prepare_merged_df(planned: pd.DataFrame, actual: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    """Merge planned and actual on Task, parse dates, compute delay days, and return merged df."""
    task_col = mapping["task"]
    merged = pd.merge(planned.copy(), actual.copy(), left_on=task_col, right_on=task_col, suffixes=("_PL", "_AC"), how="outer")
    # Standardize column names for ease
    # Identify end planned & end actual column names in merged
    end_pl_candidates = [c for c in merged.columns if "end" in c.lower() and ("pl" in c.lower() or "planned" in c.lower())]
    end_ac_candidates = [c for c in merged.columns if "end" in c.lower() and ("ac" in c.lower() or "actual" in c.lower())]

    # fallback to mapping values
    end_pl = mapping.get("end_planned") or (end_pl_candidates[0] if end_pl_candidates else "")
    end_ac = mapping.get("end_actual") or (end_ac_candidates[0] if end_ac_candidates else "")

    # If columns specified with suffix exist, try both
    if end_pl and end_pl not in merged.columns:
        # maybe it's without PL suffix
        if f"{end_pl}_PL" in merged.columns:
            end_pl = f"{end_pl}_PL"
    if end_ac and end_ac not in merged.columns:
        if f"{end_ac}_AC" in merged.columns:
            end_ac = f"{end_ac}_AC"

    # As last resort, search for first 'end' column in left and right halves
    if not end_pl:
        for c in merged.columns:
            if "end" in c.lower() and "_pl" in c.lower():
                end_pl = c
                break
    if not end_ac:
        for c in merged.columns:
            if "end" in c.lower() and ("_ac" in c.lower() or "_actual" in c.lower()):
                end_ac = c
                break

    # Try to find sensible defaults if still empty
    if not end_pl:
        # pick any column from planned part that contains 'end'
        for c in planned.columns:
            if "end" in c.lower():
                end_pl = c
                break
    if not end_ac:
        for c in actual.columns:
            if "end" in c.lower():
                end_ac = c
                break

    # Finally if still not found, raise
    if not end_pl or not end_ac:
        raise ValueError("Unable to identify End Planned and End Actual columns automatically. "
                         "Please ensure your Excel files have clearly named end date columns (e.g. 'End Planned', 'End Actual').")

    # Parse dates
    merged["_end_planned_dt"] = robust_date_parse(merged[end_pl])
    merged["_end_actual_dt"] = robust_date_parse(merged[end_ac])

    # Compute delay in days (End Actual - End Planned). Positive => delayed.
    merged["Delay_Days"] = (merged["_end_actual_dt"] - merged["_end_planned_dt"]).dt.days

    # Add a human-friendly string for dates
    merged["End_Planned"] = merged["_end_planned_dt"].dt.date
    merged["End_Actual"] = merged["_end_actual_dt"].dt.date

    # Fill task and phase
    merged["Task"] = merged[mapping["task"]]
    if mapping.get("phase"):
        merged["Phase"] = merged.get(mapping["phase"]) if mapping["phase"] in merged.columns else None
    else:
        merged["Phase"] = merged.get("Phase", None)

    # Keep key columns
    display_cols = ["Task", "Phase", end_pl, end_ac, "End_Planned", "End_Actual", "Delay_Days"]
    # but ensure columns exist
    display_cols = [c for c in display_cols if c in merged.columns]
    return merged


def create_gantt(merged: pd.DataFrame, mapping: dict) -> px.timeline:
    """
    Build a Plotly Express timeline with two bars per task (Planned and Actual).
    We'll try to identify start and end planned/actual columns.
    """
    rows = []
    # find start/end columns names in merged (we may already have parsed dt columns)
    # Prefer dt columns if present
    for _, row in merged.iterrows():
        task = row.get("Task")
        phase = row.get("Phase", "")
        # Determine start & end for planned and actual:
        # Look for any columns that contain 'start' and 'planned' etc.
        # Use parsed dt columns if available
        start_pl = None
        end_pl = None
        start_ac = None
        end_ac = None

        if "_start_planned_dt" in merged.columns and "_start_actual_dt" in merged.columns:
            start_pl = row.get("_start_planned_dt")
            end_pl = row.get("_end_planned_dt")
            start_ac = row.get("_start_actual_dt")
            end_ac = row.get("_end_actual_dt")
        else:
            # Try to find start columns in the row
            for c in merged.index:
                pass
            # fallback: use parsed end date and assume start 7 days before (for visualization) if start missing
            end_pl = row.get("_end_planned_dt")
            end_ac = row.get("_end_actual_dt")
            if pd.notna(end_pl) and start_pl is None:
                start_pl = end_pl - pd.Timedelta(days=7)
            if pd.notna(end_ac) and start_ac is None:
                start_ac = end_ac - pd.Timedelta(days=7)

        # Append planned and actual if have end dates
        if pd.notna(end_pl):
            rows.append({
                "Task": task,
                "Phase": phase,
                "Type": "Planned",
                "Start": start_pl,
                "Finish": end_pl
            })
        if pd.notna(end_ac):
            rows.append({
                "Task": task,
                "Phase": phase,
                "Type": "Actual",
                "Start": start_ac,
                "Finish": end_ac
            })

    if not rows:
        raise ValueError("No timeline rows found to build Gantt chart (dates may not have parsed correctly).")

    gantt_df = pd.DataFrame(rows)
    # Ensure Start/Finish datetimes
    gantt_df["Start"] = pd.to_datetime(gantt_df["Start"])
    gantt_df["Finish"] = pd.to_datetime(gantt_df["Finish"])

    # Plotly timeline
    fig = px.timeline(
        gantt_df,
        x_start="Start",
        x_end="Finish",
        y="Task",
        color="Type",
        facet_row="Phase" if "Phase" in gantt_df.columns and gantt_df["Phase"].notna().any() else None,
        title="Gantt Chart ??? Planned vs Actual",
    )
    fig.update_layout(
        height=600,
        title_font=dict(size=18, color=PRIMARY_BLUE),
        legend_title_text="",
        template="plotly_white",
        margin=dict(l=150, r=20, t=60, b=40),
    )
    # Use professional blue/grey palette: set Planned=primary blue, Actual=accent blue
    color_map = {"Planned": PRIMARY_BLUE, "Actual": ACCENT_BLUE}
    fig.for_each_trace(lambda t: t.update(marker_color=color_map.get(t.name, PRIMARY_BLUE)))
    return fig


def generate_insights(merged: pd.DataFrame) -> dict:
    """
    Generate simple AI-style insights:
        - phases behind / ahead (count per Phase)
        - total delay (sum of positive delays)
        - average delay
        - risk level (Low/Medium/High based on avg delay)
    """
    insights = {}
    # Filter only tasks with numeric Delay_Days
    numeric = merged[merged["Delay_Days"].notna()].copy()
    if numeric.empty:
        insights["summary"] = "No valid delay data detected."
        return insights

    numeric["Behind"] = numeric["Delay_Days"] > 0
    numeric["Ahead"] = numeric["Delay_Days"] < 0

    # Group by phase if present
    if "Phase" in numeric.columns and numeric["Phase"].notna().any():
        phase_groups = numeric.groupby("Phase").agg(
            tasks_total=("Task", "count"),
            tasks_behind=("Behind", "sum"),
            tasks_ahead=("Ahead", "sum"),
            avg_delay=("Delay_Days", "mean"),
        ).reset_index().sort_values("avg_delay", ascending=False)
        insights["phases"] = phase_groups
    else:
        insights["phases"] = None

    total_delay = numeric.loc[numeric["Delay_Days"] > 0, "Delay_Days"].sum(min_count=1)
    avg_delay = numeric["Delay_Days"].mean()
    num_tasks = numeric.shape[0]
    num_behind = int(numeric["Behind"].sum() if "Behind" in numeric.columns else (numeric["Delay_Days"] > 0).sum())
    num_ahead = int(numeric["Ahead"].sum() if "Ahead" in numeric.columns else (numeric["Delay_Days"] < 0).sum())

    insights["total_delay_days"] = int(total_delay) if pd.notna(total_delay) else 0
    insights["avg_delay_days"] = float(avg_delay) if pd.notna(avg_delay) else 0.0
    insights["num_tasks"] = int(num_tasks)
    insights["num_behind"] = int(num_behind)
    insights["num_ahead"] = int(num_ahead)

    # Risk level heuristics
    if insights["avg_delay_days"] >= 10 or insights["total_delay_days"] > insights["num_tasks"] * 5:
        risk = "HIGH"
        risk_reason = "Average delay >= 10 days or total delay large relative to project size."
    elif insights["avg_delay_days"] >= 3:
        risk = "MEDIUM"
        risk_reason = "Average delay between 3 and 10 days."
    else:
        risk = "LOW"
        risk_reason = "Average delay under 3 days."

    insights["risk"] = {"level": risk, "reason": risk_reason}
    insights["summary"] = (
        f"Out of {insights['num_tasks']} tasks, {insights['num_behind']} are behind schedule and "
        f"{insights['num_ahead']} are ahead. Total accumulated delay (positive delays) is "
        f"{insights['total_delay_days']} day(s). Average delay per task: {insights['avg_delay_days']:.1f} days."
    )
    return insights


def create_pdf_report(insights: dict, merged: pd.DataFrame, pdf_title: str = "AI Construction Timeline Analysis") -> bytes:
    """
    Create a simple PDF report using ReportLab containing the insights summary and a small table of top delayed tasks.
    Returns PDF as bytes.
    """
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Optional: register a standard font if available
    try:
        pdfmetrics.registerFont(TTFont("Helvetica", "Helvetica.ttf"))
        font_name = "Helvetica"
    except Exception:
        font_name = "Times-Roman"

    # Header
    c.setFont(font_name, 16)
    c.setFillColor(PRIMARY_BLUE)
    c.drawString(30 * mm, (height - 30 * mm), pdf_title)

    c.setFillColor("black")
    c.setFont(font_name, 10)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    c.drawString(30 * mm, (height - 36 * mm), f"Generated: {now_str}")

    # Insights summary paragraph
    text_style = ParagraphStyle(
        name="Normal",
        fontName=font_name,
        fontSize=10,
        leading=12,
    )
    story = []
    summary_text = insights.get("summary", "No insights available.")
    story.append(Paragraph(f"<b>Executive summary</b><br/>{summary_text}", text_style))
    story.append(Paragraph("<br/>", text_style))

    # Risk
    risk = insights.get("risk", {})
    risk_level = risk.get("level", "N/A")
    risk_reason = risk.get("reason", "")
    story.append(Paragraph(f"<b>Risk level:</b> {risk_level} - {risk_reason}", text_style))
    story.append(Paragraph("<br/>", text_style))

    # Phases table if present - show top 8 phases by avg_delay
    if insights.get("phases") is not None:
        phases_df: pd.DataFrame = insights["phases"]
        # Convert to small html-ish table via Paragraphs
        story.append(Paragraph("<b>Phases overview (top delays)</b>", text_style))
        # Build a simple textual table
        table_text = "<br/>".join(
            [f"{r['Phase']}: tasks={int(r['tasks_total'])}, behind={int(r['tasks_behind'])}, "
             f"avg_delay={r['avg_delay']:.1f}d" for _, r in phases_df.sort_values("avg_delay", ascending=False).head(8).iterrows()]
        )
        story.append(Paragraph(table_text, text_style))
        story.append(Paragraph("<br/>", text_style))

    # Top delayed tasks table
    if "Delay_Days" in merged.columns:
        top_delays = merged[merged["Delay_Days"].notna()].sort_values("Delay_Days", ascending=False).head(10)
        if not top_delays.empty:
            story.append(Paragraph("<b>Top delayed tasks</b>", text_style))
            td_lines = []
            for _, r in top_delays.iterrows():
                td_lines.append(f"{r.get('Task')} ??? Delay: {int(r.get('Delay_Days'))} days; Planned End: {r.get('End_Planned')} Actual End: {r.get('End_Actual')}")
            story.append(Paragraph("<br/>".join(td_lines), text_style))

    # Frame to place story
    frame = Frame(30 * mm, 30 * mm, width - 60 * mm, height - 80 * mm, showBoundary=0)
    frame.addFromList(story, c)

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()


# -------------------------
# Streamlit UI - Uploads
# -------------------------
col1, col2 = st.columns(2)
with col1:
    planned_file = st.file_uploader("Upload Planned Timeline (Excel)", type=["xlsx", "xls"], key="planned")
with col2:
    actual_file = st.file_uploader("Upload Actual Progress (Excel)", type=["xlsx", "xls"], key="actual")

st.markdown("**Notes:** Excel files should contain a common 'Task' column and clear End date columns (e.g. 'End Planned', 'End Actual'). The app will try to auto-detect common variations for date column names.")
st.write("")

# Analyse button
analyse_btn = st.button("Analyse Project")

# Keep PDF bytes in session_state for download
if "report_pdf" not in st.session_state:
    st.session_state["report_pdf"] = None

# -------------------------
# Main analysis flow
# -------------------------
if analyse_btn:
    try:
        if planned_file is None or actual_file is None:
            st.warning("Please upload both Planned Timeline and Actual Progress Excel files before analysing.")
            st.stop()

        # Read Excel files into dataframes
        try:
            planned_df = pd.read_excel(planned_file, engine="openpyxl")
        except Exception:
            planned_file.seek(0)
            planned_df = pd.read_excel(planned_file)
        try:
            actual_df = pd.read_excel(actual_file, engine="openpyxl")
        except Exception:
            actual_file.seek(0)
            actual_df = pd.read_excel(actual_file)

        st.success("Files loaded successfully.")
        # Infer columns
        mapping, warn_msg = infer_columns(planned_df, actual_df)
        if warn_msg:
            st.info(warn_msg)

        # Prepare merged dataframe and compute delays
        merged = prepare_merged_df(planned_df, actual_df, mapping)

        # Show delay table
        st.subheader("Delay Table")
        # Present a friendly table (sorted by Delay descending)
        display_table = merged[["Task", "Phase", "End_Planned", "End_Actual", "Delay_Days"]].copy()
        # fallback: if Phase not in columns drop it
        if "Phase" not in display_table.columns:
            display_table = merged[["Task", "End_Planned", "End_Actual", "Delay_Days"]].copy()
        display_table = display_table.sort_values("Delay_Days", ascending=False)
        st.dataframe(display_table.reset_index(drop=True), use_container_width=True)

        # Gantt chart
        st.subheader("Gantt Chart (Planned vs Actual)")
        try:
            fig = create_gantt(merged, mapping)
            st.plotly_chart(fig, use_container_width=True)
        except Exception as e:
            st.error(f"Could not generate Gantt chart: {e}")

        # Generate AI insights
        st.subheader("AI Insights")
        insights = generate_insights(merged)
        st.markdown(f"**Summary:** {insights.get('summary', 'No summary')}")
        st.markdown(f"**Total positive delay (days):** {insights.get('total_delay_days', 0)}")
        st.markdown(f"**Average delay (days):** {insights.get('avg_delay_days', 0):.1f}")
        st.markdown(f"**Risk level:** {insights.get('risk', {}).get('level', 'N/A')} ??? {insights.get('risk', {}).get('reason', '')}")

        # Phase insights table if present
        if insights.get("phases") is not None:
            st.markdown("**Phases overview (by avg delay)**")
            st.dataframe(insights["phases"].reset_index(drop=True), use_container_width=True)

        # Create PDF report
        st.info("Generating PDF report...")
        pdf_bytes = create_pdf_report(insights, merged)
        st.session_state["report_pdf"] = pdf_bytes
        st.success("PDF report generated and ready for download.")

        # Download button
        st.download_button(
            label="Download PDF Report",
            data=st.session_state["report_pdf"],
            file_name="AI_Construction_Timeline_Report.pdf",
            mime="application/pdf"
        )

    except Exception as e:
        st.exception(f"An error occurred during analysis: {e}")

# If user already has a generated PDF in the session, show a download button persistently
if st.session_state.get("report_pdf") is not None and not analyse_btn:
    st.sidebar.markdown("### Download last report")
    st.sidebar.download_button(
      
      
      
        label="Download PDF Report",
        data=st.session_state["report_pdf"],
        file_name="AI_Construction_Timeline_Report.pdf",
        mime="application/pdf"
    )

st.write("---")
st.markdown("<small style='color:#555'>Built with ?????? ??? AI Construction Timeline Analyzer</small>", unsafe_allow_html=True)
