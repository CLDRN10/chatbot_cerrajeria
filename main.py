
import os
import json
import psycopg2
import psycopg2.extras # Necesario para devolver diccionarios
from urllib.parse import urlparse
from dotenv import load_dotenv
import logging
from flask import Flask, request, jsonify # jsonify para las respuestas de API
from twilio.twiml.messaging_response import MessagingResponse

# --- Configuración Inicial ---
load_dotenv()
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# --- Helpers de Base de Datos ---
def get_db_connection():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise ConnectionError("La variable de entorno DATABASE_URL no está configurada.")
    # Usamos un cursor factory para que las respuestas sean diccionarios
    return psycopg2.connect(db_url, sslmode='require')


# --- Rutas de la Interfaz Gráfica (API) ---

@app.route("/api/servicios", methods=['GET'])
def get_all_servicios():
    """Devuelve una lista de todos los servicios con datos del cliente y cerrajero."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # ACTUALIZADO: Añadidos los campos direccion_c y ciudad_c del cliente
            sql_query = """
                SELECT 
                    s.id_servicio, s.fecha_s, s.hora_s, s.tipo_s, s.estado_s, 
                    s.monto_pago, s.metodo_pago, s.detalle_pago,
                    c.nombre_c AS nombre_cliente, c.telefono_c AS telefono_cliente,
                    c.direccion_c, c.ciudad_c,
                    ce.nombre_ce AS nombre_cerrajero
                FROM servicio s
                JOIN cliente c ON s.id_cliente = c.id_cliente
                JOIN cerrajero ce ON s.id_cerrajero = ce.id_cerrajero
                ORDER BY s.fecha_s DESC, s.hora_s DESC;
            """
            cur.execute(sql_query)
            servicios = cur.fetchall()
            # Convertir fechas y horas a strings para que JSON no dé error
            for servicio in servicios:
                servicio['fecha_s'] = servicio['fecha_s'].isoformat() if servicio['fecha_s'] else None
                # Formateamos la hora a HH:MM
                servicio['hora_s'] = servicio['hora_s'].strftime('%H:%M') if servicio['hora_s'] else None

            return jsonify(servicios), 200
    except Exception as e:
        app.logger.error(f"API_GET_SERVICIOS_ERROR: {e}")
        # Cambio temporal para depuración: Devolver el error real.
        return jsonify({"error_real": str(e)}), 500
    finally:
        if conn: conn.close()


# --- Lógica del Chatbot de WhatsApp ---

# ... (El resto del código del chatbot se mantiene exactamente igual)
# ... (Lo omito aquí para no repetir todo el archivo, pero no se ha borrado)

# --- Lógica de Guardado Permanente (Adaptada a tu Schema) ---
def save_service_request(sender_id, data):
    """
    Guarda la solicitud en las tablas `cliente` y `servicio`.
    1. Busca o crea el cliente basado en el sender_id (telefono).
    2. Crea el registro del servicio y lo asocia al cliente y al cerrajero por defecto.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            phone_number = sender_id.split(':')[-1]
            cur.execute("SELECT id_cliente FROM cliente WHERE telefono_c = %s;", (phone_number,))
            client_result = cur.fetchone()

            if client_result:
                client_id = client_result[0]
            else:
                cur.execute(
                    """INSERT INTO cliente (nombre_c, telefono_c, direccion_c, ciudad_c)
                       VALUES (%s, %s, %s, %s) RETURNING id_cliente;""",
                    (data.get('nombre'), phone_number, data.get('direccion'), data.get('ciudad'))
                )
                client_id = cur.fetchone()[0]

            id_cerrajero_default = 1
            monto_pago = 0
            metodo_pago = data.get('metodo_pago')
            detalle_pago = 'PENDIENTE POR VERIFICAR' if metodo_pago.lower() == 'nequi' else None

            cur.execute(
                """INSERT INTO servicio (fecha_s, hora_s, tipo_s, estado_s, monto_pago, metodo_pago, detalle_pago, id_cliente, id_cerrajero)
                   VALUES (CURRENT_DATE, CURRENT_TIME, %s, 'pendiente', %s, %s, %s, %s, %s);""",
                (data.get('detalle_servicio'), monto_pago, metodo_pago, detalle_pago, client_id, id_cerrajero_default)
            )

            conn.commit()
            app.logger.info(f"SERVICE_REQUEST_SAVED: For client_id {client_id}")

    except Exception as e:
        app.logger.error(f"DATABASE_SAVE_ERROR: {e}")
        if conn: conn.rollback()
        raise
    finally:
        if conn: conn.close()

