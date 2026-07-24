import re

with open('/home/silent/.gemini/antigravity-ide/brain/0212836f-5306-4eae-aa6f-fff415d21f2f/.system_generated/steps/651/content.md', 'r') as f:
    text = f.read()

# remove script tags
text = re.sub(r'<script.*?>.*?</script>', '', text, flags=re.DOTALL)
# remove style tags
text = re.sub(r'<style.*?>.*?</style>', '', text, flags=re.DOTALL)
# get visible text by removing all html tags
text = re.sub(r'<.*?>', ' ', text)
# collapse spaces
text = re.sub(r'\s+', ' ', text)

print(text[:3000])
