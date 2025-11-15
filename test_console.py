
import os
import json
import psycopg2
from dotenv import load_dotenv
import logging
import uuid

# --- Configuración ---
load_dotenv()
logging.basicConfig(level=logging.INFO)

# ID de usuario para esta simulación. Puedes cambiarlo si quieres simular ser otro usuario.
SENDER_ID = "console-user-1"

# --- Copia de la Lógica de Base de Datos (de main.py) ---
def get_db_connection():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise ConnectionError("DATABASE_URL no configurada.")
    return psycopg2.connect(db_url, sslmode='require')

def get_session(sender_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT session_data FROM whatsapp_sessions WHERE sender_id = %s;", (sender_id,))
            result = cur.fetchone()
            return result[0] if result and result[0] else {'state': 'awaiting_welcome', 'data': {}, 'processed_sids': []}
    finally:
        if conn: conn.close()

def save_session(sender_id, session):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO whatsapp_sessions (sender_id, session_data, updated_at)
                VALUES (%s, %s, NOW() at time zone 'utc')
                ON CONFLICT (sender_id) DO UPDATE SET
                    session_data = EXCLUDED.session_data,
                    updated_at = EXCLUDED.updated_at;
            """, (sender_id, json.dumps(session)))
            conn.commit()
    finally:
        if conn: conn.close()

def delete_session(sender_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM whatsapp_sessions WHERE sender_id = %s;", (sender_id,))
            conn.commit()
    finally:
        if conn: conn.close()

# --- Copia de la Lógica de Conversación (de main.py) ---
AVAILABLE_SERVICES = [
    "Apertura de automóvil", "Apertura de caja fuerte", "Apertura de candado",
    "Apertura de motocicleta", "Apertura de puerta residencial", "Cambio de clave de automóvil",
    "Cambio de clave de motocicleta", "Cambio de clave residencial", "Duplicado de llave",
    "Elaboración de llaves", "Instalación de alarma", "Instalación de chapa", "Reparación general",
]

def get_summary_message(data):
    return (
        f"----- RESUMEN DE TU SOLICITUD -----\n\n"
        f"👤 Nombre: {data.get('nombre', 'N/A')}\n"
        f"🏙️ Ciudad: {data.get('ciudad', 'N/A')}\n"
        f"📍 Dirección: {data.get('direccion', 'N/A')}\n"
        f"🛠️ Servicio: {data.get('detalle_servicio', 'N/A')}\n"
        f"💳 Método de pago: {data.get('metodo_pago', 'N/A')}\n\n"
        "Escribe *confirmar* para guardar, *corregir* para cambiar algún dato, o *salir* para cancelar."
    )

def get_service_list_message():
    return "\n".join([
        "¿Qué tipo de servicio de cerrajería necesitas?\n",
        *[f"{i}. {service}" for i, service in enumerate(AVAILABLE_SERVICES, 1)],
        "\nResponde solo con el *número* del servicio que necesitas."
    ])

def process_message(sender_id, message_body):
    """El cerebro del bot. Procesa un mensaje y devuelve la respuesta."""
    lower_message_body = message_body.lower()
    # En la consola no tenemos SID, así que generamos uno falso para la idempotencia
    message_sid = str(uuid.uuid4())
    
    session = get_session(sender_id)

    # Idempotencia
    if message_sid in session.get('processed_sids', []): return None # Ignorar duplicado
    session.setdefault('processed_sids', []).append(message_sid)
    session['processed_sids'] = session['processed_sids'][-10:]

    state = session.get('state')
    data = session.get('data', {})
    response_message = ""

    if lower_message_body == 'salir':
        response_message = "Tu solicitud ha sido cancelada. Si quieres empezar de nuevo, solo escribe 'hola'."
        delete_session(sender_id)
        return response_message

    if state == 'awaiting_welcome':
        response_message = "¡Bienvenido al servicio de cerrajería! Para comenzar, dime tu nombre completo."
        session['state'] = 'awaiting_name'
    elif state == 'awaiting_name':
        data['nombre'] = message_body.title()
        response_message = f"Gracias, {data['nombre']}. ¿En qué ciudad te encuentras? (Bucaramanga, Piedecuesta o Floridablanca)"
        session['state'] = 'awaiting_city'
    # ... (el resto de la máquina de estados)
    elif state == 'awaiting_city':
        if lower_message_body in ['bucaramanga', 'piedecuesta', 'floridablanca']:
            data['ciudad'] = lower_message_body.capitalize()
            response_message = "Perfecto. Indícame la dirección completa (barrio, calle, número)."
            session['state'] = 'awaiting_address'
        else:
            response_message = "Ciudad no válida. Elige entre Bucaramanga, Piedecuesta o Floridablanca."
    elif state == 'awaiting_address':
        data['direccion'] = message_body
        response_message = get_service_list_message()
        session['state'] = 'awaiting_details'
    elif state == 'awaiting_details':
        try:
            choice = int(message_body)
            if 1 <= choice <= len(AVAILABLE_SERVICES):
                data['detalle_servicio'] = AVAILABLE_SERVICES[choice - 1]
                response_message = "¿Cómo prefieres pagar? (Efectivo o Nequi)"
                session['state'] = 'awaiting_payment_method'
            else:
                response_message = f"Opción no válida. Elige un número del 1 al {len(AVAILABLE_SERVICES)}."
        except (ValueError, TypeError):
            response_message = "Respuesta no válida. Usa solo el número del servicio."
    elif state == 'awaiting_payment_method':
        if lower_message_body in ['efectivo', 'nequi']:
            data['metodo_pago'] = lower_message_body
            response_message = get_summary_message(data)
            session['state'] = 'awaiting_confirmation'
        else:
            response_message = "Método de pago no válido. Escribe 'Efectivo' o 'Nequi'."
    elif state == 'awaiting_confirmation':
        if lower_message_body == 'confirmar':
            response_message = "¡Servicio confirmado! Un cerrajero se pondrá en contacto contigo."
            delete_session(sender_id)
        elif lower_message_body == 'corregir':
            response_message = "¿Qué dato deseas corregir? (nombre, ciudad, direccion, servicio, pago)"
            session['state'] = 'awaiting_correction_choice'
        else:
            response_message = "Opción no válida. Escribe *confirmar*, *corregir* o *salir*."
    elif state == 'awaiting_correction_choice':
        field = lower_message_body
        prompts = {
            'nombre': "Por favor, dime el nombre correcto.",
            'ciudad': "¿En qué ciudad te encuentras? (Bucaramanga, Piedecuesta o Floridablanca)",
            'direccion': "Por favor, dime la dirección correcta.",
            'servicio': get_service_list_message(),
            'pago': "¿Cómo prefieres pagar? (Efectivo o Nequi)"
        }
        if field in prompts:
            response_message = prompts[field]
            session['state'] = 'awaiting_correction_value'
            session['field_to_correct'] = field
        else:
            response_message = "Dato no válido. Elige entre: nombre, ciudad, direccion, servicio, pago."
    elif state == 'awaiting_correction_value':
        field_to_correct = session.pop('field_to_correct', None)
        data[field_to_correct] = message_body
        response_message = "Dato actualizado.\n\n" + get_summary_message(data)
        session['state'] = 'awaiting_confirmation'
    else:
        response_message = "Lo siento, no entendí. Escribe 'hola' para empezar."
        delete_session(sender_id)

    save_session(sender_id, session)
    return response_message


# --- Bucle Principal de la Simulación ---
if __name__ == "__main__":
    print("--- Simulador de Chatbot de Cerrajería ---")
    print(f"ID de Sesión: {SENDER_ID}")
    print("Escribe 'salir()' para terminar la simulación.")
    print("---------------------------------------------")

    # Iniciar la conversación
    initial_response = process_message(SENDER_ID, "hola")
    print(f"🤖 Bot: {initial_response}")

    while True:
        try:
            user_input = input("🙂 Tú: ")
            if user_input.lower() == 'salir()':
                print("Simulación terminada.")
                break
            
            bot_response = process_message(SENDER_ID, user_input)
            if bot_response:
                print(f"🤖 Bot: {bot_response}")

        except KeyboardInterrupt:
            print("\nSimulación terminada.")
            break
        except Exception as e:
            print(f"Ha ocurrido un error: {e}")
            logging.error(f"ERROR_SIMULATOR: {e}")
            break
