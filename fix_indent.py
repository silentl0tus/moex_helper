with open("streamlit_project.py", "r") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if line.startswith("            capital = st.number_input("):
        lines[i] = "        " + line.lstrip()
    if line.startswith("            min_roe_filter = st.slider("):
        lines[i] = "        " + line.lstrip()

with open("streamlit_project.py", "w") as f:
    f.writelines(lines)
