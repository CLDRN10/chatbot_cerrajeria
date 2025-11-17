import os
import psycopg2
from dotenv import load_dotenv

# --- Configuración de Entorno ---
load_dotenv() # Carga las variables desde el archivo .env

# --- Conexión a la Base de Datos ---
DB_URL = os.environ.get("DATABASE_URL")
if not DB_URL:
    raise ValueError("No se encontró la variable de entorno DATABASE_URL. Asegúrate de que esté en el .env")

conn = psycopg2.connect(DB_URL, sslmode='require')
cur = conn.cursor()

# --- Definición y Creación de Tablas ---

# 1. Tabla de Cerrajeros
cur.execute("""
DROP TABLE IF EXISTS cerrajero CASCADE;
CREATE TABLE cerrajero (
    id_cerrajero SERIAL PRIMARY KEY,
    nombre_ce VARCHAR(100) NOT NULL UNIQUE,
    telefono_ce VARCHAR(15) NOT NULL,
    CONSTRAINT ck1_cerrajero CHECK (telefono_ce ~ '^[0-9]+$')
);
""")

# 2. Tabla de Clientes
cur.execute("""
DROP TABLE IF EXISTS cliente CASCADE;
CREATE TABLE cliente (
    id_cliente SERIAL PRIMARY KEY,
    nombre_c VARCHAR(100) NOT NULL,
    telefono_c VARCHAR(15) NOT NULL UNIQUE,
    direccion_c VARCHAR(255) NOT NULL,
    ciudad_c VARCHAR(50) NOT NULL
);
""")

# 3. Tabla de Servicios (CORREGIDA - SIN detalle_pago)
cur.execute("""
DROP TABLE IF EXISTS servicio CASCADE;
CREATE TABLE servicio (
    id_servicio SERIAL PRIMARY KEY,
    fecha_s DATE NOT NULL,
    hora_s TIME NOT NULL,
    tipo_s VARCHAR(100) NOT NULL,
    estado_s VARCHAR(20) NOT NULL DEFAULT 'pendiente',
    monto_pago NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    metodo_pago VARCHAR(20) NOT NULL,
    id_cliente INT NOT NULL,
    id_cerrajero INT NOT NULL,
    CONSTRAINT fk_cliente FOREIGN KEY (id_cliente) REFERENCES cliente (id_cliente),
    CONSTRAINT fk_cerrajero FOREIGN KEY (id_cerrajero) REFERENCES cerrajero (id_cerrajero),
    CONSTRAINT ck1_servicio CHECK (estado_s IN ('pendiente', 'en proceso', 'finalizado', 'cancelado')),
    CONSTRAINT ck2_servicio CHECK (monto_pago >= 0),
    CONSTRAINT ck3_servicio CHECK (metodo_pago IN ('efectivo', 'nequi'))
);
""")

# 4. Tabla de Sesiones de WhatsApp (Para el Chatbot)
cur.execute("""
DROP TABLE IF EXISTS whatsapp_sessions CASCADE;
CREATE TABLE whatsapp_sessions (
    id SERIAL PRIMARY KEY,
    sender_id VARCHAR(255) NOT NULL UNIQUE,
    session_data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
""")

# --- Inserción de Datos Iniciales ---

# Insertar un cerrajero por defecto para el chatbot
cur.execute("INSERT INTO cerrajero (nombre_ce, telefono_ce) VALUES (%s, %s);", ('Jose Hernández', '3111234567'))

print("Base de datos inicializada correctamente.")
print("- Se eliminaron las tablas existentes.")
print("- Se crearon las tablas: cerrajero, cliente, servicio, whatsapp_sessions.")
print("- Se insertó un cerrajero por defecto.")

# --- Cierre de Conexión ---
conn.commit()
cur.close()
conn.close()
