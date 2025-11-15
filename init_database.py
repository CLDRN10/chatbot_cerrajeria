
import os
import psycopg2
from dotenv import load_dotenv

# --- Script de Inicialización Manual de la Base de Datos ---

def init_db():
    """Crea la tabla de sesiones si no existe. Se debe ejecutar manualmente."""
    load_dotenv()
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: La variable de entorno DATABASE_URL no está configurada.")
        return

    conn = None
    try:
        conn = psycopg2.connect(db_url, sslmode='require')
        with conn.cursor() as cur:
            print("Conectado a la base de datos. Creando tabla si no existe...")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS whatsapp_sessions (
                    sender_id VARCHAR(255) PRIMARY KEY,
                    session_data JSONB,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() at time zone 'utc')
                );
            """)
            conn.commit()
        print("¡Éxito! La tabla 'whatsapp_sessions' ha sido verificada o creada.")
    except psycopg2.OperationalError as e:
        print(f"ERROR DE CONEXIÓN: No se pudo conectar a la base de datos.")
        print(f"Detalle: {e}")
    except Exception as e:
        print(f"ERROR INESPERADO: {e}")
    finally:
        if conn:
            conn.close()
            print("Conexión cerrada.")

if __name__ == "__main__":
    print("Este script creará la tabla necesaria para las sesiones del chatbot.")
    confirm = input("¿Estás seguro de que deseas continuar? (s/n): ")
    if confirm.lower() == 's':
        init_db()
    else:
        print("Operación cancelada.")
