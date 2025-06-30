
import os
import datetime
import pytz
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from dateutil.parser import parse

SCOPES = ['https://www.googleapis.com/auth/calendar']

def get_calendar_service():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            'credentials.json', SCOPES)
        creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('calendar', 'v3', credentials=creds)

def find_available_slots():
    service = get_calendar_service()
    now = datetime.datetime.utcnow().isoformat() + 'Z'
    events_result = service.events().list(
        calendarId='primary',
        timeMin=now,
        maxResults=50,
        singleEvents=True,
        orderBy='startTime').execute()
    events = events_result.get('items', [])

    week_days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
    tz = pytz.timezone("America/Mexico_City")
    today = datetime.datetime.now(tz).date()
    availability = {}

    for i in range(5):
        day = today + datetime.timedelta(days=i)
        slots = []
        for hour in range(9, 18):
            slot_start = tz.localize(datetime.datetime.combine(day, datetime.time(hour)))
            slot_end = slot_start + datetime.timedelta(minutes=30)
            conflict = any(
                parse(e['start'].get('dateTime', e['start'].get('date'))) < slot_end and
                parse(e['end'].get('dateTime', e['end'].get('date'))) > slot_start
                for e in events
            )
            if not conflict:
                slots.append(slot_start.strftime('%Y-%m-%d %H:%M'))
        if slots:
            availability[str(day)] = slots

    if availability:
        return availability
    else:
        return "No hay disponibilidad esta semana."

def create_event(summary, start_datetime, end_datetime):
    service = get_calendar_service()
    event = {
        'summary': summary,
        'start': {'dateTime': start_datetime.isoformat(), 'timeZone': 'America/Mexico_City'},
        'end': {'dateTime': end_datetime.isoformat(), 'timeZone': 'America/Mexico_City'},
    }
    created_event = service.events().insert(calendarId='primary', body=event).execute()
    return f"Evento creado: {created_event.get('htmlLink')}"
