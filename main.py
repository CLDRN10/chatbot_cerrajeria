import os
import json
import psycopg2
import psycopg2.extras
import pytz  # Se importa la nueva librería
from urllib.parse import urlparse
from dotenv import load_dotenv
import logging
from flask import Flask, request, jsonify, render_template
from twilio.twiml.messaging_response import MessagingResponse
from datetime import datetime

# --- Configuración Inicial ---
load_dotenv()
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# --- Helpers de Base de Datos ---
def get_db_connection():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise ConnectionError("La variable de entorno DATABASE_URL no está configurada.")
    return psycopg2.connect(db_url, sslmode='require')

# --- Rutas de la Interfaz Gráfica (Web) ---

@app.route("/")
def index():
    return render_template('login.html')

@app.route("/login")
def login_page():
    return render_template('login.html')

@app.route("/inicio")
def inicio_page():
    return render_template('inicio.html')

@app.route("/servicios")
def show_servicios_page():
    return render_template('servicios.html')

@app.route("/agregar")
def agregar_page():
    return render_template('agregar.html')

@app.route("/estadisticas")
def estadisticas_page():
    return render_template('estadisticas.html')

@app.route("/clave")
def clave_page():
    return render_template('clave.html')

# --- API para la Interfaz Gráfica (Endpoints de Datos) ---

@app.route("/api/servicios", methods=['GET'])
def get_all_servicios():
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            sql_query = """
                SELECT 
                    s.id_servicio, s.fecha_s AS fecha, s.hora_s AS hora,
                    s.tipo_s AS tipo, s.estado_s AS estado, s.monto_pago AS valor,
                    s.metodo_pago, c.nombre_c AS cliente, c.telefono_c, 
                    c.direccion_c AS direccion, c.ciudad_c AS municipio, 
                    ce.nombre_ce AS cerrajero
                FROM servicio s
                JOIN cliente c ON s.id_cliente = c.id_cliente
                JOIN cerrajero ce ON s.id_cerrajero = ce.id_cerrajero
                ORDER BY s.fecha_s DESC, s.hora_s DESC;
            """
            cur.execute(sql_query)
            servicios = cur.fetchall()
            
            for servicio in servicios:
                if servicio.get('fecha'):
                    servicio['fecha'] = servicio['fecha'].strftime('%d/%m/%Y')
                if servicio.get('hora'):
                    servicio['hora'] = servicio['hora'].strftime('%I:%M %p')

            return jsonify(servicios), 200
    except Exception as e:
        app.logger.error(f"API_GET_SERVICIOS_ERROR: {e}")
        return jsonify({"error": "Error interno al obtener los servicios", "detalle": str(e)}), 500
    finally:
        if conn: conn.close()

@app.route('/api/servicios/update_status', methods=['POST'])
def update_status_from_button():
    data = request.get_json()
    service_id = data.get('id_servicio')
    new_status = data.get('nuevo_estado')

    if not service_id or not new_status:
        return jsonify({"error": "Faltan datos (id_servicio, nuevo_estado)"}), 400

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("UPDATE servicio SET estado_s = %s WHERE id_servicio = %s;", (new_status, service_id))
            conn.commit()
            if cur.rowcount == 0:
                return jsonify({"error": "Servicio no encontrado"}), 404
            return jsonify({"success": True, "message": "Estado actualizado"})
    except Exception as e:
        if conn: conn.rollback()
        app.logger.error(f"API_UPDATE_STATUS_ERROR: {e}")
        return jsonify({"error": "Error interno al actualizar el estado", "detalle": str(e)}), 500
    finally:
        if conn: conn.close()
        
