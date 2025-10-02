# time_utils.py
from datetime import datetime
import pytz

TZ_LOCAL = pytz.timezone("America/Monterrey")  # tu zona local

def parse_local_to_utc(date_str: str) -> datetime:
    """Parsea texto del usuario en local y regresa datetime en UTC (aware)."""
    from dateutil.parser import parse
    naive = parse(date_str, fuzzy=True)              # sin tz
    local_dt = TZ_LOCAL.localize(datetime.combine(naive.date(), naive.time()))
    return local_dt.astimezone(pytz.UTC)

def utc_now():
    return datetime.now(pytz.UTC)

def utc_to_local_str(utc_dt: datetime) -> str:
    """Formatea una fecha UTC a string legible en local."""
    local = utc_dt.astimezone(TZ_LOCAL)
    return local.strftime("%A %d de %B a las %I:%M %p").capitalize()

def same_day_window_utc(utc_dt: datetime, start_hour=9, end_hour=18):
    """Devuelve ventana [inicio, fin] del día local del utc_dt, en UTC."""
    local_day = utc_dt.astimezone(TZ_LOCAL).date()
    start_local = TZ_LOCAL.localize(datetime.combine(local_day, datetime.min.time())).replace(hour=start_hour, minute=0)
    end_local   = TZ_LOCAL.localize(datetime.combine(local_day, datetime.min.time())).replace(hour=end_hour,   minute=0)
    return start_local.astimezone(pytz.UTC), end_local.astimezone(pytz.UTC)
