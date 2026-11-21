"""Lee los Excel exportados y carga a SQLite de forma idempotente.

Uso:
    python -m src.load                      # usa los Excel de la carpeta «documentos iniciales»
    python -m src.load --estados X --horas Y
"""
from __future__ import annotations

import argparse
import hashlib
import re
import secrets
import unicodedata
from datetime import datetime
from pathlib import Path

import pandas as pd

from .db import DB_PATH, ROOT, connect, falta_datos_basicos, init_db

DOCS_INICIALES = ROOT / "documentos iniciales"
ESTADOS_XLSX = DOCS_INICIALES / "Agenda citas y estados .xlsx"
HORAS_XLSX = DOCS_INICIALES / "Agenda y citas .xlsx"
SALT_PATH = ROOT / "data" / ".salt"

ESTADO_MAP = {
    "atendido": "atendido",
    "cambio de fecha": "cambio_fecha",
    "anulado": "anulado",
    "anulado por pcte. via whatsapp": "anulado_paciente",
    "no asiste": "no_asiste",
    "confirmado por telefono": "confirmada",
    "confirmado por pcte. via whatsapp": "confirmada",
    "confirmado por email": "confirmada",
    "no confirmado": "agendada",
    "notif. automatica via whatsapp": "agendada",
    "notificado via email": "agendada",
    "notif. whatsapp fallida": "agendada",
}

# Categorías derivadas del comentario libre: no se guarda el texto completo.
SERVICIO_REGLAS = [
    ("alineadores", r"alineador|alineaores|refinamiento"),
    ("ortodoncia", r"ortodoncia|retenedor|retendor"),
    ("laboratorio", r"\blab\b|laboratorio|corona|carilla|impresion|scaneo|escaneo|provisional|cementacion|incrustracion|preparacion"),
    ("implantes", r"implante"),
    ("cirugia", r"cirugia|exodoncia|cordales"),
    ("endodoncia", r"endodoncia"),
    ("urgencia", r"urgencia"),
    ("limpieza", r"limpieza|fluor|barniz"),
    ("blanqueamiento", r"blanqueamiento"),
    ("resina", r"resina"),
    ("placa", r"placa|desprogramador|bruxismo"),
    ("valoracion", r"valoracion|cita virtual|explicacion plan"),
    ("revision", r"revision|control|mantenimiento"),
    ("continuacion", r"continu|etapa|iniciar"),
]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().lower()


def normalizar_estado(s: str) -> str:
    return ESTADO_MAP.get(_norm(s), "agendada")


def categoria_servicio(comentario) -> str | None:
    if pd.isna(comentario):
        return None
    t = _norm(comentario)
    for cat, patron in SERVICIO_REGLAS:
        if re.search(patron, t):
            return cat
    return "otro"


def _salt() -> str:
    SALT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not SALT_PATH.exists():
        SALT_PATH.write_text(secrets.token_hex(16))
    return SALT_PATH.read_text().strip()


def _hash(valor, prefijo: str, salt: str) -> str:
    return prefijo + hashlib.sha256(f"{salt}:{valor}".encode()).hexdigest()[:10]


def _hora(v) -> str | None:
    if pd.isna(v):
        return None
    return str(v)[:5]


def _txt(v) -> str | None:
    if pd.isna(v):
        return None
    s = re.sub(r"\s+", " ", str(v).strip())
    if not s or s in {"-", "nan", "None"}:
        return None
    return s


def _tel(v) -> str | None:
    if pd.isna(v):
        return None
    if isinstance(v, float):
        v = int(v) if v == int(v) else v
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    if not s or s in {"-", "nan", "None"}:
        return None
    return s


def _primero_no_nulo(s: pd.Series):
    for v in s:
        if pd.notna(v) and v is not None and str(v).strip() not in {"", "-"}:
            return v
    return None


