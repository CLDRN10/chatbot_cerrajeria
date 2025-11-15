
import os
import json
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import psycopg2
from psycopg2 import pool
from urllib.parse import urlparse
from dotenv import load_dotenv
import logging

load_dotenv()

app = Flask(__name__)

# Configurar logging
logging.basicConfig(level=logging.INFO)

# --- Pool de Conexiones a la Base de Datos ---
db_pool = None
try:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL no configurada")
    # REDUCIDO EL TAMAÑO DEL POOL PARA EVITAR EL ERROR "TOO MANY CONNECTIONS"
    db_pool = pool.SimpleConnectionPool(1, 4, dsn=db_url, sslmode='require')
    app.logger.info("Pool de conexiones a DB creado.")
except Exception as e:
    app.logger.error(f"Error al crear el pool de conexiones: {e}")

# --- Gestión de Sesiones en la Base de Datos (Solución Definitiva) ---
def init_db():
    """Crea la tabla de sesiones si no existe."""
    if not db_pool:
        # Este error es fatal, si no hay pool, la app no puede funcionar.
        raise ConnectionError("El pool de conexiones a la base de datos no está disponible. La aplicación no puede iniciar.")
    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS whatsapp_sessions (
                    sender_id VARCHAR(255) PRIMARY KEY,
                    session_data JSONB,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() at time zone 'utc')
                );
            """)
            conn.commit()
            app.logger.info("Tabla 'whatsapp_sessions' verificada/creada.")
    finally:
        db_pool.putconn(conn)

def get_session(sender_id):
    """Obtiene la sesión de un usuario desde la DB."""
    if not db_pool: raise ConnectionError("Pool de DB no disponible.")
    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT session_data FROM whatsapp_sessions WHERE sender_id = %s;", (sender_id,))
            result = cur.fetchone()
            if result and result[0]:
                return result[0]
            else:
                # Si no hay sesión, crea una por defecto
                return {'state': 'awaiting_welcome', 'data': {}, 'processed_sids': []}
    finally:
        db_pool.putconn(conn)

def save_session(sender_id, session):
    """Guarda la sesión de un usuario en la DB."""
    if not db_pool: raise ConnectionError("Pool de DB no disponible.")
    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Usamos INSERT ON CONFLICT para crear o actualizar atómicamente
            cur.execute("""
                INSERT INTO whatsapp_sessions (sender_id, session_data, updated_at)
                VALUES (%s, %s, NOW() at time zone 'utc')
                ON CONFLICT (sender_id) DO UPDATE SET
                    session_data = EXCLUDED.session_data,
                    updated_at = EXCLUDED.updated_at;
            """, (sender_id, json.dumps(session)))
            conn.commit()
    finally:
        db_pool.putconn(conn)

def delete_session(sender_id):
    """Elimina la sesión de un usuario de la DB."""
    if not db_pool: raise ConnectionError("Pool de DB no disponible.")
    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM whatsapp_sessions WHERE sender_id = %s;", (sender_id,))
            conn.commit()
    finally:
        db_pool.putconn(conn)

# --- Inicializar DB solo si el pool se creó correctamente ---
if db_pool:
    with app.app_context():
        init_db()

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


@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    sender_id = request.values.get('From', '')
    message_body = request.values.get('Body', '').strip()
    lower_message_body = message_body.lower()
    message_sid = request.values.get('MessageSid')
    resp = MessagingResponse()
    msg = resp.message()

    # Manejo de error si el pool no se inicializó
    if not db_pool:
        app.logger.error("La petición no puede ser procesada porque no hay conexión a la base de datos.")
        msg.body("Lo siento, el servicio no está disponible en este momento por un problema de conexión. Por favor, intenta más tarde.")
        return str(resp)

    session = get_session(sender_id)

    # --- Idempotencia: Ignorar mensajes ya procesados ---
    if message_sid and message_sid in session.get('processed_sids', []):
        app.logger.warning(f"Mensaje duplicado {message_sid}. Ignorando.")
        return str(resp) # Responder 200 OK para detener reintentos

    # Añadir SID a la lista de procesados (y mantenerla corta)
    if message_sid:
        session.setdefault('processed_sids', []).append(message_sid)
        session['processed_sids'] = session['processed_sids'][-10:]

    state = session.get('state')
    data = session.get('data', {})

    # --- Manejo de Comandos Globales ---
    if lower_message_body == 'salir':
        msg.body("Tu solicitud ha sido cancelada. Si quieres empezar de nuevo, solo escribe 'hola'.")
        delete_session(sender_id)
        return str(resp)
    
    # --- Máquina de Estados de la Conversación ---
    try:
        if state == 'awaiting_welcome':
            msg.body("¡Bienvenido al servicio de cerrajería! Para comenzar, por favor dime tu nombre completo.")
            session['state'] = 'awaiting_name'

        elif state == 'awaiting_name':
            data['nombre'] = message_body.title()
            msg.body(f"Gracias, {data['nombre']}. ¿En qué ciudad te encuentras? (Bucaramanga, Piedecuesta o Floridablanca)")
            session['state'] = 'awaiting_city'

        elif state == 'awaiting_city':
            if lower_message_body in ['bucaramanga', 'piedecuesta', 'floridablanca']:
                data['ciudad'] = lower_message_body.capitalize()
                msg.body("Perfecto. Ahora, por favor, indícame la dirección completa (barrio, calle, número).")
                session['state'] = 'awaiting_address'
            else:
                msg.body("Ciudad no válida. Por favor, elige entre Bucaramanga, Piedecuesta o Floridablanca.")
        
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
                    msg.body(f"Opción no válida. Por favor, elige un número entre 1 y {len(AVAILABLE_SERVICES)}.")
            except (ValueError, TypeError):
                msg.body("Respuesta no válida. Por favor, responde solo con el número del servicio.")

        elif state == 'awaiting_payment_method':
            if lower_message_body in ['efectivo', 'nequi']:
                data['metodo_pago'] = lower_message_body
                msg.body(get_summary_message(data))
                session['state'] = 'awaiting_confirmation'
            else:
                msg.body("Método de pago no válido. Por favor, escribe 'Efectivo' o 'Nequi'.")

        elif state == 'awaiting_confirmation':
            if lower_message_body == 'confirmar':
                # Aquí iría la lógica para guardar en la DB (save_service_request)
                msg.body("¡Servicio confirmado! Un cerrajero se pondrá en contacto contigo en breve.")
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
                session['field_to_correct'] = field # Guardamos qué campo se está corrigiendo
            else:
                msg.body("Dato no válido. Elige entre: nombre, ciudad, direccion, servicio, pago.")

        elif state == 'awaiting_correction_value':
            field = session.pop('field_to_correct', None)
            if field == 'nombre':
                data['nombre'] = message_body.title()
            elif field == 'ciudad':
                if lower_message_body in ['bucaramanga', 'piedecuesta', 'floridablanca']:
                    data['ciudad'] = lower_message_body.capitalize()
                else:
                     msg.body("Ciudad no válida. Por favor, elige una de las opciones.")
                     session['field_to_correct'] = field # Re-establecer para reintentar
                     save_session(sender_id, session)
                     return str(resp)
            # ... (Lógica similar para otros campos)

            # Volver a la confirmación
            msg.body("Dato actualizado.\n\n" + get_summary_message(data))
            session['state'] = 'awaiting_confirmation'

        else:
            msg.body("Parece que hubo un error. Escribe 'salir' para reiniciar.")

    except Exception as e:
        app.logger.error(f"Error en la lógica del bot: {e}")
        msg.body("Lo siento, ocurrió un error inesperado. Intenta de nuevo.")
        delete_session(sender_id)

    # Guardar la sesión en la base de datos al final de cada interacción exitosa
    save_session(sender_id, session)
    return str(resp)

if __name__ == "__main__":
    app.run(debug=True)