@app.route('/api/servicios/agregar', methods=['POST'])
def add_new_service():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No se recibieron datos"}), 400

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cerrajero_id = None

            if data.get('cerrajero') == 'Otro':
                nombre_nuevo, telefono_nuevo = data.get('otroCerrajero'), data.get('otroCerrajeroTelefono')
                cur.execute("SELECT id_cerrajero FROM cerrajero WHERE nombre_ce = %s", (nombre_nuevo,))
                existente = cur.fetchone()
                if existente:
                    cerrajero_id = existente[0]
                else:
                    cur.execute("INSERT INTO cerrajero (nombre_ce, telefono_ce) VALUES (%s, %s) RETURNING id_cerrajero;", (nombre_nuevo, telefono_nuevo))
                    cerrajero_id = cur.fetchone()[0]
            else:
                cur.execute("SELECT id_cerrajero FROM cerrajero WHERE nombre_ce = %s", (data.get('cerrajero'),))
                resultado = cur.fetchone()
                if not resultado:
                    raise ValueError(f"El cerrajero '{data.get('cerrajero')}' no fue encontrado.")
                cerrajero_id = resultado[0]

            cur.execute("SELECT id_cliente FROM cliente WHERE telefono_c = %s", (data.get('telefono_cliente'),))
            cliente_existente = cur.fetchone()
            if cliente_existente:
                cliente_id = cliente_existente[0]
                cur.execute("UPDATE cliente SET nombre_c = %s, direccion_c = %s, ciudad_c = %s WHERE id_cliente = %s", (data.get('cliente'), data.get('direccion'), data.get('municipio'), cliente_id))
            else:
                cur.execute("INSERT INTO cliente (nombre_c, telefono_c, direccion_c, ciudad_c) VALUES (%s, %s, %s, %s) RETURNING id_cliente;", (data.get('cliente'), data.get('telefono_cliente'), data.get('direccion'), data.get('municipio')))
                cliente_id = cur.fetchone()[0]

            fecha_db = datetime.strptime(data.get('fecha'), '%d/%m/%Y').strftime('%Y-%m-%d')
            hora_db = datetime.strptime(data.get('hora'), '%I:%M %p').strftime('%H:%M:%S')
            valor_limpio = int(''.join(filter(str.isdigit, data.get('valor', '0'))))
            
            cur.execute(
                "INSERT INTO servicio (fecha_s, hora_s, tipo_s, estado_s, monto_pago, metodo_pago, id_cliente, id_cerrajero) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);",
                (fecha_db, hora_db, data.get('tipo'), data.get('estado'), valor_limpio, data.get('metodo_pago'), cliente_id, cerrajero_id)
            )
            
            conn.commit()
            return jsonify({"success": True, "message": "Servicio agregado correctamente"}), 201

    except Exception as e:
        if conn: conn.rollback()
        app.logger.error(f"API_ADD_SERVICE_ERROR: {e}")
        return jsonify({"error": "Error interno al guardar el servicio", "detalle": str(e)}), 500
    finally:
        if conn: conn.close()

