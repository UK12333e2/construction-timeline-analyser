import streamlit as st
import pandas as pd
import plotly.express as px
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from io import BytesIO

st.set_page_config(page_title="AI Construction Timeline Analyzer")

st.title("AI Construction Timeline Analyzer")

# Upload boxes
planned_file = st.file_uploader("Upload Planned Timeline (Excel)", type=["xlsx"])
actual_file = st.file_uploader("Upload Actual Progress (Excel)", type=["xlsx"])

if planned_file and actual_file:
    df_planned = pd.read_excel(planned_file)
    df_actual = pd.read_excel(actual_file)

    # Rename columns to match expected names
    df_planned = df_planned.rename(columns={
        "Planned Start Date": "Start_Planned",
        "Planned End Date": "End_Planned"
    })

    df_actual = df_actual.rename(columns={
        "Actual Start Date": "Start_Actual",
        "Actual End Date": "End_Actual"
    })

    if st.button("Analyze Project"):
        # Merge by Task
        merged = df_planned.merge(df_actual, on="Task", suffixes=("_Planned", "_Actual"))

        # Convert to datetime
        merged["Start_Planned"] = pd.to_datetime(merged["Start_Planned"])
        merged["End_Planned"] = pd.to_datetime(merged["End_Planned"])
        merged["Start_Actual"] =_]()

