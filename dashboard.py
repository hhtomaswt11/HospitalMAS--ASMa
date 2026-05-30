import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"

app = FastAPI(title="Hospital MAS Dashboard")

# Montar pasta static onde estará o index.html
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
async def read_index():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html, status_code=200)

@app.get("/api/state")
async def get_state():
    try:
        json_path = DATA_DIR / "dashboard.json"
        if json_path.exists():
            with json_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return data
    except Exception as e:
        return {"error": str(e)}
    # Fallback se o JSON ainda não existir
    return {
        "resources": {},
        "waitlist": {"routine": [], "emergency": []},
        "logs": [],
        "metrics": {"by_hospital": {"h1": {}, "h2": {}}, "events": []}
    }

if __name__ == "__main__":
    import uvicorn
    # Executa o uvicorn nativo (decoupled do spade)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error")