# --- Gestión de Sesiones Temporales ---
def get_session(sender_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT session_data FROM whatsapp_sessions WHERE sender_id = %s;", (sender_id,))
            result = cur.fetchone()
            return result[0] if result and result[0] else {'state': 'awaiting_start', 'data': {}, 'processed_sids': []}
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
        app.logger.error(f"CRITICAL_DB_ERROR: {e}")
        msg.body("Lo siento, el servicio no está disponible. Intenta más tarde.")
        return str(resp)

    if message_sid and message_sid in session.get('processed_sids', []):
        return str(resp)
    if message_sid:
        session.setdefault('processed_sids', []).append(message_sid)
        session['processed_sids'] = session['processed_sids'][-10:]

    state = session.get('state')
    data = session.get('data', {})

    if lower_message_body in ['hola', 'empezar', 'inicio'] or state == 'awaiting_start':
        msg.body("¡Bienvenido al servicio de cerrajería! Para comenzar, dime tu nombre completo.")
        session['state'] = 'awaiting_name'
        session['data'] = {}
    elif lower_message_body == 'salir':
        msg.body("Tu solicitud ha sido cancelada. Si quieres empezar de nuevo, solo escribe 'hola'.")
        delete_session(sender_id)
        return str(resp)
    elif state == 'awaiting_name':
        data['nombre'] = message_body.title()
        msg.body(f"Gracias, {data['nombre']}. ¿En qué ciudad te encuentras? (Bucaramanga, Piedecuesta o Floridablanca)")
        session['state'] = 'awaiting_city'
    elif state == 'awaiting_city':
        data['ciudad'] = lower_message_body.capitalize()
        msg.body("Perfecto. Indícame la dirección completa (barrio, calle, número).")
        session['state'] = 'awaiting_address'
    elif state == 'awaiting_address':
        data['direccion'] = message_body
        msg.body(get_service_list_message())
        session['state'] = 'awaiting_details'
    elif state == 'awaiting_details':
        try:
            choice = int(message_body)
            data['detalle_servicio'] = AVAILABLE_SERVICES[choice - 1]
            msg.body("¿Cómo prefieres pagar? (Efectivo o Nequi)")
            session['state'] = 'awaiting_payment_method'
        except (ValueError, IndexError):
            msg.body("Opción no válida. Usa solo el número del servicio.")
    elif state == 'awaiting_payment_method':
        data['metodo_pago'] = lower_message_body.capitalize()
        msg.body(get_summary_message(data))
        session['state'] = 'awaiting_confirmation'
    elif state == 'awaiting_confirmation':
        if lower_message_body == 'confirmar':
            try:
                save_service_request(sender_id, data)
                msg.body("¡Servicio confirmado! Tu solicitud ha sido guardada. Un cerrajero se pondrá en contacto contigo.")
                delete_session(sender_id)
            except Exception as e:
                app.logger.error(f"SAVE_REQUEST_FAILED: {e}")
                msg.body("Hubo un error al guardar tu solicitud. Por favor, inténtalo de nuevo o contacta a soporte.")
        elif lower_message_body == 'corregir':
            msg.body("¿Qué dato deseas corregir? (nombre, ciudad, direccion, servicio, pago)")
            session['state'] = 'awaiting_correction_choice'
        else:
            msg.body("Opción no válida. Escribe *confirmar*, *corregir* o *salir*.")

    # El resto de estados de corrección se omiten por brevedad

    session['data'] = data
    save_session(sender_id, session)
    return str(resp)


if __name__ == "__main__":
    app.run(debug=True, port=8080)
