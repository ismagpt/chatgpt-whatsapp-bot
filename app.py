from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from openai import OpenAI
import os
import re
from google_calendar import crear_evento, esta_disponible, sugerir_disponibles

app = Flask(__name__)

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
conversaciones = {}

def extraer_fecha_hora(texto):
    match = re.search(r"(\d{4}-\d{2}-\d{2})[^0-9]*(\d{1,2}:\d{2})", texto)
    if match:
        return match.group(1), match.group(2)
    return None, None

@app.route("/webhook", methods=["POST"])
def whatsapp_reply():
    numero = request.values.get("From", "")
    mensaje = request.values.get("Body", "").strip()
    response = MessagingResponse()
    msg = response.message()
    estado = conversaciones.get(numero, {})

    if estado.get("esperando_nombre") and estado.get("fecha") and estado.get("hora"):
        nombre = mensaje.strip()
        fecha = estado["fecha"]
        hora = estado["hora"]

        if esta_disponible(fecha, hora):
            link = crear_evento(nombre, fecha, hora)
            msg.body(f"✅ Cita agendada para {nombre} el {fecha} a las {hora}.")
        else:
            sugerencias = sugerir_disponibles(fecha, hora)
            if sugerencias:
                sugerencias_str = "\n".join(sugerencias)
                msg.body(f"❌ Esa hora ya está ocupada. Aquí tienes horarios disponibles:\n{sugerencias_str}")
            else:
                msg.body("❌ No se encontró disponibilidad en los próximos días.")
        conversaciones.pop(numero)
        return str(response)

    # ¿Usuario pidió agendar?
    if "cita" in mensaje.lower() and "agendar" in mensaje.lower():
        fecha, hora = extraer_fecha_hora(mensaje)
        if fecha and hora:
            conversaciones[numero] = {"fecha": fecha, "hora": hora, "esperando_nombre": True}
            msg.body(f"Perfecto. ¿Podrías darme tu nombre completo para agendar la cita el {fecha} a las {hora}?")
        else:
            msg.body("¿En qué fecha y hora deseas la cita? Por favor usa el formato YYYY-MM-DD HH:MM")
    else:
        # Respuesta ChatGPT general
        chat_response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Eres un asistente dental que agenda citas y responde dudas comunes."},
                {"role": "user", "content": mensaje}
            ]
        )
        respuesta = chat_response.choices[0].message.content.strip()
        msg.body(respuesta)

    return str(response)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
