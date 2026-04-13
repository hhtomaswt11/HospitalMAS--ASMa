import os
import json
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Hospital MAS Dashboard")

# Montar pasta static onde estará o index.html
if not os.path.exists("static"):
    os.makedirs("static")
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_index():
    with open("static/index.html", "r", encoding="utf-8") as f:
        html = f.read()
    return HTMLResponse(content=html, status_code=200)

@app.get("/api/state")
async def get_state():
    try:
        if os.path.exists("data/dashboard.json"):
            with open("data/dashboard.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                return data
    except Exception as e:
        return {"error": str(e)}
    # Fallback se o JSON ainda não existir
    return {
        "resources": {},
        "waitlist": {"routine": [], "emergency": []},
        "logs": []
    }

if __name__ == "__main__":
    import uvicorn
    # Executa o uvicorn nativo (decoupled do spade)
    uvicorn.run("dashboard:app", host="0.0.0.0", port=8000, log_level="error")
