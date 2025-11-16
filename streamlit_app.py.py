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

    if st.button("Analyze Project"):
        # Merge by task
        merged = df_planned.merge(df_actual, on="Task", suffixes=("_Planned", "_Actual"))

        # Delay calculation
        merged["DelayDays"] = (merged["End_Actual"] - merged["End_Planned"]).dt.days

        st.subheader("📊 Delay Table")
        st.dataframe(merged[["Task", "Start_Planned", "End_Planned", "Start_Actual", "End_Actual", "DelayDays"]])

        # Gantt Chart
        st.subheader("📈 Gantt Chart")

        gantt_df = pd.DataFrame({
            "Task": merged["Task"],
            "Start": merged["Start_Planned"],
            "Finish": merged["End_Planned"],
            "Type": "Planned"
        }).append(pd.DataFrame({
            "Task": merged["Task"],
            "Start": merged["Start_Actual"],
            "Finish": merged["End_Actual"],
            "Type": "Actual"
        }))

        fig = px.timeline(gantt_df, x_start="Start", x_end="Finish", y="Task", color="Type")
        st.plotly_chart(fig, use_container_width=True)

        # AI Insights
        st.subheader("🤖 AI Insights")
        
        behind = merged[merged["DelayDays"] > 0]["Task"].tolist()
        ahead = merged[merged["DelayDays"] < 0]["Task"].tolist()

        insights = f"""
        **Phases Behind Schedule:** {behind}  
        **Phases Ahead of Schedule:** {ahead}  
        **Estimated Project Delay:** {merged['DelayDays'].sum()} days  
        **Risk Score:** {'High' if merged['DelayDays'].sum() > 10 else 'Low'}  
        **Recommendation:** Focus on tasks causing the highest delays to recover timeline.
        """

        st.write(insights)

        # PDF generation
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer)
        styles = getSampleStyleSheet()
        story = [Paragraph("Construction Timeline Report", styles["Title"]),
                 Paragraph(insights, styles["Normal"])]
        doc.build(story)

        st.download_button("Download PDF Report", buffer, file_name="timeline_report.pdf")
