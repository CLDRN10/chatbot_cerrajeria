
import os
import json
import psycopg2
from urllib.parse import urlparse
from dotenv import load_dotenv
import logging
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# --- Configuración Inicial ---
load_dotenv()
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# --- Helpers de Base de Datos (Modelo sin Pool) ---
def get_db_connection():
    """Crea y retorna una nueva conexión a la base de datos."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise ConnectionError("La variable de entorno DATABASE_URL no está configurada.")
    return psycopg2.connect(db_url, sslmode='require')

def init_db():
    """Crea la tabla de sesiones si no existe. Se ejecuta una vez al inicio."""
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS whatsapp_sessions (
                    sender_id VARCHAR(255) PRIMARY KEY,
                    session_data JSONB,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() at time zone 'utc')
                );
            """)
            conn.commit()
        conn.close()
        app.logger.info("DATABASE: Tabla 'whatsapp_sessions' verificada/creada exitosamente.")
    except Exception as e:
        app.logger.error(f"DATABASE_INIT_ERROR: {e}")
        # Si la DB no puede ser inicializada, la aplicación no debería continuar.
        raise

# --- Gestión de Sesiones (Cada función maneja su propia conexión) ---
def get_session(sender_id):
    """Obtiene la sesión de un usuario. Abre y cierra su propia conexión."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT session_data FROM whatsapp_sessions WHERE sender_id = %s;", (sender_id,))
            result = cur.fetchone()
            return result[0] if result and result[0] else {'state': 'awaiting_welcome', 'data': {}, 'processed_sids': []}
    finally:
        if conn: conn.close()

def save_session(sender_id, session):
    """Guarda la sesión de un usuario. Abre y cierra su propia conexión."""
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
    """Elimina la sesión de un usuario. Abre y cierra su propia conexión."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM whatsapp_sessions WHERE sender_id = %s;", (sender_id,))
            conn.commit()
    finally:
        if conn: conn.close()


# --- Contenido del Chatbot ---
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

# --- Rutas de la Aplicación ---
@app.route("/")
def index():
    """Ruta de 'health check' para que Clever Cloud sepa que la app está viva."""
    return "OK", 200

@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    sender_id = request.values.get('From', '')
    message_body = request.values.get('Body', '').strip()
    lower_message_body = message_body.lower()
    message_sid = request.values.get('MessageSid')
    resp = MessagingResponse()
    msg = resp.message()

    try:
        session = get_session(sender_id)
    except Exception as e:
        app.logger.error(f"ERROR_GETTING_SESSION: No se pudo conectar a la DB. {e}")
        msg.body("Lo siento, el servicio no está disponible por un problema de conexión. Por favor, intenta más tarde.")
        return str(resp)

    # Idempotencia: Ignorar SIDs ya procesados
    if message_sid and message_sid in session.get('processed_sids', []):
        app.logger.warning(f"Duplicate message SID {message_sid}. Ignoring.")
        return str(resp)
    if message_sid:
        session.setdefault('processed_sids', []).append(message_sid)
        session['processed_sids'] = session['processed_sids'][-10:]

    state = session.get('state')
    data = session.get('data', {})

    if lower_message_body == 'salir':
        msg.body("Tu solicitud ha sido cancelada. Si quieres empezar de nuevo, solo escribe 'hola'.")
        delete_session(sender_id)
        return str(resp)

    # Lógica de la conversación (máquina de estados)
    if state == 'awaiting_welcome':
        msg.body("¡Bienvenido al servicio de cerrajería! Para comenzar, dime tu nombre completo.")
        session['state'] = 'awaiting_name'
    elif state == 'awaiting_name':
        data['nombre'] = message_body.title()
        msg.body(f"Gracias, {data['nombre']}. ¿En qué ciudad te encuentras? (Bucaramanga, Piedecuesta o Floridablanca)")
        session['state'] = 'awaiting_city'
    elif state == 'awaiting_city':
        if lower_message_body in ['bucaramanga', 'piedecuesta', 'floridablanca']:
            data['ciudad'] = lower_message_body.capitalize()
            msg.body("Perfecto. Indícame la dirección completa (barrio, calle, número).")
            session['state'] = 'awaiting_address'
        else:
            msg.body("Ciudad no válida. Elige entre Bucaramanga, Piedecuesta o Floridablanca.")
    elif state == 'awaiting_address':
        data['direccion'] = message_body
        msg.body(get_service_list_message())
        session['state'] = 'awaiting_details'
    elif state == 'awaiting_details':
        try:
            choice = int(message_body)
            if 1 <= choice <= len(AVAILABLE_SERVICES):
                data['detalle_servicio'] = AVAILABLE_SERVICES[choice - 1]
                msg.body("¿Cómo prefieres pagar? (Efectivo o Nequi)")
                session['state'] = 'awaiting_payment_method'
            else:
                msg.body(f"Opción no válida. Elige un número del 1 al {len(AVAILABLE_SERVICES)}.")
        except (ValueError, TypeError):
            msg.body("Respuesta no válida. Usa solo el número del servicio.")
    elif state == 'awaiting_payment_method':
        if lower_message_body in ['efectivo', 'nequi']:
            data['metodo_pago'] = lower_message_body
            msg.body(get_summary_message(data))
            session['state'] = 'awaiting_confirmation'
        else:
            msg.body("Método de pago no válido. Escribe 'Efectivo' o 'Nequi'.")
    elif state == 'awaiting_confirmation':
        if lower_message_body == 'confirmar':
            # Lógica para guardar el servicio final en la DB
            msg.body("¡Servicio confirmado! Un cerrajero se pondrá en contacto contigo.")
            delete_session(sender_id)
        elif lower_message_body == 'corregir':
            msg.body("¿Qué dato deseas corregir? (nombre, ciudad, direccion, servicio, pago)")
            session['state'] = 'awaiting_correction_choice'
        else:
            msg.body("Opción no válida. Escribe *confirmar*, *corregir* o *salir*.")
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
            msg.body(prompts[field])
            session['state'] = 'awaiting_correction_value'
            session['field_to_correct'] = field
        else:
            msg.body("Dato no válido. Elige entre: nombre, ciudad, direccion, servicio, pago.")
    elif state == 'awaiting_correction_value':
        field_to_correct = session.pop('field_to_correct', None)
        # Aquí falta la lógica para actualizar el campo correspondiente
        data[field_to_correct] = message_body # Simplificación, necesita más validación
        msg.body("Dato actualizado.\n\n" + get_summary_message(data))
        session['state'] = 'awaiting_confirmation'
    else:
        msg.body("Lo siento, no entendí. Escribe 'hola' para empezar.")
        delete_session(sender_id) # Reiniciar si el estado es desconocido

    # Guardar la sesión al final de una interacción exitosa
    save_session(sender_id, session)
    return str(resp)

# --- Arranque de la Aplicación ---
if __name__ != '__main__':
    # Este bloque se ejecuta cuando la app corre en producción (gunicorn/uwsgi)
    init_db()

# Para desarrollo local (python main.py)
if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=8080)
