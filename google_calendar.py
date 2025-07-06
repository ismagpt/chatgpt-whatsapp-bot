import os
import datetime
import pytz
from google.oauth2 import service_account
from googleapiclient.discovery import build

CREDENTIALS_FILE = "service_account.json"
SCOPES = ['https://www.googleapis.com/auth/calendar']

credentials = service_account.Credentials.from_service_account_file(
    CREDENTIALS_FILE, scopes=SCOPES
)

CALENDAR_ID = "zisma.watermc@gmail.com"

def crear_evento(nombre, servicio, fecha_obj):
    service = build("calendar", "v3", credentials=credentials)

    start_datetime = fecha_obj
    end_datetime = start_datetime + datetime.timedelta(minutes=30)

    evento = {
        "summary": f"Cita dental - {nombre}",
        "description": f"Servicio: {servicio} (agendado automáticamente vía WhatsApp)",
        "start": {
            "dateTime": start_datetime.isoformat(),
            "timeZone": "America/Mexico_City"
        },
        "end": {
            "dateTime": end_datetime.isoformat(),
            "timeZone": "America/Mexico_City"
        }
    }

    return service.events().insert(calendarId=CALENDAR_ID, body=evento).execute()

def hay_conflicto(fecha_obj):
    service = build("calendar", "v3", credentials=credentials)
    inicio = fecha_obj.isoformat()
    fin = (fecha_obj + datetime.timedelta(minutes=30)).isoformat()

    eventos = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=inicio,
        timeMax=fin,
        singleEvents=True,
        orderBy="startTime"
    ).execute().get("items", [])

    return len(eventos) > 0

def obtener_horarios_disponibles(fecha_obj):
    tz = pytz.timezone("America/Mexico_City")
    fecha = fecha_obj.date()
    service = build("calendar", "v3", credentials=credentials)

    inicio = tz.localize(datetime.datetime.combine(fecha, datetime.time(9, 0)))
    fin = tz.localize(datetime.datetime.combine(fecha, datetime.time(18, 0)))

    eventos = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=inicio.isoformat(),
        timeMax=fin.isoformat(),
        singleEvents=True,
        orderBy="startTime"
    ).execute().get("items", [])

    ocupados = [
        datetime.datetime.fromisoformat(event["start"]["dateTime"]).time()
        for event in eventos if "dateTime" in event["start"]
    ]

    disponibles = []
    for hora in range(9, 18):
        t = datetime.time(hora, 0)
        if t not in ocupados:
            disponibles.append(t.strftime("%I:%M %p"))

    return disponibles

def formatear_fecha(fecha_obj):
    return fecha_obj.strftime("%A %d de %B a las %I:%M %p").capitalize()
