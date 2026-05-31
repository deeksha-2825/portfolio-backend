import httpx
try:
    httpx.get("http://localhost:8000/reset_limit")
except:
    pass