def preparar(estados: Path, horas: Path | None, salt: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve (citas, pacientes) con datos básicos de contacto."""
    a = pd.read_excel(estados)
    df = pd.DataFrame(
        {
            "cita_id": a["# Cita"].astype(int),
            "id_soft": a["# Paciente"].astype(int),
            "tratamiento_ref": a["# Tratamiento"].map(lambda x: _hash(x, "T", salt)),
            "fecha": pd.to_datetime(a["Fecha Cita"]).dt.strftime("%Y-%m-%d"),
            "tipo_cita": a["Tratamiento o Diagnóstico"],
            "estado_original": a["Estado actual cita"],
            "antig": a["Antigüedad paciente"],
            "nombre": a["Nombre Paciente"].map(_txt),
            "apellidos": a["Apellidos Paciente"].map(_txt),
        }
    )
    df["hora_inicio"] = df["hora_fin"] = df["sillon"] = df["servicio"] = None
    df["tipo_paciente"] = None
    df["celular"] = df["telefono"] = df["email"] = None

    if horas is not None and Path(horas).exists():
        b = pd.read_excel(horas).drop_duplicates("# Cita").set_index("# Cita")
        m = df["cita_id"].map
        df["hora_inicio"] = m(b["Hora Inicio Cita"].map(_hora))
        df["hora_fin"] = m(b["Hora Fin Cita"].map(_hora))
        df["sillon"] = m(b["Sillón (Recurso)"])
        df["servicio"] = m(b["Comentario Cita"].map(categoria_servicio))
        tp = b["Tipo Paciente"].replace("-", pd.NA)
        df["tipo_paciente"] = m(tp)

        # Contacto y nombre (el export con horas suele traer celular/email).
        contactos = (
            pd.read_excel(horas)
            .assign(
                id_soft=lambda x: x["# Paciente"].astype(int),
                nombre=lambda x: x["Nombre Paciente"].map(_txt),
                apellidos=lambda x: x["Apellidos Paciente"].map(_txt),
                celular=lambda x: x["Celular"].map(_tel),
                telefono=lambda x: x["Teléfono"].map(_tel),
                email=lambda x: x["E-Mail"].map(_txt),
            )
            .groupby("id_soft", as_index=False)
            .agg(
                nombre=("nombre", _primero_no_nulo),
                apellidos=("apellidos", _primero_no_nulo),
                celular=("celular", _primero_no_nulo),
                telefono=("telefono", _primero_no_nulo),
                email=("email", _primero_no_nulo),
            )
            .set_index("id_soft")
        )
        for col in ("nombre", "apellidos", "celular", "telefono", "email"):
            desde_horas = df["id_soft"].map(contactos[col])
            df[col] = df[col].where(df[col].notna(), desde_horas)

    df["estado"] = df["estado_original"].map(normalizar_estado)
    df["paciente_id"] = df["id_soft"].map(lambda x: _hash(x, "P", salt))

    def antiguedad(g: pd.Series) -> str:
        vals = set(g)
        if "Nuevo" in vals:
            return "Nuevo"
        if "Antiguo" in vals:
            return "Antiguo"
        return "Desconocida"

    pac = (
        df.groupby("paciente_id")
        .agg(
            id_software=("id_soft", "first"),
            nombre=("nombre", _primero_no_nulo),
            apellidos=("apellidos", _primero_no_nulo),
            celular=("celular", _primero_no_nulo),
            telefono=("telefono", _primero_no_nulo),
            email=("email", _primero_no_nulo),
            antiguedad=("antig", antiguedad),
            tipo_paciente=("tipo_paciente", _primero_no_nulo),
            primera_cita=("fecha", "min"),
        )
        .reset_index()
    )
    return df, pac


def cargar(con, citas: pd.DataFrame, pac: pd.DataFrame, fuente: str) -> dict:
    ahora = datetime.now().isoformat(timespec="seconds")
    res = {"nuevas": 0, "actualizadas": 0, "sin_cambio": 0}
    with con:
        for p in pac.itertuples(index=False):
            con.execute(
                """INSERT INTO pacientes(
                       paciente_id,id_software,nombre,apellidos,celular,telefono,email,
                       antiguedad,tipo_paciente,primera_cita)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(paciente_id) DO UPDATE SET
                     id_software=excluded.id_software,
                     nombre=COALESCE(excluded.nombre, pacientes.nombre),
                     apellidos=COALESCE(excluded.apellidos, pacientes.apellidos),
                     celular=COALESCE(excluded.celular, pacientes.celular),
                     telefono=COALESCE(excluded.telefono, pacientes.telefono),
                     email=COALESCE(excluded.email, pacientes.email),
                     antiguedad=excluded.antiguedad,
                     tipo_paciente=COALESCE(excluded.tipo_paciente, pacientes.tipo_paciente),
                     primera_cita=MIN(pacientes.primera_cita, excluded.primera_cita)""",
                (
                    p.paciente_id,
                    None if pd.isna(p.id_software) else int(p.id_software),
                    p.nombre if pd.notna(p.nombre) else None,
                    p.apellidos if pd.notna(p.apellidos) else None,
                    p.celular if pd.notna(p.celular) else None,
                    p.telefono if pd.notna(p.telefono) else None,
                    p.email if pd.notna(p.email) else None,
                    p.antiguedad,
                    p.tipo_paciente if pd.notna(p.tipo_paciente) else None,
                    p.primera_cita,
                ),
            )
        previos = {r["cita_id"]: r["estado"] for r in con.execute("SELECT cita_id, estado FROM citas")}
        for c in citas.itertuples(index=False):
            vals = (
                c.cita_id,
                c.paciente_id,
                c.tratamiento_ref,
                c.fecha,
                c.hora_inicio,
                c.hora_fin,
                c.sillon,
                c.tipo_cita,
                c.servicio,
                c.estado_original,
                c.estado,
                fuente,
                ahora,
            )
            vals = tuple(None if (v is not None and not isinstance(v, str) and pd.isna(v)) else v for v in vals)
            anterior = previos.get(c.cita_id)
            if anterior is None:
                con.execute("INSERT INTO citas VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", vals)
                res["nuevas"] += 1
            elif anterior != c.estado:
                con.execute(
                    """UPDATE citas SET fecha=?, hora_inicio=COALESCE(?,hora_inicio), hora_fin=COALESCE(?,hora_fin),
                       sillon=COALESCE(?,sillon), tipo_cita=?, servicio=COALESCE(?,servicio),
                       estado_original=?, estado=?, fuente=?, cargada_en=? WHERE cita_id=?""",
                    (vals[3], vals[4], vals[5], vals[6], vals[7], vals[8], vals[9], vals[10], fuente, ahora, c.cita_id),
                )
                con.execute(
                    "INSERT INTO citas_historial(cita_id,estado_anterior,estado_nuevo,cambiado_en) VALUES(?,?,?,?)",
                    (c.cita_id, anterior, c.estado, ahora),
                )
                res["actualizadas"] += 1
            else:
                res["sin_cambio"] += 1
    return res


def cargar_si_hace_falta(
    db_path: Path | str | None = None,
    estados: Path = ESTADOS_XLSX,
    horas: Path = HORAS_XLSX,
) -> str | None:
    """Carga los Excel a la base si cambiaron o si faltan datos básicos del paciente.

    Devuelve un mensaje si cargó, o None si la base ya está al día.
    Lanza FileNotFoundError si no hay base ni archivo de agenda.
    """
    destino = Path(db_path) if db_path else DB_PATH
    if not estados.exists():
        if destino.exists():
            return None
        raise FileNotFoundError(
            f"No hay base de datos ni el archivo «{estados.name}» en la carpeta «documentos iniciales»."
        )

    fuentes = [p for p in (estados, horas) if p.exists()]
    ultima_fuente = max(p.stat().st_mtime for p in fuentes)

    con = connect(destino)
    init_db(con)
    forzar = falta_datos_basicos(con)
    if destino.exists() and destino.stat().st_mtime >= ultima_fuente and not forzar:
        con.close()
        return None

    citas, pac = preparar(estados, horas if horas.exists() else None, _salt())
    res = cargar(con, citas, pac, fuente=estados.name)
    con.close()
    return (
        f"Agenda actualizada desde los Excel: {len(citas)} citas, {len(pac)} pacientes, "
        f"{res['nuevas']} nuevas, {res['actualizadas']} con cambio de estado."
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--estados", type=Path, default=ESTADOS_XLSX)
    ap.add_argument("--horas", type=Path, default=HORAS_XLSX)
    ap.add_argument("--db", type=Path, default=None)
    args = ap.parse_args()

    con = connect(args.db)
    init_db(con)
    citas, pac = preparar(args.estados, args.horas, _salt())
    res = cargar(con, citas, pac, fuente=args.estados.name)
    print(f"Pacientes: {len(pac)} | Citas leídas: {len(citas)} | {res}")


if __name__ == "__main__":
    main()
