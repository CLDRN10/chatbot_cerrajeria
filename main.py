
import os
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import psycopg2
from psycopg2 import pool
from urllib.parse import urlparse
from dotenv import load_dotenv
import logging

load_dotenv()

app = Flask(__name__)

# Configurar logging para ver la información en Clever Cloud
logging.basicConfig(level=logging.INFO)

# --- Pool de Conexiones a la Base de Datos (Optimización) ---
db_pool = None
try:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise ValueError("No se ha configurado la variable de entorno DATABASE_URL")
    
    db_pool = pool.SimpleConnectionPool(
        minconn=1,
        maxconn=5,
        dsn=db_url,
        sslmode='require'
    )
    app.logger.info("Pool de conexiones a la base de datos creado exitosamente.")

except Exception as e:
    app.logger.error(f"Error al crear el pool de conexiones: {e}")

# --- Ruta de Chequeo de Salud ---
@app.route("/")
def index():
    return "Application is running successfully!"

# --- Lista de Servicios Disponibles ---
AVAILABLE_SERVICES = [
    "Apertura de automóvil", "Apertura de caja fuerte", "Apertura de candado",
    "Apertura de motocicleta", "Apertura de puerta residencial", "Cambio de clave de automóvil",
    "Cambio de clave de motocicleta", "Cambio de clave residencial", "Duplicado de llave",
    "Elaboración de llaves", "Instalación de alarma", "Instalación de chapa", "Reparación general",
]

# --- Función de Base de Datos Optimizada ---
def save_service_request(sender_id, data):
    if not db_pool:
        raise ConnectionError("El pool de conexiones no está disponible.")

    phone_number = sender_id.split(':')[-1]
    
    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id_cliente FROM cliente WHERE telefono_c = %s;", (phone_number,))
            client_id_result = cur.fetchone()
            
            if client_id_result:
                client_id = client_id_result[0]
                cur.execute(
                    "UPDATE cliente SET nombre_c = %s, direccion_c = %s, ciudad_c = %s WHERE id_cliente = %s;",
                    (data['nombre'], data['direccion'], data['ciudad'], client_id)
                )
            else:
                cur.execute(
                    "INSERT INTO cliente (nombre_c, telefono_c, direccion_c, ciudad_c) VALUES (%s, %s, %s, %s) RETURNING id_cliente;",
                    (data['nombre'], phone_number, data['direccion'], data['ciudad'])
                )
                client_id = cur.fetchone()[0]

            detalle_pago_val = 'N/A' if data['metodo_pago'].lower() == 'nequi' else None

            cur.execute(
                """INSERT INTO servicio (id_cliente, fecha_s, hora_s, tipo_s, estado_s, monto_pago, metodo_pago, detalle_pago, id_cerrajero)
                VALUES (%s, CURRENT_DATE, CURRENT_TIME, %s, 'pendiente', 0, %s, %s, 1);""",
                (client_id, data['detalle_servicio'], data['metodo_pago'], detalle_pago_val)
            )
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        db_pool.putconn(conn)

# --- Lógica del Chatbot ---
user_sessions = {}

def get_summary_message(data):
    return (
        f"----- RESUMEN DE TU SOLICITUD -----\n"
        f"Nombre: {data['nombre']}\n"
        f"Ciudad: {data['ciudad']}\n"
        f"Dirección: {data['direccion']}\n"
        f"Servicio: {data['detalle_servicio']}\n"
        f"Método de pago: {data['metodo_pago']}\n\n"
        "Escribe 'confirmar' para guardar, 'corregir' para cambiar algún dato, o 'salir' para cancelar."
    )

def get_service_list_message():
    service_list = "¿Qué tipo de servicio de cerrajería necesitas?\n\n"
    for i, service in enumerate(AVAILABLE_SERVICES, 1):
        service_list += f"{i}. {service}\n"
    service_list += "\nResponde solo con el número del servicio que necesitas."
    return service_list

