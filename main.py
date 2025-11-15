
import os
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import psycopg2
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv() # Carga las variables de entorno desde el archivo .env

app = Flask(__name__)

# --- Lista de Servicios Disponibles ---
AVAILABLE_SERVICES = [
    "Apertura de automóvil",
    "Apertura de caja fuerte",
    "Apertura de candado",
    "Apertura de motocicleta",
    "Apertura de puerta residencial",
    "Cambio de clave de automóvil",
    "Cambio de clave de motocicleta",
    "Cambio de clave residencial",
    "Duplicado de llave",
    "Elaboración de llaves",
    "Instalación de alarma",
    "Instalación de chapa",
    "Reparación general",
]

# --- Base de Datos ---
def get_db_connection():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise ValueError("No se ha configurado la variable de entorno DATABASE_URL")
    result = urlparse(db_url)
    return psycopg2.connect(
        dbname=result.path[1:],
        user=result.username,
        password=result.password,
        host=result.hostname,
        port=result.port,
        sslmode='require'
    )

def save_service_request(sender_id, data):
    phone_number = sender_id.split(':')[-1]
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 1. Buscar o crear el cliente
    cur.execute("SELECT id_cliente FROM cliente WHERE telefono_c = %s;", (phone_number,))
    client_id_result = cur.fetchone()
    
    if client_id_result:
        client_id = client_id_result[0]
        # Opcional: Actualizar datos del cliente si es necesario
        cur.execute(
            "UPDATE cliente SET nombre_c = %s, direccion_c = %s, ciudad_c = %s WHERE id_cliente = %s;",
            (data['nombre'], data['direccion'], data['ciudad'], client_id)
        )
    else:
        # CORRECCIÓN: Usar nombre_c, direccion_c, ciudad_c
        cur.execute(
            "INSERT INTO cliente (nombre_c, telefono_c, direccion_c, ciudad_c) VALUES (%s, %s, %s, %s) RETURNING id_cliente;",
            (data['nombre'], phone_number, data['direccion'], data['ciudad'])
        )
        client_id = cur.fetchone()[0]

    # 2. Preparar datos para la tabla servicio
    # CORRECCIÓN: Asignar un valor para detalle_pago si el método es nequi
    detalle_pago_val = 'N/A' if data['metodo_pago'].lower() == 'nequi' else None

    # 3. Insertar en la tabla servicio con las columnas correctas
    # CORRECCIÓN: Usar tipo_s, estado_s y añadir los campos faltantes
    cur.execute(
        """INSERT INTO servicio (id_cliente, fecha_s, hora_s, tipo_s, estado_s, monto_pago, metodo_pago, detalle_pago, id_cerrajero)
        VALUES (%s, CURRENT_DATE, CURRENT_TIME, %s, 'pendiente', 0, %s, %s, 1);""",
        (client_id, data['detalle_servicio'], data['metodo_pago'], detalle_pago_val)
    )
    
    conn.commit()
    cur.close()
    conn.close()

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
    resp = MessagingResponse()
    msg = resp.message()

    session = user_sessions.get(sender_id, {'state': 'awaiting_welcome', 'data': {}})

    if message_body == 'salir':
        msg.body("Tu solicitud ha sido cancelada. Gracias.")
        user_sessions.pop(sender_id, None)
        return str(resp)

    # Estado inicial
    if session.get('state') == 'awaiting_welcome':
        msg.body("¡Bienvenido al servicio de cerrajería! Para comenzar, por favor dime tu nombre completo.")
        session['state'] = 'awaiting_name'
        user_sessions[sender_id] = session
        return str(resp)

    state = session.get('state')
    data = session.get('data', {})

    # --- Flujo de Corrección ---
    if state == 'awaiting_correction_new_value':
        field_to_correct = session.pop('field_to_correct')
        is_valid = False
        if field_to_correct == 'nombre':
            data['nombre'] = request.values.get('Body', '').strip().title()
            is_valid = True
        elif field_to_correct == 'ciudad':
            if message_body in ['bucaramanga', 'piedecuesta', 'floridablanca']:
                data['ciudad'] = message_body
                is_valid = True
            else:
                msg.body("Ciudad no válida. Por favor, elige entre Bucaramanga, Piedecuesta o Floridablanca.")
                session['field_to_correct'] = field_to_correct
        elif field_to_correct == 'direccion':
            data['direccion'] = request.values.get('Body', '').strip()
            is_valid = True
        elif field_to_correct == 'servicio':
            try:
                choice = int(message_body)
                if 1 <= choice <= len(AVAILABLE_SERVICES):
                    data['detalle_servicio'] = AVAILABLE_SERVICES[choice - 1]
                    is_valid = True
                else:
                    msg.body(f"Opción no válida. Por favor, elige un número entre 1 y {len(AVAILABLE_SERVICES)}.")
                    session['field_to_correct'] = field_to_correct
            except ValueError:
                msg.body("Respuesta no válida. Por favor, responde solo con el número del servicio.")
                session['field_to_correct'] = field_to_correct
        elif field_to_correct == 'pago':
            if message_body in ['efectivo', 'nequi']:
                data['metodo_pago'] = message_body
                is_valid = True
            else:
                msg.body("Método de pago no válido. Por favor, escribe 'Efectivo' o 'Nequi'.")
                session['field_to_correct'] = field_to_correct

        if is_valid:
            msg.body(get_summary_message(data))
            session['state'] = 'awaiting_confirmation'
        else:
            session['state'] = 'awaiting_correction_new_value'
        user_sessions[sender_id] = session
        return str(resp)

    # --- Flujo Principal ---
    if state == 'awaiting_name':
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
                user_sessions.pop(sender_id, None)
            except Exception as e:
                # Log the exception for debugging
                app.logger.error(f"Error saving to database: {e}")
                msg.body("Hubo un error al guardar tu solicitud. Por favor, intenta de nuevo más tarde.")
        elif message_body == 'corregir':
            msg.body("¿Qué dato deseas corregir? (nombre, ciudad, direccion, servicio, pago)")
            session['state'] = 'awaiting_correction_choice'
        else:
            msg.body("Opción no válida. Escribe 'confirmar', 'corregir' o 'salir'.")
    elif state == 'awaiting_correction_choice':
        field = message_body
        correction_map = {
            'nombre': ("Por favor, dime el nombre correcto.", None),
            'ciudad': ("¿En qué ciudad te encuentras? (Bucaramanga, Piedecuesta o Floridablanca)", None),
            'direccion': ("Por favor, dime la dirección correcta.", None),
            'servicio': (get_service_list_message(), None),
            'pago': ("¿Cómo prefieres pagar? (Efectivo o Nequi)", None)
        }
        if field in correction_map:
            prompt, _ = correction_map[field]
            msg.body(prompt)
            session['state'] = 'awaiting_correction_new_value'
            session['field_to_correct'] = field
        else:
            msg.body("Dato no válido. Por favor, elige entre: nombre, ciudad, direccion, servicio, pago.")

    session['data'] = data
    user_sessions[sender_id] = session
    return str(resp)

if __name__ == "__main__":
    app.run(debug=True)
