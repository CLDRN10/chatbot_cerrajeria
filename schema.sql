-- Este archivo contiene el esquema de la base de datos del proyecto.
-- No se ejecuta automáticamente, sirve como referencia para el desarrollo.

-- TABLA CLIENTE
CREATE TABLE cliente (
    id_cliente SERIAL CONSTRAINT pk_cliente PRIMARY KEY,
    nombre_c VARCHAR(30) NOT NULL,
    telefono_c VARCHAR(15) NOT NULL 
        CONSTRAINT ck1_cliente CHECK (telefono_c ~ '^[0-9]{7,13}$'),
    direccion_c VARCHAR(50),
    ciudad_c VARCHAR(15) NOT NULL
        CONSTRAINT ck2_cliente CHECK (
            LOWER(ciudad_c) IN ('bucaramanga', 'piedecuesta', 'floridablanca')
        )
);

-- TABLA CERRAJERO
CREATE TABLE cerrajero (
    id_cerrajero SERIAL CONSTRAINT pk_cerrajero PRIMARY KEY,
    nombre_ce VARCHAR(30) NOT NULL,
    telefono_ce VARCHAR(15) NOT NULL 
        CONSTRAINT ck1_cerrajero CHECK (telefono_ce ~ '^[0-9]+$'),
    CONSTRAINT uq1_cerrajero UNIQUE (telefono_ce)
);

-- TABLA SERVICIO
CREATE TABLE servicio (
    id_servicio SERIAL CONSTRAINT pk_servicio PRIMARY KEY,
    fecha_s DATE NOT NULL,
    hora_s TIME NOT NULL,
    tipo_s VARCHAR(100) NOT NULL,
    estado_s VARCHAR(20) DEFAULT 'pendiente' 
        CONSTRAINT ck1_servicio CHECK (estado_s IN ('pendiente', 'en proceso', 'finalizado')),
    monto_pago NUMERIC(10,2) NOT NULL 
        CONSTRAINT ck2_servicio CHECK (monto_pago >= 0),
    metodo_pago VARCHAR(30) NOT NULL 
        CONSTRAINT ck3_servicio CHECK (
            LOWER(metodo_pago) IN ('efectivo', 'nequi')
        ),
    detalle_pago VARCHAR(30),
    id_cliente INT NOT NULL,
    id_cerrajero INT NOT NULL,
    CONSTRAINT fk1_servicio FOREIGN KEY (id_cliente) 
        REFERENCES cliente (id_cliente) ON DELETE CASCADE,
    CONSTRAINT fk2_servicio FOREIGN KEY (id_cerrajero) 
        REFERENCES cerrajero (id_cerrajero) ON DELETE RESTRICT,
    CONSTRAINT ck4_servicio CHECK (
        (LOWER(metodo_pago) = 'nequi' AND detalle_pago IS NOT NULL)
        OR (LOWER(metodo_pago) = 'efectivo' AND detalle_pago IS NULL)
    )
);

-- TABLA HISTORIAL DE ESTADOS
CREATE TABLE historial_estado (
    id_historial SERIAL PRIMARY KEY,
    id_servicio INT NOT NULL 
        REFERENCES servicio (id_servicio) ON DELETE CASCADE,
    id_cerrajero INT 
        REFERENCES cerrajero (id_cerrajero) ON DELETE SET NULL,
    estado_anterior VARCHAR(20) NOT NULL,
    estado_nuevo VARCHAR(20) NOT NULL,
    fecha_cambio TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    observacion TEXT
);