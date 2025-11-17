import requests
import json

# URL apuntando al puerto 5000, como lo indica devserver.sh
BASE_URL = "http://127.0.0.1:5000/whatsapp"

# Un identificador de remitente único para simular un usuario
SENDER_ID = "whatsapp:+573001234568" # Cambia el número para reiniciar la conversación

def make_request(message):
    """Función para simular el envío de un mensaje a Twilio y recibir la respuesta."""
    payload = {
        'From': SENDER_ID,
        'Body': message,
        'MessageSid': f'SM{json.dumps(message.__hash__())[-10:]}' # ID de mensaje único
    }
    
    try:
        response = requests.post(BASE_URL, data=payload)
        response.raise_for_status()
        
        if '<Body>' in response.text and '</Body>' in response.text:
            return response.text.split('<Body>')[1].split('</Body>')[0]
        else:
            # Si no hay <Body>, podría ser una respuesta vacía (fin de conversación)
            return "(Conversación terminada o respuesta vacía)"

    except requests.exceptions.RequestException as e:
        return f"\n[ERROR] No se pudo conectar a la aplicación en el puerto 5000. Asegúrate de que el servidor esté corriendo.\nDetalle: {e}"

def main():
    """Función principal para el ciclo de chat interactivo."""
    print("--- Chatbot de Cerrajería 24 Horas (Modo Consola) ---")
    print("Escribe 'salir!' para terminar.")
    print("-----------------------------------------------------")

    # Mensaje inicial
    initial_response = make_request('hola')
    print(f"Bot: {initial_response}")

    while True:
        user_input = input("Tú: ")

        if user_input.lower() == 'salir!':
            print("\nSaliendo del chat de prueba. ¡Adiós!")
            break

        bot_response = make_request(user_input)
        print(f"Bot: {bot_response}")
        # Si la conversación termina, el bot podría no decir nada. 
        # El bucle seguirá, pero al escribir de nuevo debería empezar de cero.

if __name__ == "__main__":
    main()
