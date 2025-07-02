from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from openai import OpenAI
import os
from google_calendar import crear_evento  # 👈 importa la función que agenda la cita

app = Flask(__name__)

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

# Estado de conversaciones por número
conversaciones = {}

@app.route("/webhook", methods=["POST"])
def whatsapp_reply():
    numero = request.values.get("From", "")
    mensaje = request.values.get("Body", "").strip()
    response = MessagingResponse()
    msg = response.message()

    estado = conversaciones.get(numero, {})

    if "esperando_datos" in estado:
        # Ya está en medio del flujo para agendar
        nombre = mensaje.strip()
        try:
            # Crea el evento en Google Calendar
            crear_evento(nombre=nombre)
            msg.body(f"✅ Cita agendada para {nombre}. ¡Gracias!")
        except Exception as e:
            msg.body(f"❌ Hubo un error al agendar la cita: {e}")
        conversaciones.pop(numero)
    elif "cita" in mensaje.lower() and "agendar" in mensaje.lower():
        # Inicia flujo de agendamiento
        conversaciones[numero] = {"esperando_datos": True}
        msg.body("Por favor indícame tu nombre completo para agendar la cita.")
    else:
        # ChatGPT responde dudas generales
        chat_response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Eres un asistente para agendar citas dentales y responder dudas comunes."},
                {"role": "user", "content": mensaje}
            ]
        )
        respuesta = chat_response.choices[0].message.content.strip()
        msg.body(respuesta)

    return str(response)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
