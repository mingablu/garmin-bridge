"""
Garmin Bridge v2 - Microservico que conecta Garmin Connect ao n8n.
Expoe dados do Garmin como API REST para o Coach Virtual consumir.
Inclui: wellness, training status, atividades, workouts programados, calendario.
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

app = FastAPI(title="Garmin Bridge", version="2.0")
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
    return {"status": "ok", "version": "2.0", "time": datetime.now(timezone.utc).isoformat()}


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


# ============================================
# NOVOS ENDPOINTS v2 — Treinos Programados
# ============================================

@app.get("/workouts")
def get_workouts(limit: int = 20, x_api_key: str = Header(None)):
    """Lista workouts salvos/programados no Garmin Connect."""
    _auth(x_api_key)
    c = _get_client()
    try:
        workouts = c.get_workouts(0, limit)
        return {"workouts": workouts}
    except Exception as e:
        return {"workouts": [], "error": str(e)}


@app.get("/calendar/month")
def get_calendar_month(year: int = None, month: int = None, x_api_key: str = Header(None)):
    """Calendario mensal do Garmin (treinos programados, atividades, eventos)."""
    _auth(x_api_key)
    c = _get_client()
    now = datetime.now()
    y = year or now.year
    m = month or now.month
    try:
        cal = c.get_calendar(y, m)
        return {"year": y, "month": m, "calendar": cal}
    except Exception as e:
        return {"year": y, "month": m, "calendar": [], "error": str(e)}


@app.get("/calendar/today")
def get_calendar_today(x_api_key: str = Header(None)):
    """Retorna eventos do calendario Garmin para hoje (treinos programados do dia)."""
    _auth(x_api_key)
    c = _get_client()
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    try:
        cal = c.get_calendar(now.year, now.month)
        # Filtra eventos de hoje
        today_events = []
        if isinstance(cal, list):
            for item in cal:
                item_date = item.get("date", "") or item.get("startDate", "") or ""
                if today_str in str(item_date):
                    today_events.append(item)
        elif isinstance(cal, dict):
            items = cal.get("calendarItems", []) or cal.get("items", []) or []
            for item in items:
                item_date = item.get("date", "") or item.get("startDate", "") or ""
                if today_str in str(item_date):
                    today_events.append(item)
        return {"date": today_str, "events": today_events, "total": len(today_events)}
    except Exception as e:
        return {"date": today_str, "events": [], "total": 0, "error": str(e)}


@app.get("/calendar/week")
def get_calendar_week(x_api_key: str = Header(None)):
    """Retorna eventos do calendario Garmin para os proximos 7 dias."""
    _auth(x_api_key)
    c = _get_client()
    now = datetime.now()
    today = now.date()
    week_end = today + timedelta(days=7)
    try:
        # Pode precisar de 2 meses se estiver no fim do mes
        months_needed = {now.month}
        if week_end.month != now.month:
            months_needed.add(week_end.month)

        all_events = []
        for m in months_needed:
            y = now.year if m >= now.month else now.year + 1
            cal = c.get_calendar(y, m)
            if isinstance(cal, list):
                all_events.extend(cal)
            elif isinstance(cal, dict):
                items = cal.get("calendarItems", []) or cal.get("items", []) or []
                all_events.extend(items)

        # Filtra proximos 7 dias
        week_events = []
        for item in all_events:
            item_date_str = item.get("date", "") or item.get("startDate", "") or ""
            try:
                if isinstance(item_date_str, str) and len(item_date_str) >= 10:
                    item_date = datetime.strptime(item_date_str[:10], "%Y-%m-%d").date()
                    if today <= item_date <= week_end:
                        week_events.append(item)
            except (ValueError, TypeError):
                continue

        # Ordena por data
        week_events.sort(key=lambda x: str(x.get("date", "") or x.get("startDate", "")))

        return {
            "from": today.isoformat(),
            "to": week_end.isoformat(),
            "events": week_events,
            "total": len(week_events),
        }
    except Exception as e:
        return {
            "from": today.isoformat(),
            "to": week_end.isoformat(),
            "events": [],
            "total": 0,
            "error": str(e),
        }


@app.get("/training/plan")
def get_training_plan(x_api_key: str = Header(None)):
    """Retorna plano de treino ativo (se houver)."""
    _auth(x_api_key)
    c = _get_client()
    try:
        plans = c.get_training_plan_list()
        return {"plans": plans}
    except Exception as e:
        return {"plans": [], "error": str(e)}
