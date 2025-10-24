# app.py
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from twilio.request_validator import RequestValidator
from openai import OpenAI
import os
import json
import datetime
import pytz
from dateutil.parser import parse
from dateparser import parse as dp_parse
from babel.dates import format_datetime

# --- Módulos propios ---
from google_calendar import (
    crear_evento,
    hay_conflicto,
    obtener_horarios_disponibles,
    formatear_fecha_local_from_utc as formatear_fecha  # recibe UTC y devuelve string local
)
from db import init_db, SessionLocal, Conversation, Message

# =======================
# Configuración base
# =======================
SESSION_TTL_MIN = 120  # 2 horas

init_db()  # crea tablas si no existen
app = Flask(__name__)

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
client = OpenAI(api_key=OPENAI_API_KEY)

# Twilio signature (opcional pero recomendado)
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
validator = RequestValidator(TWILIO_AUTH_TOKEN) if TWILIO_AUTH_TOKEN else None

# Zonas horarias
TZ_LOCAL = pytz.timezone("America/Monterrey")  # para parsear entrada y mostrar al usuario
UTC = pytz.UTC


# =======================
# Utils de transcript + extracción con IA
# =======================
def get_recent_transcript(db, conv_id: int, limit: int = 10) -> str:
    rows = (
        db.query(Message.direction, Message.body)
          .filter(Message.conversation_id == conv_id)
          .order_by(Message.id.desc())
          .limit(limit)
          .all()
    )
    lines = []
    for direction, body in reversed(rows):
        role = "USER" if direction == "in" else "BOT"
        lines.append(f"{role}: {body}")
    return "\n".join(lines)


def extract_slots_with_ai(transcript: str) -> dict:
    """
    Devuelve dict parcial con campos si aparecen en el historial:
      { "nombre": str|None, "servicio": str|None, "fecha_texto": str|None }
    """
    sys = (
        "Eres un extractor de datos para reservar citas. "
        "Devuelve SOLO un JSON con posibles campos: "
        '{"nombre": string|null, "servicio": string|null, "fecha_texto": string|null}. '
        "No inventes; si no estás seguro, usa null."
    )

    chat = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": sys},
            {"role": "user", "content": transcript}
        ],
        temperature=0.0,
    )
    try:
        data = json.loads(chat.choices[0].message.content or "{}")
        if not isinstance(data, dict):
            return {}
        return {
            "nombre": data.get("nombre"),
            "servicio": data.get("servicio"),
            "fecha_texto": data.get("fecha_texto"),
        }
    except Exception:
        return {}


# =======================
# Helpers de tiempo
# =======================
def parse_local_to_utc_iso(texto_fecha: str) -> str:
    """
    Parsea texto libre (ES/EN) respetando zona local y ahora.
    Ej.: 'mañana a la 1', 'pasado mañana 4pm', '3 julio 4pm'
    Devuelve ISO8601 en UTC (string).
    """
    now_local = datetime.datetime.now(TZ_LOCAL)

    dt_local = dp_parse(
        texto_fecha,
        languages=["es", "en"],
        settings={
            "TIMEZONE": "America/Monterrey",
            "RETURN_AS_TIMEZONE_AWARE": True,
            "RELATIVE_BASE": now_local,
            "PREFER_DATES_FROM": "future",   # si hoy ya pasó esa hora, usa el próximo
            "PREFER_DAY_OF_MONTH": "current",
        },
    )
    if not dt_local:
        # fallback: intenta con dateutil (podría fallar en ES)
        naive = parse(texto_fecha, fuzzy=True)
        dt_local = TZ_LOCAL.localize(datetime.datetime.combine(naive.date(), naive.time()))

    # Heurística: si no trae am/pm y cae fuera de horario, ajústalo a PM típico
    # (opcional — evita que 'a la 1' termine en 1:00 am)
    if dt_local.hour < 9:  # horario típico de clínica 9-18
        dt_local = dt_local.replace(hour=13, minute=0)

    return dt_local.astimezone(UTC).isoformat()



