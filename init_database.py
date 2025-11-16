
import os
import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv

# --- Configuración Inicial ---
load_dotenv()

def get_db_connection():
    """Establece la conexión con la base de datos usando la URL de entorno."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise ValueError("La variable de entorno DATABASE_URL no está configurada.")
    return psycopg2.connect(db_url, sslmode='require')

def column_exists(cursor, table_name, column_name):
    """Verifica si una columna existe en una tabla."""
    cursor.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
    """, (table_name, column_name))
    return cursor.fetchone() is not None

def initialize_database():
    """
    Asegura que la base de datos tenga la estructura mínima requerida
    sin eliminar datos existentes. Añade columnas si faltan.
    """
    conn = None
    try:
        conn = get_db_connection()
        print("Conexión a la base de datos exitosa.")

        with conn.cursor() as cur:
            print("Verificando y actualizando estructura de la base de datos...")

            # 1. Asegurar columnas en la tabla 'cliente'
            if not column_exists(cur, 'cliente', 'direccion_c'):
                cur.execute("ALTER TABLE cliente ADD COLUMN direccion_c TEXT;")
                print("- Columna 'direccion_c' añadida a la tabla 'cliente'.")
            else:
                print("- Columna 'direccion_c' ya existe en 'cliente'.")

            if not column_exists(cur, 'cliente', 'ciudad_c'):
                cur.execute("ALTER TABLE cliente ADD COLUMN ciudad_c VARCHAR(100);")
                print("- Columna 'ciudad_c' añadida a la tabla 'cliente'.")
            else:
                print("- Columna 'ciudad_c' ya existe en 'cliente'.")

            # 2. Asegurar existencia de la tabla 'cerrajero' (sin disponibilidad)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS cerrajero (
                    id_cerrajero SERIAL PRIMARY KEY,
                    nombre_ce VARCHAR(255) NOT NULL,
                    telefono_ce VARCHAR(20)
                );
            """)
            print("- Tabla 'cerrajero' verificada/creada.")

            # 3. Asegurar existencia de la tabla 'servicio'
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

            # 4. Asegurar cerrajero por defecto (sin disponibilidad)
            cur.execute("SELECT 1 FROM cerrajero WHERE nombre_ce = 'Por Asignar';")
            if cur.fetchone() is None:
                cur.execute("""
                    INSERT INTO cerrajero (nombre_ce, telefono_ce)
                    VALUES ('Por Asignar', '0000000000');
                """)
                print("- Cerrajero por defecto 'Por Asignar' insertado.")
            else:
                print("- Cerrajero por defecto 'Por Asignar' ya existe.")

            conn.commit()
        print("\n¡Éxito! La base de datos ha sido verificada y actualizada sin perder datos.")

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
    print("Iniciando script de migración y verificación de base de datos...")
    initialize_database()
