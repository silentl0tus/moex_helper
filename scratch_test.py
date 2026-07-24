import sys
from streamlit.web.cli import main

# I'll just write a quick script that imports streamlit_project and runs fetch_moex_universe
# to see where it crashes.
import traceback

try:
    import streamlit_project
    # Let's mock st to capture errors? No, streamlit_project runs in global scope but the 
    # execution is inside a streamlit context usually.
    # The error is likely when generating map_df or the Altair chart.
except Exception as e:
    traceback.print_exc()