def iso_to_utc_dt(iso_str: str) -> datetime.datetime:
    """Convierte string ISO (posible 'Z') a datetime aware en UTC."""
    return datetime.datetime.fromisoformat(iso_str.replace("Z", "+00:00")).astimezone(UTC)


def utc_to_local_display(utc_dt: datetime.datetime) -> str:
    """
    Muestra la fecha en español correctamente, independiente del locale del servidor.
    """
    local = utc_dt.astimezone(TZ_LOCAL)
    # Ejemplo: "viernes 25 de octubre a las 1:00 p. m."
    return format_datetime(local, "EEEE d 'de' MMMM 'a las' h:mm a", locale="es_MX").capitalize()


# =======================
# Seguridad Twilio (verificación de firma)
# =======================
@app.before_request
def validate_twilio_signature():
    if validator and request.path == "/webhook":
        signature = request.headers.get("X-Twilio-Signature", "")
        url = request.url  # Debe ser EXACTAMENTE la URL pública registrada en Twilio
        params = request.form.to_dict()
        if not validator.validate(url, params, signature):
            return ("Forbidden", 403)


# =======================
# Webhook principal
# =======================
@app.route("/webhook", methods=["POST"])
def whatsapp_reply():
    db = SessionLocal()
    try:
        numero = request.values.get("From", "")                 # "whatsapp:+52..."
        mensaje = (request.values.get("Body", "") or "").strip()

        # 1) Buscar o crear conversación
        conv = db.query(Conversation).filter_by(user_phone=numero).first()
        if not conv:
            conv = Conversation(user_phone=numero, state="{}")
            db.add(conv)
            db.commit()
            db.refresh(conv)

        # 1.1) Expirar el estado si pasaron > 2 horas sin actividad (usa naive UTC para comparar)
        now_utc_naive = datetime.datetime.utcnow()
        if conv.updated_at and (now_utc_naive - conv.updated_at).total_seconds() > SESSION_TTL_MIN * 60:
            conv.state = "{}"
            db.commit()

        # 2) Cargar estado JSON
        try:
            estado = json.loads(conv.state) if isinstance(conv.state, str) else (conv.state or {})
        except Exception:
            estado = {}

        # 3) Registrar mensaje entrante
        db.add(Message(conversation_id=conv.id, direction="in", body=mensaje))
        db.commit()

        # 3.5) Enriquecer estado con IA (multi-idioma, sin keywords)
        transcript = get_recent_transcript(db, conv.id, limit=10)
        slots = extract_slots_with_ai(transcript)
        if slots.get("nombre") and not estado.get("nombre"):
            estado["nombre"] = slots["nombre"]
        if slots.get("servicio") and not estado.get("servicio"):
            estado["servicio"] = slots["servicio"]
        if slots.get("fecha_texto") and not estado.get("fecha_utc"):
            try:
                estado["fecha_utc"] = parse_local_to_utc_iso(slots["fecha_texto"])
            except Exception:
                pass  # si no parsea, seguimos con el flujo normal

        # 4) Construir respuesta
        twiml = MessagingResponse()
        msg = twiml.message()

        # --- Confirmación de fecha sugerida (cuando usuario eligió una pasada) ---
        if estado.get("esperando_confirmacion_fecha"):
            if "sí" in mensaje.lower() or "si" in mensaje.lower():
                estado["fecha_utc"] = estado["fecha_sugerida_utc"]  # ISO UTC
                estado.pop("esperando_confirmacion_fecha", None)
            else:
                out = "❌ Entendido. No se agendó la cita. Si deseas intentarlo con otra fecha, escribe 'agendar cita'."
                msg.body(out)
                db.add(Message(conversation_id=conv.id, direction="out", body=out))
                conv.state = json.dumps({})
                conv.updated_at = datetime.datetime.utcnow()
                db.commit()
                return str(twiml)

        # --- Caso listo para agendar: tenemos nombre, servicio y fecha_utc ---
        if all(k in estado for k in ("nombre", "servicio", "fecha_utc")):
            start_utc = iso_to_utc_dt(estado["fecha_utc"])

            # google_calendar.py ya opera en UTC: no conviertas a otras TZ
            if hay_conflicto(start_utc):
                sugerencias = obtener_horarios_disponibles(start_utc)
                if sugerencias:
                    listado = "\n- " + "\n- ".join(sugerencias[:5])
                    out = f"⚠️ Ese horario ya está ocupado. Opciones el mismo día:{listado}"
                else:
                    out = "❌ Lo siento, no hay horarios disponibles ese día. Intenta con otra fecha."
                msg.body(out)
                db.add(Message(conversation_id=conv.id, direction="out", body=out))
                # No limpiar estado: el usuario puede dar otra hora
                conv.state = json.dumps(estado)
                conv.updated_at = datetime.datetime.utcnow()
                db.commit()
                return str(twiml)

            # Crear evento en Calendar (UTC)
            crear_evento(estado["nombre"], estado["servicio"], start_utc)

            # Respuesta al usuario (bonita en local)
            out = f"✅ Cita agendada para {estado['nombre']} el {utc_to_local_display(start_utc)}. ¡Gracias!"
            msg.body(out)
            db.add(Message(conversation_id=conv.id, direction="out", body=out))
            # Aquí SÍ limpiamos estado (flujo terminado)
            conv.state = json.dumps({})
            conv.updated_at = datetime.datetime.utcnow()
            db.commit()
            return str(twiml)

        # --- Arranque del flujo SIN palabras clave ---
        elif "nombre" not in estado:
            estado["esperando_nombre"] = True
            out = "¡Perfecto! ¿Podrías darme tu nombre completo?"
            msg.body(out)
            db.add(Message(conversation_id=conv.id, direction="out", body=out))

        # --- Pedir servicio ---
        elif estado.get("esperando_nombre"):
            estado["nombre"] = mensaje
            estado.pop("esperando_nombre")
            estado["esperando_servicio"] = True
            out = f"Gracias, {mensaje}. ¿Qué tipo de servicio deseas? (ej: limpieza, revisión, dolor de muela, etc.)"
            msg.body(out)
            db.add(Message(conversation_id=conv.id, direction="out", body=out))

        # --- Pedir fecha/hora ---
        elif estado.get("esperando_servicio"):
            estado["servicio"] = mensaje
            estado.pop("esperando_servicio")
            estado["esperando_fecha"] = True
            out = "¿En qué día y hora deseas la cita? Puedes escribirlo libremente (ej.: '3 julio 4pm')."
            msg.body(out)
            db.add(Message(conversation_id=conv.id, direction="out", body=out))

        # --- Parsear la fecha del usuario ---
        elif estado.get("esperando_fecha"):
            try:
                iso_utc = parse_local_to_utc_iso(mensaje)   # guardamos ISO en UTC (string)
                parsed_utc = iso_to_utc_dt(iso_utc)
                now_utc_aware = datetime.datetime.now(UTC)  # aware, para comparar con parsed_utc (aware)

                if parsed_utc < now_utc_aware:
                    # Sugerir mismo día/hora del próximo año (simple)
                    next_year = parsed_utc.replace(year=now_utc_aware.year + 1)
                    estado["fecha_sugerida_utc"] = next_year.isoformat()
                    estado["esperando_confirmacion_fecha"] = True
                    out = f"⚠️ Esa fecha ya pasó este año. ¿Agendo el {utc_to_local_display(next_year)}? (sí/no)"
                else:
                    estado["fecha_utc"] = iso_utc
                    out = "Perfecto, estoy revisando disponibilidad…"
                msg.body(out)
                db.add(Message(conversation_id=conv.id, direction="out", body=out))

            except Exception:
                out = "❌ No pude entender la fecha. Por favor usa un formato como: '3 julio 4pm'"
                msg.body(out)
                db.add(Message(conversation_id=conv.id, direction="out", body=out))
                conv.state = json.dumps(estado)
                conv.updated_at = datetime.datetime.utcnow()
                db.commit()
                return str(twiml)

        # 5) Persistir estado actualizado y responder
        conv.state = json.dumps(estado)
        conv.updated_at = datetime.datetime.utcnow()
        db.commit()
        return str(twiml)

    finally:
        db.close()


# =======================
# Run local
# =======================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
