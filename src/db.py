"""Esquema y acceso a SQLite (un solo archivo, sin servidor).

La tabla pacientes guarda datos básicos de contacto (nombre, celular, etc.)
para uso en el computador de la clínica.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "blissens.db"

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS pacientes (
    paciente_id   TEXT PRIMARY KEY,          -- hash con sal (clave estable entre cargas)
    id_software   INTEGER,                   -- '# Paciente' del software
    nombre        TEXT,
    apellidos     TEXT,
    celular       TEXT,
    telefono      TEXT,
    email         TEXT,
    antiguedad    TEXT,                      -- Nuevo | Antiguo | Desconocida
    tipo_paciente TEXT,                      -- ej. Rehabilitacion; NULL si no viene
    primera_cita  TEXT                       -- fecha ISO de la primera cita vista en la base
);

CREATE TABLE IF NOT EXISTS citas (
    cita_id            INTEGER PRIMARY KEY,  -- '# Cita' del software (clave de la carga idempotente)
    paciente_id        TEXT NOT NULL REFERENCES pacientes(paciente_id),
    tratamiento_ref    TEXT,                 -- hash de '# Tratamiento'
    fecha              TEXT NOT NULL,        -- ISO yyyy-mm-dd
    hora_inicio        TEXT,                 -- HH:MM, solo si viene en el export con horas
    hora_fin           TEXT,
    sillon             TEXT,
    tipo_cita          TEXT,                 -- Diagnóstico | Tratamiento
    servicio           TEXT,                 -- categoría derivada del comentario (sin texto libre)
    estado_original    TEXT NOT NULL,
    estado             TEXT NOT NULL,        -- atendido | cambio_fecha | anulado | anulado_paciente
                                             -- | no_asiste | confirmada | agendada
    fuente             TEXT NOT NULL,        -- archivo de origen o 'api'
    cargada_en         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_citas_paciente ON citas(paciente_id, fecha);
CREATE INDEX IF NOT EXISTS ix_citas_fecha    ON citas(fecha);

-- Cada vez que una cita ya cargada cambia de estado queda registro.
CREATE TABLE IF NOT EXISTS citas_historial (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cita_id         INTEGER NOT NULL REFERENCES citas(cita_id),
    estado_anterior TEXT,
    estado_nuevo    TEXT NOT NULL,
    cambiado_en     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eventos_perdida (
    evento_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cita_id            INTEGER REFERENCES citas(cita_id),
    paciente_id        TEXT NOT NULL REFERENCES pacientes(paciente_id),
    -- tipo = qué pasó. El grupo de la cola (tratamiento / nuevo / inactivo) se calcula en rules.py
    -- porque depende de la antigüedad del paciente.
    tipo               TEXT NOT NULL CHECK (tipo IN
                         ('cancelacion','no_asistencia','diagnostico_sin_continuidad','inactivo')),
    fecha_evento       TEXT NOT NULL,        -- desde aquí se cuentan los días 3, 7 y 15
    motivo_cancelacion TEXT,                 -- obligatorio para tipo = cancelacion (lo llena la auxiliar)
    estado_cola        TEXT NOT NULL DEFAULT 'abierto'
                         CHECK (estado_cola IN ('abierto','recuperado','sin_recuperar')),
    UNIQUE (cita_id, tipo)
);

CREATE TABLE IF NOT EXISTS intentos_contacto (
    intento_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    evento_id     INTEGER NOT NULL REFERENCES eventos_perdida(evento_id),
    fecha         TEXT NOT NULL,
    dia_protocolo INTEGER NOT NULL CHECK (dia_protocolo IN (3, 7, 15)),
    canal         TEXT NOT NULL DEFAULT 'whatsapp',
    resultado     TEXT NOT NULL CHECK (resultado IN
                    ('sin_respuesta','reagendo','rechazo','otro')),
    nota          TEXT
);

-- El evento nace desde la agenda sin motivo; no se puede cerrar una cancelación sin motivo.
CREATE TRIGGER IF NOT EXISTS trg_motivo_obligatorio_cierre
BEFORE UPDATE OF estado_cola ON eventos_perdida
WHEN NEW.tipo = 'cancelacion' AND (NEW.motivo_cancelacion IS NULL OR TRIM(NEW.motivo_cancelacion) = '')
     AND NEW.estado_cola <> 'abierto'
BEGIN
    SELECT RAISE(ABORT, 'Falta el motivo de cancelación');
END;

CREATE TABLE IF NOT EXISTS huecos (
    fecha               TEXT NOT NULL,
    hora_inicio         TEXT NOT NULL,
    hora_fin            TEXT NOT NULL,
    sillon              TEXT,
    cita_origen_id      INTEGER NOT NULL REFERENCES citas(cita_id),
    ocupado_por_cita_id INTEGER REFERENCES citas(cita_id),
    PRIMARY KEY (cita_origen_id)
);
"""

# Columnas añadidas después del esquema inicial (bases ya creadas).
PACIENTES_COLS_EXTRA = {
    "nombre": "TEXT",
    "apellidos": "TEXT",
    "celular": "TEXT",
    "telefono": "TEXT",
    "email": "TEXT",
}


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    p = Path(path) if path else DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)
    _migrar_pacientes(con)
    con.commit()


def _migrar_pacientes(con: sqlite3.Connection) -> None:
    existentes = {r[1] for r in con.execute("PRAGMA table_info(pacientes)")}
    for col, tipo in PACIENTES_COLS_EXTRA.items():
        if col not in existentes:
            con.execute(f"ALTER TABLE pacientes ADD COLUMN {col} {tipo}")


def falta_datos_basicos(con: sqlite3.Connection) -> bool:
    """True si hay pacientes sin nombre (carga antigua sin datos básicos)."""
    n = con.execute("SELECT COUNT(*) FROM pacientes").fetchone()[0]
    if n == 0:
        return True
    sin = con.execute(
        "SELECT COUNT(*) FROM pacientes WHERE nombre IS NULL OR TRIM(nombre) = ''"
    ).fetchone()[0]
    return sin > 0
