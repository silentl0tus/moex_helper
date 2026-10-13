import re

with open("streamlit_project.py", "r") as f:
    content = f.read()

# We need to swap the `with tab1:` block and `with tab2:` block.
# Let's find the blocks.
tab1_start = content.find("        with tab1:")
tab2_start = content.find("        with tab2:")
tab3_start = content.find("        with tab3:")

tab1_block = content[tab1_start:tab2_start]
tab2_block = content[tab2_start:tab3_start]

# Swap them
new_content = content[:tab1_start] + tab2_block + tab1_block + content[tab3_start:]

with open("streamlit_project.py", "w") as f:
    f.write(new_content)
