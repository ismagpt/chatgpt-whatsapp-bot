import os
import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Configuración
CREDENTIALS_FILE = "service_account.json"
SCOPES = ['https://www.googleapis.com/auth/calendar']
CALENDAR_ID = "zisma.watermc@gmail.com"

credentials = service_account.Credentials.from_service_account_file(
    CREDENTIALS_FILE, scopes=SCOPES
)

def esta_disponible(fecha, hora):
    """
    Verifica si hay un evento ya programado en ese día y hora exactos.
    """
    service = build("calendar", "v3", credentials=credentials)
    start_datetime = datetime.datetime.strptime(f"{fecha} {hora}", "%Y-%m-%d %H:%M")
    end_datetime = start_datetime + datetime.timedelta(minutes=30)

    eventos = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=start_datetime.isoformat() + "Z",
        timeMax=end_datetime.isoformat() + "Z",
        singleEvents=True,
        orderBy="startTime"
    ).execute()

    return len(eventos.get("items", [])) == 0

def sugerir_disponibles(fecha, hora="10:00"):
    """
    Sugiere horarios disponibles en el mismo día o días siguientes.
    """
    sugerencias = []
    base_date = datetime.datetime.strptime(f"{fecha} {hora}", "%Y-%m-%d %H:%M")
    service = build("calendar", "v3", credentials=credentials)

    for i in range(5):  # busca por 5 días
        dia = base_date.date() + datetime.timedelta(days=i)
        for h in range(9, 18):
            slot = datetime.datetime.combine(dia, datetime.time(h, 0))
            slot_end = slot + datetime.timedelta(minutes=30)

            eventos = service.events().list(
                calendarId=CALENDAR_ID,
                timeMin=slot.isoformat() + "Z",
                timeMax=slot_end.isoformat() + "Z",
                singleEvents=True,
                orderBy="startTime"
            ).execute()

            if len(eventos.get("items", [])) == 0:
                sugerencias.append(slot.strftime("%Y-%m-%d %H:%M"))

            if len(sugerencias) >= 3:
                return sugerencias
    return sugerencias

def crear_evento(nombre, fecha_str, hora_str):
    service = build("calendar", "v3", credentials=credentials)
    start_datetime = datetime.datetime.strptime(f"{fecha_str} {hora_str}", "%Y-%m-%d %H:%M")
    end_datetime = start_datetime + datetime.timedelta(minutes=30)

    evento = {
        "summary": f"Cita dental - {nombre}",
        "description": "Agendada por el asistente automático vía WhatsApp",
        "start": {
            "dateTime": start_datetime.isoformat(),
            "timeZone": "America/Mexico_City"
        },
        "end": {
            "dateTime": end_datetime.isoformat(),
            "timeZone": "America/Mexico_City"
        }
    }

    event = service.events().insert(calendarId=CALENDAR_ID, body=evento).execute()
    return f"✅ Evento creado: {event.get('htmlLink')}"