@app.route('/api/servicios/<int:service_id>', methods=['GET'])
def get_service_by_id(service_id):
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT s.id_servicio, s.fecha_s, s.hora_s, s.tipo_s, s.estado_s, 
                       s.monto_pago, s.metodo_pago, c.nombre_c, c.telefono_c, 
                       c.direccion_c, c.ciudad_c, ce.nombre_ce
                FROM servicio s
                JOIN cliente c ON s.id_cliente = c.id_cliente
                JOIN cerrajero ce ON s.id_cerrajero = ce.id_cerrajero
                WHERE s.id_servicio = %s;
            """, (service_id,))
            servicio = cur.fetchone()
            if servicio is None:
                return jsonify({"error": "Servicio no encontrado"}), 404
            
            servicio['fecha_s'] = servicio['fecha_s'].strftime('%d/%m/%Y')
            servicio['hora_s'] = servicio['hora_s'].strftime('%I:%M %p')
            return jsonify(servicio)
    except Exception as e:
        app.logger.error(f"API_GET_SERVICE_ID_ERROR: {e}")
        return jsonify({"error": "Error interno al obtener el servicio", "detalle": str(e)}), 500
    finally:
        if conn: conn.close()

@app.route('/api/servicios/<int:service_id>', methods=['PUT'])
def update_service(service_id):
    data = request.get_json()
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT id_cliente FROM cliente WHERE telefono_c = %s", (data['telefono_cliente'],))
            cliente_res = cur.fetchone()
            if cliente_res:
                cliente_id = cliente_res[0]
                cur.execute("UPDATE cliente SET nombre_c=%s, direccion_c=%s, ciudad_c=%s WHERE id_cliente=%s", 
                            (data['cliente'], data['direccion'], data['municipio'], cliente_id))
            else:
                cur.execute("INSERT INTO cliente (nombre_c, telefono_c, direccion_c, ciudad_c) VALUES (%s, %s, %s, %s) RETURNING id_cliente",
                            (data['cliente'], data['telefono_cliente'], data['direccion'], data['municipio']))
                cliente_id = cur.fetchone()[0]

            cerrajero_id = None
            if data.get('cerrajero') == 'Otro':
                nombre_nuevo, telefono_nuevo = data.get('otroCerrajero'), data.get('otroCerrajeroTelefono')
                if not nombre_nuevo:
                    raise ValueError("El nombre del nuevo cerrajero no puede estar vacío.")
                cur.execute("SELECT id_cerrajero FROM cerrajero WHERE nombre_ce = %s", (nombre_nuevo,))
                existente = cur.fetchone()
                if existente:
                    cerrajero_id = existente[0]
                else:
                    cur.execute("INSERT INTO cerrajero (nombre_ce, telefono_ce) VALUES (%s, %s) RETURNING id_cerrajero;", (nombre_nuevo, telefono_nuevo))
                    cerrajero_id = cur.fetchone()[0]
            else:
                cur.execute("SELECT id_cerrajero FROM cerrajero WHERE nombre_ce = %s", (data['cerrajero'],))
                cerrajero_res = cur.fetchone()
                if not cerrajero_res:
                    raise ValueError(f"Cerrajero '{data['cerrajero']}' no encontrado")
                cerrajero_id = cerrajero_res[0]

            fecha_db = datetime.strptime(data['fecha'], '%d/%m/%Y').strftime('%Y-%m-%d')
            hora_db = datetime.strptime(data['hora'], '%I:%M %p').strftime('%H:%M:%S')
            valor_limpio = int(''.join(filter(str.isdigit, str(data.get('valor', '0')))))

            cur.execute("""
                UPDATE servicio SET
                    fecha_s = %s, hora_s = %s, tipo_s = %s, estado_s = %s, 
                    monto_pago = %s, metodo_pago = %s, id_cliente = %s, id_cerrajero = %s
                WHERE id_servicio = %s;
            """, (fecha_db, hora_db, data['tipo'], data['estado'], valor_limpio, 
                  data['metodo_pago'], cliente_id, cerrajero_id, service_id))
            
            conn.commit()
            return jsonify({"success": True, "message": "Servicio actualizado correctamente"})
    except Exception as e:
        if conn: conn.rollback()
        app.logger.error(f"API_UPDATE_SERVICE_ERROR: {e}")
        return jsonify({"error": "Error interno al actualizar", "detalle": str(e)}), 500
    finally:
        if conn: conn.close()

@app.route('/api/servicios/<int:service_id>', methods=['DELETE'])
def delete_service(service_id):
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM servicio WHERE id_servicio = %s;", (service_id,))
            conn.commit()
            if cur.rowcount == 0:
                return jsonify({"error": "Servicio no encontrado para eliminar"}), 404
            return jsonify({"success": True, "message": "Servicio eliminado correctamente"})
    except Exception as e:
        if conn: conn.rollback()
        app.logger.error(f"API_DELETE_SERVICE_ERROR: {e}")
        return jsonify({"error": "Error interno al eliminar", "detalle": str(e)}), 500
    finally:
        if conn: conn.close()

# --- Lógica del Chatbot de WhatsApp (Versión con Hora Correcta) ---
AVAILABLE_SERVICES = [
    "Apertura de automóvil", "Apertura de caja fuerte", "Apertura de candado", "Apertura de motocicleta",
    "Apertura de puerta residencial", "Cambio de clave de automóvil", "Cambio de clave de motocicleta",
    "Cambio de clave residencial", "Duplicado de llave", "Elaboración de llaves", "Instalación de alarma",
    "Instalación de chapa", "Reparación general",
]

def get_session(sender_id):
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT session_data FROM whatsapp_sessions WHERE sender_id = %s;", (sender_id,))
            result = cur.fetchone()
            return result['session_data'] if result else None
    finally:
        if conn: conn.close()

def save_session(sender_id, session):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('''
                INSERT INTO whatsapp_sessions (sender_id, session_data, updated_at) VALUES (%s, %s, NOW() at time zone 'utc')
                ON CONFLICT (sender_id) DO UPDATE SET session_data = EXCLUDED.session_data, updated_at = EXCLUDED.updated_at;
            ''', (sender_id, json.dumps(session)))
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

def save_service_request(sender_id, data):
    conn = get_db_connection()
    try:
        # Definir la zona horaria de Colombia
        colombia_tz = pytz.timezone('America/Bogota')
        # Obtener la fecha y hora actual en esa zona horaria
        now_in_colombia = datetime.now(colombia_tz)
        current_date = now_in_colombia.strftime('%Y-%m-%d')
        current_time = now_in_colombia.strftime('%H:%M:%S')

        with conn.cursor() as cur:
            raw_phone = sender_id.split(':')[-1]
            phone_number = ''.join(filter(str.isdigit, raw_phone))

            if phone_number.startswith('57'):
                phone_number = phone_number[2:]

            cur.execute("SELECT id_cliente FROM cliente WHERE telefono_c = %s;", (phone_number,))
            client_result = cur.fetchone()

            if client_result:
                client_id = client_result[0]
                cur.execute("UPDATE cliente SET nombre_c = %s, direccion_c = %s, ciudad_c = %s WHERE id_cliente = %s;",
                            (data.get('nombre'), data.get('direccion'), data.get('ciudad'), client_id))
            else:
                cur.execute("INSERT INTO cliente (nombre_c, telefono_c, direccion_c, ciudad_c) VALUES (%s, %s, %s, %s) RETURNING id_cliente;",
                            (data.get('nombre'), phone_number, data.get('direccion'), data.get('ciudad')))
                client_id = cur.fetchone()[0]

            # Usar la fecha y hora de Colombia en lugar de CURRENT_DATE y CURRENT_TIME
            cur.execute(
                """
                INSERT INTO servicio (fecha_s, hora_s, tipo_s, estado_s, monto_pago, metodo_pago, id_cliente, id_cerrajero)
                VALUES (%s, %s, %s, 'pendiente', 0, 'Efectivo', %s, 1);
                """,
                (current_date, current_time, data.get('detalle_servicio'), client_id)
            )
            conn.commit()
    except Exception as e:
        app.logger.error(f"DATABASE_SAVE_ERROR: {e}")
        if conn: conn.rollback()
        raise
    finally:
        if conn: conn.close()

def get_summary_message(data):
    return (
        f"----- RESUMEN DE TU SOLICITUD -----\n\n" 
        f"👤 Nombre: {data.get('nombre', 'N/A')}\n" 
        f"🏙️ Ciudad: {data.get('ciudad', 'N/A')}\n" 
        f"📍 Dirección: {data.get('direccion', 'N/A')}\n" 
        f"🛠️ Servicio: {data.get('detalle_servicio', 'N/A')}\n\n" 
        "Escribe *confirmar* para guardar, *corregir* para cambiar algún dato, o *salir* para cancelar."
    )

def get_service_list_message():
    message = "¿Qué tipo de servicio de cerrajería necesitas?\n\n"
    for i, service in enumerate(AVAILABLE_SERVICES, 1):
        message += f"{i}. {service}\n"
    message += "\nResponde solo con el *número* del servicio que necesitas."
    return message

@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    sender_id = request.values.get('From', '')
    message_body = request.values.get('Body', '').strip()
    message_body_lower = message_body.lower()
    resp = MessagingResponse()
    msg = resp.message()

    session = get_session(sender_id)

    if not session or message_body_lower in ['hola', 'inicio', 'empezar']:
        session = {'state': 'AWAITING_NAME', 'data': {}}
        msg.body("¡Bienvenido al servicio de cerrajería! Para comenzar, por favor, dime tu nombre completo.")
        save_session(sender_id, session)
        return str(resp)
    
    if message_body_lower == 'salir':
        delete_session(sender_id)
        msg.body("Tu solicitud ha sido cancelada. Si quieres empezar de nuevo, solo escribe 'hola'.")
        return str(resp)

    state = session.get('state', 'AWAITING_NAME')
    data = session.get('data', {})

    # --- Máquina de Estados Principal ---
    if state == 'AWAITING_NAME':
        data['nombre'] = message_body.title()
        session['state'] = 'AWAITING_CITY'
        msg.body(f"Gracias, {data['nombre']}. ¿En qué ciudad te encuentras? (Bucaramanga, Piedecuesta o Floridablanca)")
    
    elif state == 'AWAITING_CITY':
        if message_body_lower not in ['bucaramanga', 'piedecuesta', 'floridablanca']:
            msg.body("Ciudad no válida. Por favor, elige entre *Bucaramanga*, *Piedecuesta* o *Floridablanca*.")
        else:
            data['ciudad'] = message_body.capitalize()
            session['state'] = 'AWAITING_ADDRESS'
            msg.body("Perfecto. Indícame la dirección completa (barrio, calle, número).")

    elif state == 'AWAITING_ADDRESS':
        data['direccion'] = message_body
        session['state'] = 'AWAITING_SERVICE_TYPE'
        msg.body(get_service_list_message())

    elif state == 'AWAITING_SERVICE_TYPE':
        try:
            choice = int(message_body)
            if 1 <= choice <= len(AVAILABLE_SERVICES):
                data['detalle_servicio'] = AVAILABLE_SERVICES[choice - 1]
                session['state'] = 'CONFIRMATION'
                msg.body(get_summary_message(data))
            else:
                msg.body("Opción no válida. Por favor, responde solo con el *número* del servicio que necesitas.")
        except (ValueError, IndexError):
            msg.body("Respuesta no válida. Por favor, usa solo el *número* del servicio de la lista.")

    # --- Flujo de Confirmación y Corrección ---
    elif state == 'CONFIRMATION':
        if message_body_lower == 'confirmar':
            try:
                save_service_request(sender_id, data)
                msg.body("¡Servicio confirmado! Tu solicitud ha sido guardada. Pronto un cerrajero se pondrá en contacto contigo.")
                delete_session(sender_id)
                return str(resp) 
            except Exception as e:
                app.logger.error(f"SAVE_REQUEST_FAILED: {e}")
                msg.body("Lo siento, hubo un error técnico al guardar tu solicitud. Por favor, intenta de nuevo escribiendo *confirmar*.")
        elif message_body_lower == 'corregir':
            session['state'] = 'AWAITING_CORRECTION_FIELD'
            msg.body("¿Qué dato deseas corregir? Responde con una sola palabra: *nombre*, *ciudad*, *direccion* o *servicio*.")
        else:
            msg.body("Opción no válida. Por favor, escribe *confirmar* para finalizar, *corregir* para cambiar un dato, o *salir* para cancelar.")

    elif state == 'AWAITING_CORRECTION_FIELD':
        field = message_body_lower
        if field == 'nombre':
            session['state'] = 'CORRECTING_NAME'
            msg.body("OK. Por favor, dime el nombre correcto.")
        elif field == 'ciudad':
            session['state'] = 'CORRECTING_CITY'
            msg.body("OK. ¿Cuál es la ciudad correcta? (Bucaramanga, Piedecuesta o Floridablanca)")
        elif field == 'direccion':
            session['state'] = 'CORRECTING_ADDRESS'
            msg.body("OK. Por favor, dime la dirección correcta.")
        elif field == 'servicio':
            session['state'] = 'CORRECTING_SERVICE_TYPE'
            msg.body(get_service_list_message())
        else:
            msg.body("No entendí. Por favor, elige una de las opciones: *nombre*, *ciudad*, *direccion* o *servicio*.")

    # --- Estados de Corrección Individuales ---
    elif state == 'CORRECTING_NAME':
        data['nombre'] = message_body.title()
        session['state'] = 'CONFIRMATION'
        msg.body(f"Dato actualizado.\n\n{get_summary_message(data)}")
    
    elif state == 'CORRECTING_CITY':
        if message_body_lower not in ['bucaramanga', 'piedecuesta', 'floridablanca']:
            msg.body("Ciudad no válida. Elige *Bucaramanga*, *Piedecuesta* o *Floridablanca*.")
        else:
            data['ciudad'] = message_body.capitalize()
            session['state'] = 'CONFIRMATION'
            msg.body(f"Dato actualizado.\n\n{get_summary_message(data)}")
            
    elif state == 'CORRECTING_ADDRESS':
        data['direccion'] = message_body
        session['state'] = 'CONFIRMATION'
        msg.body(f"Dato actualizado.\n\n{get_summary_message(data)}")

    elif state == 'CORRECTING_SERVICE_TYPE':
        try:
            choice = int(message_body)
            if 1 <= choice <= len(AVAILABLE_SERVICES):
                data['detalle_servicio'] = AVAILABLE_SERVICES[choice - 1]
                session['state'] = 'CONFIRMATION'
                msg.body(f"Dato actualizado.\n\n{get_summary_message(data)}")
            else:
                msg.body("Opción no válida. Por favor, responde solo con el *número* del servicio.")
        except (ValueError, IndexError):
            msg.body("Respuesta no válida. Por favor, usa solo el *número* del servicio.")
    
    else:
        msg.body("Lo siento, ocurrió un error y perdí el hilo de la conversación. Escribe 'hola' para empezar de nuevo.")
        delete_session(sender_id)

    session['data'] = data
    save_session(sender_id, session)
    return str(resp)

# --- Punto de Entrada de la Aplicación ---
if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)
