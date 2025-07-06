from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from openai import OpenAI
import os
import datetime
import pytz
from dateutil.parser import parse
from google_calendar import crear_evento, hay_conflicto, obtener_horarios_disponibles, formatear_fecha

app = Flask(__name__)
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
conversaciones = {}

@app.route("/webhook", methods=["POST"])
def whatsapp_reply():
    numero = request.values.get("From", "")
    mensaje = request.values.get("Body", "").strip()
    response = MessagingResponse()
    msg = response.message()

    estado = conversaciones.get(numero, {})

    if estado.get("esperando_confirmacion_fecha"):
        if "sí" in mensaje.lower() or "si" in mensaje.lower():
            estado["fecha"] = estado["fecha_sugerida"]
        else:
            msg.body("❌ Entendido. No se agendó la cita. Si deseas intentarlo con otra fecha, escribe 'agendar cita'.")
            conversaciones.pop(numero)
            return str(response)

    if all(k in estado for k in ("nombre", "servicio", "fecha")):
        fecha_obj = estado["fecha"]

        if hay_conflicto(fecha_obj):
            sugerencias = obtener_horarios_disponibles(fecha_obj)
            if sugerencias:
                opciones = ", ".join(sugerencias)
                msg.body(f"⚠️ Ese horario ya está ocupado. Estos son otros horarios disponibles el mismo día:\n{opciones}")
            else:
                msg.body("❌ Lo siento, no hay horarios disponibles ese día. Intenta con otra fecha.")
            conversaciones.pop(numero)
            return str(response)

        crear_evento(estado["nombre"], estado["servicio"], fecha_obj)
        texto_fecha = formatear_fecha(fecha_obj)
        msg.body(f"✅ Cita agendada para {estado['nombre']} el {texto_fecha}. ¡Gracias!")
        conversaciones.pop(numero)

    elif "nombre" not in estado:
        if "cita" in mensaje.lower() and "agendar" in mensaje.lower():
            conversaciones[numero] = {"esperando_nombre": True}
            msg.body("¡Perfecto! ¿Podrías darme tu nombre completo?")
        else:
            chat_response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "Eres un asistente para agendar citas dentales y responder dudas comunes."},
                    {"role": "user", "content": mensaje}
                ]
            )
            respuesta = chat_response.choices[0].message.content.strip()
            msg.body(respuesta)

    elif estado.get("esperando_nombre"):
        estado["nombre"] = mensaje
        estado.pop("esperando_nombre")
        estado["esperando_servicio"] = True
        msg.body(f"Gracias, {mensaje}. ¿Qué tipo de servicio deseas? (ej: limpieza, revisión, dolor de muela, etc.)")

    elif estado.get("esperando_servicio"):
        estado["servicio"] = mensaje
        estado.pop("esperando_servicio")
        estado["esperando_fecha"] = True
        msg.body("¿En qué día y hora deseas la cita? Por favor responde con el formato: '3 julio 4pm'")

    elif estado.get("esperando_fecha"):
        try:
            tz = pytz.timezone("America/Mexico_City")
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
                msg.body(f"⚠️ La fecha que proporcionaste ya pasó este año. ¿Quieres agendar la cita para el {texto_sugerida}? (responde sí o no)")
            else:
                estado["fecha"] = fecha_obj

        except Exception as e:
            msg.body("❌ No pude entender la fecha. Por favor usa el formato: '3 julio 4pm'")
            return str(response)

    conversaciones[numero] = estado
    return str(response)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
