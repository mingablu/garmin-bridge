"""
Garmin Bridge - Microservico que conecta Garmin Connect ao n8n.
Expoe os dados do Garmin como API REST para o Coach Virtual consumir.
"""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import FastAPI, HTTPException, Header
from garminconnect import Garmin

TOKEN_DIR = Path("/tmp/garmin_tokens")
TOKEN_DIR.mkdir(parents=True, exist_ok=True)

GARMIN_EMAIL = os.environ["GARMIN_EMAIL"]
GARMIN_PASSWORD = os.environ["GARMIN_PASSWORD"]
API_KEY = os.environ["BRIDGE_API_KEY"]

app = FastAPI(title="Garmin Bridge", version="1.0")
_client = None


def _get_client():
    """Login com cache de token (renova automaticamente quando expira)."""
    global _client
    if _client is None:
        _client = Garmin(
            email=GARMIN_EMAIL,
            password=GARMIN_PASSWORD,
        )
        try:
            _client.login(tokenstore=str(TOKEN_DIR))
        except Exception:
            _client.login()
            _client.garth.dump(str(TOKEN_DIR))
    return _client


def _auth(api_key):
    if api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/wellness/today")
def wellness_today(x_api_key: str = Header(None)):
    _auth(x_api_key)
    c = _get_client()
    today = datetime.now().strftime("%Y-%m-%d")
    return {
        "date": today,
        "body_battery": c.get_body_battery(today),
        "hrv": c.get_hrv_data(today),
        "sleep": c.get_sleep_data(today),
        "stress": c.get_stress_data(today),
        "steps": c.get_steps_data(today),
        "rhr": c.get_rhr_day(today),
    }


@app.get("/wellness/range")
def wellness_range(days: int = 7, x_api_key: str = Header(None)):
    _auth(x_api_key)
    c = _get_client()
    end = datetime.now()
    start = end - timedelta(days=days)
    return {
        "from": start.strftime("%Y-%m-%d"),
        "to": end.strftime("%Y-%m-%d"),
        "body_battery_events": c.get_body_battery_events(
            start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
        ),
        "sleep_history": [
            c.get_sleep_data((end - timedelta(days=i)).strftime("%Y-%m-%d"))
            for i in range(days)
        ],
    }


@app.get("/training/status")
def training_status(x_api_key: str = Header(None)):
    _auth(x_api_key)
    c = _get_client()
    today = datetime.now().strftime("%Y-%m-%d")
    return {
        "training_status": c.get_training_status(today),
        "training_readiness": c.get_training_readiness(today),
        "max_metrics": c.get_max_metrics(today),
        "race_predictions": c.get_race_predictions(),
    }


@app.get("/activities/recent")
def activities_recent(limit: int = 10, x_api_key: str = Header(None)):
    _auth(x_api_key)
    c = _get_client()
    return c.get_activities(0, limit)


@app.get("/activities/{activity_id}")
def activity_detail(activity_id: int, x_api_key: str = Header(None)):
    _auth(x_api_key)
    c = _get_client()
    return {
        "summary": c.get_activity(activity_id),
        "details": c.get_activity_details(activity_id),
        "splits": c.get_activity_splits(activity_id),
        "hr_zones": c.get_activity_hr_in_timezones(activity_id),
    }


@app.get("/activities/since")
def activities_since(iso: str, x_api_key: str = Header(None)):
    """Retorna atividades a partir de um timestamp ISO."""
    _auth(x_api_key)
    c = _get_client()
    raw = c.get_activities(0, 20)
    cutoff = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    filtered = [
        a for a in raw
        if datetime.fromisoformat(a["startTimeGMT"].replace(" ", "T") + "+00:00") > cutoff
    ]
    return filtered
