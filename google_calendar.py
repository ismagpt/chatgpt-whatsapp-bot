# google_calendar.py
import os, datetime, pytz
from google.oauth2 import service_account
from googleapiclient.discovery import build

CREDENTIALS_FILE = "service_account.json"
SCOPES = ['https://www.googleapis.com/auth/calendar']
credentials = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)

CALENDAR_ID = os.environ.get("CALENDAR_ID", "zisma.watermc@gmail.com")  # muévelo a ENV
UTC = pytz.UTC

def _svc():
    return build("calendar", "v3", credentials=credentials)

def crear_evento(nombre, servicio, start_utc: datetime.datetime, dur_min=30, external_id=None):
    assert start_utc.tzinfo is not None, "start_utc debe ser aware (UTC)"
    end_utc = start_utc + datetime.timedelta(minutes=dur_min)
    body = {
        "summary": f"Cita dental - {nombre}",
        "description": f"Servicio: {servicio} (agendado automáticamente vía WhatsApp)",
        "start": {"dateTime": start_utc.isoformat(), "timeZone": "UTC"},
        "end":   {"dateTime": end_utc.isoformat(),   "timeZone": "UTC"},
        "extendedProperties": {"private": {"external_id": external_id or os.urandom(8).hex()}},
    }
    return _svc().events().insert(calendarId=CALENDAR_ID, body=body, sendUpdates="all").execute()

def hay_conflicto(start_utc: datetime.datetime, dur_min=30):
    assert start_utc.tzinfo is not None
    end_utc = start_utc + datetime.timedelta(minutes=dur_min)
    items = _svc().events().list(
        calendarId=CALENDAR_ID,
        timeMin=start_utc.isoformat(),
        timeMax=end_utc.isoformat(),
        singleEvents=True,
        orderBy="startTime"
    ).execute().get("items", [])
    return len(items) > 0

def obtener_horarios_disponibles(start_utc: datetime.datetime, dur_min=30, paso_min=15):
    """Devuelve opciones (strings legibles) el MISMO día local del start_utc."""
    from time_utils import same_day_window_utc, utc_to_local_str
    win_start, win_end = same_day_window_utc(start_utc)
    # Trae eventos del día
    evs = _svc().events().list(
        calendarId=CALENDAR_ID, timeMin=win_start.isoformat(), timeMax=win_end.isoformat(),
        singleEvents=True, orderBy="startTime"
    ).execute().get("items", [])
    busy = []
    for e in evs:
        s = e["start"].get("dateTime") or e["start"]["date"]
        f = e["end"].get("dateTime") or e["end"]["date"]
        sdt = datetime.datetime.fromisoformat(s.replace("Z","+00:00"))
        fdt = datetime.datetime.fromisoformat(f.replace("Z","+00:00"))
        busy.append((sdt, fdt))

    # Genera slots
    slots = []
    t = win_start
    step = datetime.timedelta(minutes=paso_min)
    dur  = datetime.timedelta(minutes=dur_min)

    def overlaps(a0,a1,b0,b1): return not (a1 <= b0 or b1 <= a0)

    while t + dur <= win_end:
        blocked = any(overlaps(t, t+dur, b0, b1) for (b0,b1) in busy)
        if not blocked:
            slots.append(t)
        t += step

    # Formatea en local (texto) y limita a 3–5 opciones
    return [utc_to_local_str(s) for s in slots[:5]]

def formatear_fecha_local_from_utc(dt_utc):
    from time_utils import utc_to_local_str
    return utc_to_local_str(dt_utc)
