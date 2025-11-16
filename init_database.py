
import os
import psycopg2
from dotenv import load_dotenv

# --- Configuración Inicial ---
load_dotenv()

def get_db_connection():
    """Establece la conexión con la base de datos usando la URL de entorno."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise ValueError("La variable de entorno DATABASE_URL no está configurada.")
    return psycopg2.connect(db_url, sslmode='require')

def initialize_database():
    """
    Crea todas las tablas necesarias para la aplicación si no existen.
    También inserta un cerrajero por defecto para las asignaciones iniciales.
    """
    conn = None
    try:
        conn = get_db_connection()
        print("Conexión a la base de datos exitosa.")

        with conn.cursor() as cur:
            # 1. Tabla de Clientes
            cur.execute("""
                CREATE TABLE IF NOT EXISTS cliente (
                    id_cliente SERIAL PRIMARY KEY,
                    nombre_c VARCHAR(255) NOT NULL,
                    telefono_c VARCHAR(20) UNIQUE NOT NULL,
                    direccion_c TEXT,
                    ciudad_c VARCHAR(100)
                );
            """)
            print("- Tabla 'cliente' verificada/creada.")

            # 2. Tabla de Cerrajeros
            cur.execute("""
                CREATE TABLE IF NOT EXISTS cerrajero (
                    id_cerrajero SERIAL PRIMARY KEY,
                    nombre_ce VARCHAR(255) NOT NULL,
                    telefono_ce VARCHAR(20),
                    disponibilidad BOOLEAN DEFAULT true
                );
            """)
            print("- Tabla 'cerrajero' verificada/creada.")

            # 3. Tabla de Servicios
            cur.execute("""
                CREATE TABLE IF NOT EXISTS servicio (
                    id_servicio SERIAL PRIMARY KEY,
                    fecha_s DATE NOT NULL,
                    hora_s TIME NOT NULL,
                    tipo_s VARCHAR(255) NOT NULL,
                    estado_s VARCHAR(50) DEFAULT 'pendiente',
                    monto_pago NUMERIC(10, 2) DEFAULT 0.00,
                    metodo_pago VARCHAR(50),
                    detalle_pago TEXT,
                    id_cliente INTEGER REFERENCES cliente(id_cliente),
                    id_cerrajero INTEGER REFERENCES cerrajero(id_cerrajero)
                );
            """)
            print("- Tabla 'servicio' verificada/creada.")

            # 4. Tabla para Sesiones de WhatsApp
            cur.execute("""
                CREATE TABLE IF NOT EXISTS whatsapp_sessions (
                    sender_id VARCHAR(255) PRIMARY KEY,
                    session_data JSONB,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() at time zone 'utc')
                );
            """)
            print("- Tabla 'whatsapp_sessions' verificada/creada.")

            # 5. Insertar cerrajero por defecto (si no existe)
            cur.execute("SELECT 1 FROM cerrajero WHERE nombre_ce = 'Por Asignar';")
            if cur.fetchone() is None:
                cur.execute("""
                    INSERT INTO cerrajero (nombre_ce, telefono_ce, disponibilidad)
                    VALUES ('Por Asignar', '0000000000', false);
                """)
                print("- Cerrajero por defecto 'Por Asignar' insertado.")
            else:
                print("- Cerrajero por defecto 'Por Asignar' ya existe.")

            conn.commit()
        print("\n¡Éxito! Todas las tablas han sido verificadas o creadas.")

    except psycopg2.Error as e:
        print(f"\nError de base de datos: {e}")
        if conn:
            conn.rollback()
    except Exception as e:
        print(f"\nOcurrió un error inesperado: {e}")
    finally:
        if conn:
            conn.close()
            print("Conexión a la base de datos cerrada.")

if __name__ == "__main__":
    print("Iniciando script de inicialización de base de datos...")
    initialize_database()
