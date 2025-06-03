from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from openai import OpenAI
import os

app = Flask(__name__)

# 🔑 Configura el cliente con tu API key
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

@app.route("/webhook", methods=["POST"])
def whatsapp_reply():
    incoming_msg = request.values.get("Body", "")
    response = MessagingResponse()
    msg = response.message()

    # 🧠 Consulta a ChatGPT
    chat_response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "Eres un asistente para agendar citas dentales y responder dudas comunes."},
            {"role": "user", "content": incoming_msg}
        ]
    )

    respuesta = chat_response.choices[0].message.content.strip()
    msg.body(respuesta)
    return str(response)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
