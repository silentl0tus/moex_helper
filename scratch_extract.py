import re
with open('/home/silent/.gemini/antigravity-ide/brain/0212836f-5306-4eae-aa6f-fff415d21f2f/.system_generated/steps/392/content.md', 'r') as f:
    text = f.read()

urls = set(re.findall(r"url:\s*'(.*?)'", text))
print("AJAX URLs:", urls)
