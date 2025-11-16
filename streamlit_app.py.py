import streamlit as st 
import pandas as pd
import plotly.express as px
from io import BytesIO
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from difflib import get_close_matches

st.title("AI Construction Timeline Analyzer")

planned_file = st.file_uploader("Upload Planned Timeline", type=["xlsx"])
actual_file = st.file_uploader("Upload Actual Progress", type=["xlsx"])

# Function to detect the "Task" column robustly
def find_task_column(df):
    candidates = df.columns.tolist()
    match = get_close_matches('task', [c.lower().strip() for c in candidates], n=1, cutoff=0.6)
    if not match:
        raise ValueError("No column matching 'Task' found in DataFrame")
    for col in candidates:
        if col.lower().strip() == match[0]:
            return col
    return None

# Function to detect "Duration" column robustly
def find_duration_column(df):
    candidates = df.columns.tolist()
    match = get_close_matches('duration', [c.lower().replace(" ", "") for c in candidates], n=1, cutoff=0.6)
    if not match:
        return None
    for col in candidates:
        if col.lower().replace(" ", "") == match[0]:
            return col
    return None

if planned_file and actual_file:
    df_planned = pd.read_excel(planned_file)
    df_actual = pd.read_excel(actual_file)

    # Strip spaces and lowercase column names for consistency
    df_planned.columns = df_planned.columns.str.strip().str.lower()
    df_actual.columns = df_actual.columns.str.strip().str.lower()

    # Detect Task columns
    task_col_planned = find_task_column(df_planned)
    task_col_actual = find_task_column(df_actual)

    # Clean Task values (remove extra spaces)
    df_planned[task_col_planned] = df_planned[task_col_planned].str.strip()
    df_actual[task_col_actual] = df_actual[task_col_actual].str.strip()

    # Detect and standardize Duration column
    duration_col_planned = find_duration_column(df_planned)
    duration_col_actual = find_duration_column(df_actual)

    if duration_col_planned:
        df_planned = df_planned.rename(columns={duration_col_planned: "duration_weeks"})
    if duration_col_actual:
        df_actual = df_actual.rename(columns={duration_col_actual: "duration_weeks"})

    # Rename date columns consistently if they exist
    rename_planned = {}
    if "planned start date" in df_planned.columns:
        rename_planned["planned start date"] = "start_planned"
    if "planned end date" in df_planned.columns:
        rename_planned["planned end date"] = "end_planned"
    df_planned = df_planned.rename(columns=rename_planned)

    rename_actual = {}
    if "actual start date" in df_actual.columns:
        rename_actual["actual start date"] = "start_actual"
    if "actual end date" in df_actual.columns:
        rename_actual["actual end date"] = "end_actual"
    df_actual = df_actual.rename(columns=rename_actual)

    if st.button("Analyze"):
        # Merge on Task column safely
        merged = df_planned.merge(
            df_actual,
            left_on=task_col_planned,
            right_on=task_col_actual,
            how="outer"
        )

        # Convert date columns to datetime safely
        for col in ["start_planned", "end_planned", "start_actual", "end_actual"]:
            if col in merged.columns:
                merged[col] = pd.to_datetime(merged[col], errors="coerce", dayfirst=True)

        # Calculate delays if both end dates exist
        if "end_planned" in merged.columns and "end_actual" in merged.columns:
            merged["DelayDays"] = (merged["end_actual"] - merged["end_planned"]).dt.days
        else:
            merged["DelayDays"] = 0

        # Color coding
        merged["Color"] = merged["DelayDays"].apply(
            lambda x: "red" if x > 0 else ("green" if x < 0 else "gray")
        )

        st.subheader("Delay Table")
        st.dataframe(merged)

        # Prepare Gantt chart only if date columns exist
        gantt_rows = []
        if "start_planned" in merged.columns and "end_planned" in merged.columns:
            gantt_rows.append(pd.DataFrame({
                "Task": merged[task_col_planned],
                "Start": merged["start_planned"],
                "Finish": merged["end_planned"],
                "Type": "Planned"
            }))
        if "start_actual" in merged.columns and "end_actual" in merged.columns:
            gantt_rows.append(pd.DataFrame({
                "Task": merged[task_col_actual],
                "Start": merged["start_actual"],
                "Finish": merged["end_actual"],
                "Type": "Actual"
            }))

        if gantt_rows:
            gantt_df = pd.concat(gantt_rows)
            fig = px.timeline(
                gantt_df,
                x_start="Start",
                x_end="Finish",
                y="Task",
                color="Type"
            )
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(fig, use_container_width=True)

        # AI insights
        total_delay = merged["DelayDays"].sum() if "DelayDays" in merged.columns else 0
        insights = f"""
        Total Delay: {total_delay} days  
        Status: {"Behind Schedule" if total_delay > 0 else "On/Ahead of Schedule"}  
        """

        st.subheader("Insights")
        st.write(insights)

        # PDF export
        pdf_buffer = BytesIO()
        doc = SimpleDocTemplate(pdf_buffer)
        styles = getSampleStyleSheet()
        doc.build([
            Paragraph("AI Timeline Report", styles["Title"]),
            Paragraph(insights.replace("\n", "<br/>"), styles["Normal"])
        ])
        st.download_button("Download Report", pdf_buffer, "report.pdf")

