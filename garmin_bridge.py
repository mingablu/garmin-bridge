"""
Garmin Bridge v5 - Microservico que conecta Garmin Connect ao n8n.
v5: Calendário via API direta do Garmin (traz treinos do TrainingPeaks).
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

app = FastAPI(title="Garmin Bridge", version="5.0")
_client = None


def _get_client():
    global _client
    if _client is None:
        _client = Garmin(email=GARMIN_EMAIL, password=GARMIN_PASSWORD)
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
    return {"status": "ok", "version": "5.0", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/wellness/today")
def wellness_today(x_api_key: str = Header(None)):
    """
    Wellness do dia.
    Sono/HRV buscados de ONTEM (Garmin armazena dados da noite na data anterior).
    """
    _auth(x_api_key)
    c = _get_client()
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    return {
        "date": today,
        "date_sleep": yesterday,
        "body_battery": c.get_body_battery(today),
        "hrv": c.get_hrv_data(yesterday),
        "sleep": c.get_sleep_data(yesterday),
        "stress": c.get_stress_data(today),
        "steps": c.get_steps_data(today),
        "rhr": c.get_rhr_day(yesterday),
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


@app.get("/calendar/week")
def get_calendar_week(x_api_key: str = Header(None)):
    """
    Calendário do Garmin via API direta (garth).
    Traz treinos programados do TrainingPeaks e outros planos.
    """
    _auth(x_api_key)
    c = _get_client()
    now = datetime.now()
    year = now.year
    month = now.month

    # Tenta API direta do calendario Garmin
    errors = []

    # Tentativa 1: connectapi direto
    try:
        data = c.connectapi(f"/calendar-service/year/{year}/month/{month}")
        if data:
            return {"source": "calendar-service", "year": year, "month": month, **data}
    except Exception as e:
        errors.append(f"connectapi: {e}")

    # Tentativa 2: garth get direto
    try:
        resp = c.garth.get("connectapi", f"/calendar-service/year/{year}/month/{month}")
        data = resp.json() if hasattr(resp, 'json') else resp
        if data:
            return {"source": "garth-calendar", "year": year, "month": month, **data}
    except Exception as e:
        errors.append(f"garth-calendar: {e}")

    # Tentativa 3: endpoint alternativo
    try:
        data = c.connectapi(f"/wellness-service/wellness/calendarItems/{year}-{month:02d}-01/{year}-{month:02d}-31")
        if data:
            return {"source": "wellness-calendar", **data}
    except Exception as e:
        errors.append(f"wellness-calendar: {e}")

    # Fallback: workouts salvos
    try:
        workouts = c.get_workouts(0, 30)
        return {
            "source": "workouts-fallback",
            "workouts": workouts if isinstance(workouts, list) else [],
            "errors": errors,
            "note": "Calendario nao acessivel, retornando workouts salvos"
        }
    except Exception as e:
        return {"source": "none", "workouts": [], "errors": errors + [str(e)]}
