import streamlit as st
import pandas as pd
import plotly.express as px
from io import BytesIO
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet

st.title("AI Construction Timeline Analyzer")

planned_file = st.file_uploader("Upload Planned Timeline", type=["xlsx"])
actual_file = st.file_uploader("Upload Actual Progress", type=["xlsx"])

# Function to detect Task column robustly
def find_task_column(df):
    for col in df.columns:
        # Check if 'task' is in column name (case-insensitive)
        if 'task' in col.lower():
            return col
    raise ValueError("No column matching 'Task' found in DataFrame")

# Function to detect Duration column robustly
def find_duration_column(df):
    for col in df.columns:
        name = col.lower().replace(" ", "")
        if "duration" in name:
            return col
    return None

if planned_file and actual_file:
    # Load Excel files
    df_planned = pd.read_excel(planned_file)
    df_actual = pd.read_excel(actual_file)

    # Clean column names: strip spaces, remove non-printable characters, lowercase
    def clean_columns(df):
        df.columns = (
            df.columns
            .str.strip()
            .str.replace(r'\s+', ' ', regex=True)
            .str.replace(r'\xa0','', regex=True)
            .str.lower()
        )
        return df

    df_planned = clean_columns(df_planned)
    df_actual = clean_columns(df_actual)

    # Detect Task columns
    task_col_planned = find_task_column(df_planned)
    task_col_actual = find_task_column(df_actual)

    # Strip spaces from Task values
    df_planned[task_col_planned] = df_planned[task_col_planned].astype(str).str.strip()
    df_actual[task_col_actual] = df_actual[task_col_actual].astype(str).str.strip()

    # Detect and rename Duration column
    duration_col_planned = find_duration_column(df_planned)
    duration_col_actual = find_duration_column(df_actual)
    if duration_col_planned:
        df_planned = df_planned.rename(columns={duration_col_planned: "duration_weeks"})
    if duration_col_actual:
        df_actual = df_actual.rename(columns={duration_col_actual: "duration_weeks"})

    # Rename date columns consistently
    if "planned start date" in df_planned.columns:
        df_planned = df_planned.rename(columns={"planned start date": "start_planned"})
    if "planned end date" in df_planned.columns:
        df_planned = df_planned.rename(columns={"planned end date": "end_planned"})
    if "actual start date" in df_actual.columns:
        df_actual = df_actual.rename(columns={"actual start date": "start_actual"})
    if "actual end date" in df_actual.columns:
        df_actual = df_actual.rename(columns={"actual end date": "end_actual"})

    if st.button("Analyze"):
        # Merge Planned and Actual safely
        merged = df_planned.merge(
            df_actual,
            left_on=task_col_planned,
            right_on=task_col_actual,
            how="outer"
        )

        # Convert dates safely
        for col in ["start_planned", "end_planned", "start_actual", "end_actual"]:
            if col in merged.columns:
                merged[col] = pd.to_datetime(merged[col], errors="coerce", dayfirst=True)

        # Calculate delays
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

        # Prepare Gantt chart
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