@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    sender_id = request.values.get('From', '')
    message_body = request.values.get('Body', '').lower().strip()
    message_sid = request.values.get('MessageSid')
    resp = MessagingResponse()
    msg = resp.message()

    # --- Gestión de Sesión e Idempotencia (Solución a Duplicados) ---
    session = user_sessions.get(sender_id)
    if not session:
        session = {'state': 'awaiting_welcome', 'data': {}, 'processed_sids': set()}
        user_sessions[sender_id] = session

    if message_sid and message_sid in session['processed_sids']:
        app.logger.warning(f"Mensaje duplicado detectado: {message_sid}. Ignorando.")
        return str(resp) # Responder 200 OK para detener reintentos de Twilio

    # Marcar el SID como procesado inmediatamente para evitar condiciones de carrera
    if message_sid:
        session['processed_sids'].add(message_sid)
        # Opcional: mantener el set limpio, guardando solo los últimos 20 SIDs
        while len(session['processed_sids']) > 20:
            session['processed_sids'].pop()

    # --- Lógica de Estado del Chatbot ---
    state = session.get('state')
    data = session.get('data', {})

    if message_body == 'salir':
        msg.body("Tu solicitud ha sido cancelada. Gracias.")
        user_sessions.pop(sender_id, None)
        return str(resp)

    if state == 'awaiting_welcome':
        msg.body("¡Bienvenido al servicio de cerrajería! Para comenzar, por favor dime tu nombre completo.")
        session['state'] = 'awaiting_name'
    elif state == 'awaiting_name':
        data['nombre'] = request.values.get('Body', '').strip().title()
        msg.body(f"Gracias, {data['nombre']}. ¿En qué ciudad te encuentras? (Bucaramanga, Piedecuesta o Floridablanca)")
        session['state'] = 'awaiting_city'
    elif state == 'awaiting_city':
        city = message_body
        if city in ['bucaramanga', 'piedecuesta', 'floridablanca']:
            data['ciudad'] = city
            msg.body("Perfecto. Ahora, por favor, indícame la dirección completa (barrio, calle, número).")
            session['state'] = 'awaiting_address'
        else:
            msg.body("Ciudad no válida. Por favor, elige entre Bucaramanga, Piedecuesta o Floridablanca.")
    elif state == 'awaiting_address':
        data['direccion'] = request.values.get('Body', '').strip()
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
        except ValueError:
            msg.body("Respuesta no válida. Por favor, responde solo con el número del servicio.")
    elif state == 'awaiting_payment_method':
        payment_method = message_body
        if payment_method in ['efectivo', 'nequi']:
            data['metodo_pago'] = payment_method
            msg.body(get_summary_message(data))
            session['state'] = 'awaiting_confirmation'
        else:
            msg.body("Método de pago no válido. Por favor, escribe 'Efectivo' o 'Nequi'.")
    elif state == 'awaiting_confirmation':
        if message_body == 'confirmar':
            try:
                save_service_request(sender_id, data)
                msg.body("¡Servicio confirmado! Un cerrajero se pondrá en contacto contigo en breve.")
                user_sessions.pop(sender_id, None) # Limpiar sesión después de confirmar
                return str(resp) # Salir aquí para evitar guardar la sesión que acabamos de borrar
            except Exception as e:
                app.logger.error(f"Error guardando en la base de datos: {e}")
                msg.body("Hubo un error al guardar tu solicitud. Por favor, intenta de nuevo más tarde.")
        elif message_body == 'corregir':
            msg.body("¿Qué dato deseas corregir? (nombre, ciudad, direccion, servicio, pago)")
            session['state'] = 'awaiting_correction_choice'
        else:
            msg.body("Opción no válida. Escribe 'confirmar', 'corregir' o 'salir'.")
    elif state == 'awaiting_correction_choice':
        field = message_body
        if field == 'nombre':
            msg.body("Por favor, dime el nombre correcto.")
            session['state'] = 'awaiting_correction_new_value'
            session['field_to_correct'] = 'nombre'
        # ... (se pueden añadir los demás campos de corrección aquí) ...
        else:
            msg.body("Dato no válido para corregir. Elige entre: nombre, ciudad, etc.")
    
    # ... (lógica para awaiting_correction_new_value si se implementa por completo) ...

    # Guardar el estado de la sesión al final
    session['data'] = data
    user_sessions[sender_id] = session
    return str(resp)

if __name__ == "__main__":
    app.run(debug=True)
