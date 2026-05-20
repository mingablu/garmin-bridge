"""
Garmin Bridge v6 - Microservico que conecta Garmin Connect ao n8n.
v6: Calendário com mes 0-indexed (API Garmin) e endpoint connect.garmin.com correto.
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

app = FastAPI(title="Garmin Bridge", version="6.0")
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
    return {"status": "ok", "version": "6.0", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/wellness/today")
def wellness_today(x_api_key: str = Header(None)):
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
    Calendario do Garmin via API direta.
    IMPORTANTE: API Garmin usa mes 0-indexed (janeiro=0, maio=4, dezembro=11).
    Traz treinos do TrainingPeaks sincronizados.
    """
    _auth(x_api_key)
    c = _get_client()
    now = datetime.now()
    year = now.year
    month_0indexed = now.month - 1  # Garmin: janeiro=0, maio=4, dezembro=11
    errors = []

    # Tentativa 1: garth com "connect" (connect.garmin.com) - mais provavel
    try:
        resp = c.garth.get(
            "connect",
            f"/calendar-service/year/{year}/month/{month_0indexed}"
        )
        data = resp.json() if hasattr(resp, "json") else resp
        if data:
            return {"source": "garth-connect", "year": year, "month_0idx": month_0indexed, **data}
    except Exception as e:
        errors.append(f"garth-connect: {e}")

    # Tentativa 2: connectapi com mes 0-indexed
    try:
        data = c.connectapi(f"/calendar-service/year/{year}/month/{month_0indexed}")
        if data:
            return {"source": "connectapi-0idx", "year": year, "month_0idx": month_0indexed, **data}
    except Exception as e:
        errors.append(f"connectapi-0idx: {e}")

    # Tentativa 3: mes 1-indexed (caso API aceite ambos)
    try:
        data = c.connectapi(f"/calendar-service/year/{year}/month/{now.month}")
        if data:
            return {"source": "connectapi-1idx", **data}
    except Exception as e:
        errors.append(f"connectapi-1idx: {e}")

    # Tentativa 4: endpoint alternativo de schedule
    try:
        start = now.strftime("%Y-%m-%d")
        end = (now + timedelta(days=14)).strftime("%Y-%m-%d")
        data = c.connectapi(f"/workout-service/schedule/{start}/{end}")
        if data:
            return {"source": "workout-schedule", "events": data if isinstance(data, list) else []}
    except Exception as e:
        errors.append(f"workout-schedule: {e}")

    # Fallback: workouts salvos
    try:
        workouts = c.get_workouts(0, 30)
        return {
            "source": "workouts-fallback",
            "workouts": workouts if isinstance(workouts, list) else [],
            "errors": errors,
        }
    except Exception as e:
        return {"source": "none", "workouts": [], "errors": errors + [str(e)]}
