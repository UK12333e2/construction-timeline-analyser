import streamlit as st
import pandas as pd
import plotly.express as px
from io import BytesIO
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet

st.title("AI Construction Timeline Analyzer")

planned_file = st.file_uploader("Upload Planned Timeline", type=["xlsx"])
actual_file = st.file_uploader("Upload Actual Progress", type=["xlsx"])

if planned_file and actual_file:

    df_planned = pd.read_excel(planned_file)
    df_actual = pd.read_excel(actual_file)

    df_planned = df_planned.rename(columns={
        "Planned Start Date": "Start_Planned",
        "Planned End Date": "End_Planned"
    })

    df_actual = df_actual.rename(columns={
        "Actual Start Date": "Start_Actual",
        "Actual End Date": "End_Actual"
    })

    if st.button("Analyze"):

        # ✅ THIS IS THE LINE THAT WAS BROKEN — NOW FIXED
        merged = df_planned.merge(df_actual, on="Task")

        # Convert dates
        for col in ["Start_Planned", "End_Planned", "Start_Actual", "End_Actual"]:
            merged[col] = pd.to_datetime(merged[col], errors="coerce")

        # Calculate delays
        merged["DelayDays"] = (merged["End_Actual"] - merged["End_Planned"]).dt.days

        # Color coding
        merged["Color"] = merged["DelayDays"].apply(
            lambda x: "red" if x > 0 else ("green" if x < 0 else "gray")
        )

        st.subheader("Delay Table")
        st.dataframe(merged)

        # Gantt Chart
        gantt_df = pd.concat([
            pd.DataFrame({
                "Task": merged["Task"],
                "Start": merged["Start_Planned"],
                "Finish": merged["End_Planned"],
                "Type": "Planned"
            }),
            pd.DataFrame({
                "Task": merged["Task"],
                "Start": merged["Start_Actual"],
                "Finish": merged["End_Actual"],
                "Type": "Actual"
            })
        ])

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
        total_delay = merged["DelayDays"].sum()
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
        doc.build([Paragraph("AI Timeline Report", styles["Title"]),
                   Paragraph(insights.replace("\n", "<br/>"), styles["Normal"])])

        st.download_button("Download Report", pdf_buffer, "report.pdf")

