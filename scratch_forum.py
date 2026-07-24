import requests
import re
url = "https://smart-lab.ru/forum/SBER"
headers = {"User-Agent": "Mozilla/5.0"}
try:
    response = requests.get(url, headers=headers, timeout=10)
    print("Status:", response.status_code)
    
    # Try finding posts by comments div
    # In smartlab forum, comments are usually in <div class="comment"> or <div class="text">
    posts = re.findall(r'class="comment_body[^>]*>(.*?)</div>', response.text, re.DOTALL | re.IGNORECASE)
    if not posts:
        posts = re.findall(r'<div class="text[^>]*>(.*?)</div>', response.text, re.DOTALL | re.IGNORECASE)
        
    print(f"Found {len(posts)} posts. First post snippet:")
    if posts:
        text = re.sub(r'<[^>]+>', '', posts[0]).strip()
        print(text[:200])
except Exception as e:
    print("Error:", e)
