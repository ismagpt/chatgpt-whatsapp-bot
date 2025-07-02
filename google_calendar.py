import os
import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Nombre del archivo de credenciales (debes haberlo subido en Render)
CREDENTIALS_FILE = "service_account.json"

# Define los alcances necesarios
SCOPES = ['https://www.googleapis.com/auth/calendar']

# Carga las credenciales desde el archivo JSON
credentials = service_account.Credentials.from_service_account_file(
    CREDENTIALS_FILE, scopes=SCOPES
)

# Usa el calendario principal del usuario que compartió su calendario con la cuenta de servicio
CALENDAR_ID = "zisma.watermc@gmail.com"

def crear_evento(nombre, fecha_str="2025-07-04", hora_str="10:00"):
    """
    Crea un evento en Google Calendar para el paciente con nombre `nombre`
    en la fecha y hora especificadas (por defecto: 4 de julio 2025 a las 10am).
    """
    service = build("calendar", "v3", credentials=credentials)

    # Construye la hora de inicio y fin
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
    print(f"✅ Evento creado: {event.get('htmlLink')}")
    return event
