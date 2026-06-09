import requests
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

r = requests.get('http://127.0.0.1:8080/', allow_redirects=False)
print(f"Root status: {r.status_code}")
print(f"Redirect to: {r.headers.get('location', 'none')}")

r2 = requests.get('http://127.0.0.1:8080/', allow_redirects=True)
has_chat = "AI客服" in r2.text
print(f"Chat page loaded: {has_chat}")
print(f"Final URL: {r2.url}")
