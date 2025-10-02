from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from openai import OpenAI
import os
import datetime
import pytz
from dateutil.parser import parse
import json

from google_calendar import crear_evento, hay_conflicto, obtener_horarios_disponibles, formatear_fecha
from db import init_db, SessionLocal, Conversation, Message
init_db()

app = Flask(__name__)
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

@app.route("/webhook", methods=["POST"])
def whatsapp_reply():
    db = SessionLocal()  # ← sesión por petición
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

        # 2) Cargar estado desde DB (JSON)
        try:
            estado = json.loads(conv.state) if isinstance(conv.state, str) else (conv.state or {})
        except Exception:
            estado = {}

        # 3) Guardar mensaje entrante
        db.add(Message(conversation_id=conv.id, direction="in", body=mensaje))
        db.commit()

        # 4) Tu lógica de flujo (igual que ya tenías)
        response = MessagingResponse()
        msg = response.message()

        if estado.get("esperando_confirmacion_fecha"):
            if "sí" in mensaje.lower() or "si" in mensaje.lower():
                estado["fecha"] = estado["fecha_sugerida"]
            else:
                out_text = "❌ Entendido. No se agendó la cita. Si deseas intentarlo con otra fecha, escribe 'agendar cita'."
                msg.body(out_text)
                # guardar salida + reset estado
                db.add(Message(conversation_id=conv.id, direction="out", body=out_text))
                conv.state = json.dumps({})
                conv.updated_at = datetime.datetime.utcnow()
                db.commit()
                return str(response)

        if all(k in estado for k in ("nombre", "servicio", "fecha")):
            fecha_obj = estado["fecha"]

            if hay_conflicto(fecha_obj):
                sugerencias = obtener_horarios_disponibles(fecha_obj)
                if sugerencias:
                    opciones = ", ".join(sugerencias[:4])  # no satures
                    out_text = f"⚠️ Ese horario ya está ocupado. Estos son otros horarios disponibles el mismo día:\n{opciones}"
                else:
                    out_text = "❌ Lo siento, no hay horarios disponibles ese día. Intenta con otra fecha."
                msg.body(out_text)
                db.add(Message(conversation_id=conv.id, direction="out", body=out_text))
                conv.state = json.dumps({})
                conv.updated_at = datetime.datetime.utcnow()
                db.commit()
                return str(response)

            crear_evento(estado["nombre"], estado["servicio"], fecha_obj)
            texto_fecha = formatear_fecha(fecha_obj)
            out_text = f"✅ Cita agendada para {estado['nombre']} el {texto_fecha}. ¡Gracias!"
            msg.body(out_text)
            db.add(Message(conversation_id=conv.id, direction="out", body=out_text))
            conv.state = json.dumps({})
            conv.updated_at = datetime.datetime.utcnow()
            db.commit()
            return str(response)

        elif "nombre" not in estado:
            if "cita" in mensaje.lower() and "agendar" in mensaje.lower():
                estado = {"esperando_nombre": True}
                out_text = "¡Perfecto! ¿Podrías darme tu nombre completo?"
                msg.body(out_text)
                db.add(Message(conversation_id=conv.id, direction="out", body=out_text))
            else:
                chat_response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": "Eres un asistente para agendar citas dentales y responder dudas comunes."},
                        {"role": "user", "content": mensaje}
                    ]
                )
                out_text = (chat_response.choices[0].message.content or "").strip()
                msg.body(out_text)
                db.add(Message(conversation_id=conv.id, direction="out", body=out_text))

        elif estado.get("esperando_nombre"):
            estado["nombre"] = mensaje
            estado.pop("esperando_nombre")
            estado["esperando_servicio"] = True
            out_text = f"Gracias, {mensaje}. ¿Qué tipo de servicio deseas? (ej: limpieza, revisión, dolor de muela, etc.)"
            msg.body(out_text)
            db.add(Message(conversation_id=conv.id, direction="out", body=out_text))

        elif estado.get("esperando_servicio"):
            estado["servicio"] = mensaje
            estado.pop("esperando_servicio")
            estado["esperando_fecha"] = True
            out_text = "¿En qué día y hora deseas la cita? Por favor responde con el formato: '3 julio 4pm'"
            msg.body(out_text)
            db.add(Message(conversation_id=conv.id, direction="out", body=out_text))

        elif estado.get("esperando_fecha"):
            try:
                tz = pytz.timezone("America/Mexico_City")  # luego cambiamos a America/Monterrey
                fecha_ingresada = parse(mensaje, fuzzy=True)
                ahora = datetime.datetime.now(tz)

                fecha_obj = tz.localize(datetime.datetime.combine(
                    fecha_ingresada.date(),
                    fecha_ingresada.time()
                ))

                if fecha_obj < ahora:
                    fecha_obj = fecha_obj.replace(year=ahora.year + 1)
                    estado["fecha_sugerida"] = fecha_obj
                    estado["esperando_confirmacion_fecha"] = True
                    texto_sugerida = formatear_fecha(fecha_obj)
                    out_text = f"⚠️ La fecha que proporcionaste ya pasó este año. ¿Quieres agendar la cita para el {texto_sugerida}? (responde sí o no)"
                else:
                    estado["fecha"] = fecha_obj
                    out_text = "Perfecto, estoy revisando disponibilidad…"

                msg.body(out_text)
                db.add(Message(conversation_id=conv.id, direction="out", body=out_text))

            except Exception:
                out_text = "❌ No pude entender la fecha. Por favor usa el formato: '3 julio 4pm'"
                msg.body(out_text)
                db.add(Message(conversation_id=conv.id, direction="out", body=out_text))
                # persistimos igual y salimos
                conv.state = json.dumps(estado)
                conv.updated_at = datetime.datetime.utcnow()
                db.commit()
                return str(response)

        # 5) Persistir estado actualizado y cerrar sesión
        conv.state = json.dumps(estado)
        conv.updated_at = datetime.datetime.utcnow()
        db.commit()
        return str(response)

    finally:
        db.close()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
