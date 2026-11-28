"""Reglas de la app: huecos, cola de recuperación, alertas día 3/7/15 y registro de intentos.

Todo se calcula a una fecha de referencia R. Solo se usan citas con fecha <= R, así la app
muestra lo que la auxiliar podía ver ese día (sirve también para repetir la Prueba 1).

Grupos de la cola
- 1. Tratamiento interrumpido: cancelación, no asistencia o diagnóstico sin continuidad de un paciente antiguo.
- 2. Paciente nuevo que no volvió: lo mismo, pero para pacientes con antigüedad Nuevo.
- 3. Inactivo más de 3 meses: última cita válida hace más de 90 días.

Protocolo: el evento arranca en fecha_evento. Alertas en el día 3, 7 y 15. Si un paciente
tiene una cita válida dentro de los 15 días siguientes, sale de la cola como recuperado.
Pasados 15 días sin recuperación, sale de la cola ("fuera de protocolo") hasta que se cierre.
"""
from __future__ import annotations

import sqlite3
from datetime import date

import pandas as pd

PASOS = (3, 7, 15)
VENTANA = 15
DIAS_INACTIVO = 90
RESULTADOS = {
    "sin_respuesta": "Sin respuesta",
    "reagendo": "Reagendó",
    "rechazo": "Rechazó",
    "otro": "Otro",
}
MOTIVOS = [
    "Motivo de salud",
    "Viaje o trabajo",
    "Problema económico",
    "No quiere continuar",
    "No se pudo contactar",
    "Otro",
]

CANCELACION = {"anulado", "anulado_paciente"}
PERDIDA = CANCELACION | {"no_asiste"}
LIBERA_CUPO = PERDIDA | {"cambio_fecha"}
VALIDAS = {"atendido", "confirmada", "agendada"}

GRUPO_TRAT = "1. Tratamiento interrumpido"
GRUPO_NUEVO = "2. Paciente nuevo que no volvió"
GRUPO_INACT = "3. Inactivo más de 3 meses"
GRUPOS = [GRUPO_TRAT, GRUPO_NUEVO, GRUPO_INACT]
ORDEN_ANTIG = {"Antiguo": 0, "Desconocida": 1, "Nuevo": 2}


def rango_fechas(con: sqlite3.Connection) -> tuple[date, date]:
    mn, mx = con.execute("SELECT MIN(fecha), MAX(fecha) FROM citas").fetchone()
    return pd.Timestamp(mn).date(), pd.Timestamp(mx).date()


def _citas(con: sqlite3.Connection, R: pd.Timestamp) -> pd.DataFrame:
    df = pd.read_sql_query(
        """SELECT c.cita_id, c.paciente_id, c.fecha, c.hora_inicio, c.hora_fin, c.sillon,
                  c.tipo_cita, c.servicio, c.estado, p.antiguedad,
                  p.nombre, p.apellidos, p.celular, p.telefono, p.email, p.id_software
           FROM citas c JOIN pacientes p ON p.paciente_id = c.paciente_id""",
        con,
    )
    df["fecha"] = pd.to_datetime(df["fecha"])
    return df[df["fecha"] <= R].reset_index(drop=True)


def _eventos(c: pd.DataFrame, R: pd.Timestamp) -> pd.DataFrame:
    """Eventos candidatos según la historia visible hasta R (sin filtrar por recuperación)."""
    valid = c[c["estado"].isin(VALIDAS)]
    partes = []

    # Cancelaciones y no asistencias
    perd = c[c["estado"].isin(PERDIDA)].copy()
    perd["tipo"] = ["cancelacion" if e in CANCELACION else "no_asistencia" for e in perd["estado"]]
    perd["fecha_evento"] = perd["fecha"]
    partes.append(perd)

    # Último diagnóstico atendido sin cita válida posterior
    diag = c[(c["estado"] == "atendido") & (c["tipo_cita"] == "Diagnóstico")].sort_values("fecha")
    ult = diag.groupby("paciente_id").tail(1).copy()
    lv = valid.groupby("paciente_id")["fecha"].max()
    ult_lv = ult["paciente_id"].map(lv)
    ult = ult[ult_lv.isna() | (ult_lv <= ult["fecha"])].copy()
    ult["tipo"] = "diagnostico_sin_continuidad"
    ult["fecha_evento"] = ult["fecha"]
    partes.append(ult)

    # Inactivos: última cita válida hace más de 90 días; el evento arranca al cumplirse ese plazo
    ultima = valid.sort_values("fecha").groupby("paciente_id").tail(1)
    ultima = ultima[ultima["fecha"] <= R - pd.Timedelta(days=DIAS_INACTIVO)].copy()
    ultima["tipo"] = "inactivo"
    ultima["fecha_evento"] = ultima["fecha"] + pd.Timedelta(days=DIAS_INACTIVO)
    partes.append(ultima)

    cols = [
        "cita_id",
        "paciente_id",
        "tipo",
        "fecha_evento",
        "servicio",
        "antiguedad",
        "nombre",
        "apellidos",
        "celular",
        "telefono",
        "email",
        "id_software",
    ]
    ev = pd.concat([p[cols] for p in partes], ignore_index=True)
    ev["dias"] = (R - ev["fecha_evento"]).dt.days
    return ev[ev["dias"] >= 0].reset_index(drop=True)


def _recuperados(ev: pd.DataFrame, valid: pd.DataFrame) -> pd.Series:
    """True si el paciente tiene otra cita válida dentro de la ventana de 15 días."""
    if ev.empty:
        return pd.Series(dtype=bool)
    base = ev[["cita_id", "paciente_id", "fecha_evento"]].reset_index().rename(columns={"index": "k"})
    m = base.merge(valid[["cita_id", "paciente_id", "fecha"]], on="paciente_id", suffixes=("", "_v"))
    m = m[
        (m["cita_id_v"] != m["cita_id"])
        & (m["fecha"] > m["fecha_evento"])
        & (m["fecha"] <= m["fecha_evento"] + pd.Timedelta(days=VENTANA))
    ]
    return ev.index.isin(set(m["k"]))


def _grupo(tipo: str, antiguedad: str) -> str:
    if tipo == "inactivo":
        return GRUPO_INACT
    if antiguedad == "Nuevo":
        return GRUPO_NUEVO
    return GRUPO_TRAT


def _pendiente(dias: int, hechos: set) -> int | None:
    """Paso más reciente ya vencido que todavía no tiene intento.

    Un intento en el día 7 cubre también el día 3: no queda pendiente.
    """
    vencidos = [s for s in PASOS if s <= dias]
    if not vencidos:
        return None
    ultimo = max(vencidos)
    return ultimo if ultimo > max(hechos, default=0) else None


def sincronizar(con: sqlite3.Connection, R) -> None:
    """Registra en eventos_perdida los eventos abiertos a la fecha R. Idempotente."""
    R = pd.Timestamp(R)
    c = _citas(con, R)
    ev = _eventos(c, R)
    valid = c[c["estado"].isin(VALIDAS)]
    ev = ev[~_recuperados(ev, valid)]
    with con:
        con.executemany(
            "INSERT OR IGNORE INTO eventos_perdida (cita_id, paciente_id, tipo, fecha_evento) VALUES (?,?,?,?)",
            [
                (int(r.cita_id), r.paciente_id, r.tipo, r.fecha_evento.date().isoformat())
                for r in ev.itertuples()
            ],
        )


def _campo(row, key: str):
    if isinstance(row, pd.Series):
        return row.get(key)
    return getattr(row, key, None)


def etiqueta_paciente(row) -> str:
    partes = []
    for key in ("nombre", "apellidos"):
        v = _campo(row, key)
        if pd.notna(v) and str(v).strip():
            partes.append(str(v).strip())
    if partes:
        return " ".join(partes)
    return str(_campo(row, "paciente_id") or "")


def _huecos(c: pd.DataFrame, R: pd.Timestamp, cola: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    cols = ["hora", "sillon", "estado", "paciente", "ocupado", "candidato"]
    dia = c[c["fecha"] == R]
    h = dia[dia["hora_inicio"].notna() & dia["hora_fin"].notna() & dia["sillon"].notna()]
    sin_horario = h.empty
    liberadas = h[h["estado"].isin(LIBERA_CUPO)]
    validas = h[h["estado"].isin(VALIDAS)]

    filas = []
    for r in liberadas.itertuples():
        otras = validas[
            (validas["sillon"] == r.sillon)
            & (validas["cita_id"] != r.cita_id)
            & (validas["hora_inicio"] < r.hora_fin)
            & (validas["hora_fin"] > r.hora_inicio)
        ]
        ocupado = not otras.empty
        candidato = ""
        if not ocupado:
            cand = cola[cola["paciente_id"] != r.paciente_id].head(1)
            if not cand.empty:
                candidato = f"{etiqueta_paciente(cand.iloc[0])} · {cand.iloc[0]['alerta']}"
        filas.append(
            {
                "hora": f"{r.hora_inicio}–{r.hora_fin}",
                "sillon": r.sillon,
                "estado": r.estado,
                "paciente": etiqueta_paciente(r),
                "ocupado": "Sí" if ocupado else "No",
                "candidato": candidato,
            }
        )
    return pd.DataFrame(filas, columns=cols), sin_horario


def calcular(con: sqlite3.Connection, R) -> dict:
    """Panel del día y cola para la fecha R. Llamar después de sincronizar()."""
    R = pd.Timestamp(R)
    c = _citas(con, R)
    ev = _eventos(c, R)
    valid = c[c["estado"].isin(VALIDAS)]
    ev["recuperado"] = _recuperados(ev, valid)
    recuperados = int(ev["recuperado"].sum())

    estado = pd.read_sql_query(
        """SELECT e.evento_id, e.cita_id, e.tipo, e.motivo_cancelacion AS motivo, e.estado_cola,
                  (SELECT COUNT(*) FROM intentos_contacto i WHERE i.evento_id = e.evento_id) AS intentos
           FROM eventos_perdida e""",
        con,
    )
    hechos_df = pd.read_sql_query("SELECT evento_id, dia_protocolo FROM intentos_contacto", con)
    hechos = hechos_df.groupby("evento_id")["dia_protocolo"].apply(set).to_dict()

    ev = ev.merge(estado, on=["cita_id", "tipo"], how="inner")
    ev = ev[~ev["recuperado"] & (ev["estado_cola"] == "abierto")]
    fuera = int((ev["dias"] > VENTANA).sum())
    cola = ev[ev["dias"] <= VENTANA].copy()

    cola["grupo"] = [_grupo(t, a) for t, a in zip(cola["tipo"], cola["antiguedad"])]
    cola["hechos"] = cola["evento_id"].map(lambda i: hechos.get(i, set()))
    cola["pendiente"] = [_pendiente(d, h) for d, h in zip(cola["dias"], cola["hechos"])]
    cola["alerta"] = [
        f"Día {int(p)}" if pd.notna(p) else ("Al día" if d >= PASOS[0] else f"En espera (día {int(d)})")
        for p, d in zip(cola["pendiente"], cola["dias"])
    ]
    cola["_p"] = cola["pendiente"].fillna(0)
    cola["_o"] = cola["antiguedad"].map(ORDEN_ANTIG).fillna(1)
    cola = cola.sort_values(["_p", "_o", "dias"], ascending=[False, True, False]).drop(columns=["_p", "_o"])
    cola = cola.reset_index(drop=True)

    huecos, sin_horario = _huecos(c, R, cola)

    dia = c[c["fecha"] == R]
    n = dia["estado"].value_counts()
    total = len(dia)
    cambio = int(n.get("cambio_fecha", 0))
    base = total - cambio
    en_pie = int(sum(n.get(e, 0) for e in ("atendido", "confirmada", "agendada")))
    kpis = {
        "citas": total,
        "atendidas": int(n.get("atendido", 0)),
        "confirmadas": int(n.get("confirmada", 0)),
        "agendadas": int(n.get("agendada", 0)),
        "no_asiste": int(n.get("no_asiste", 0)),
        "cancelaciones": int(sum(n.get(e, 0) for e in CANCELACION)),
        "cambio_fecha": cambio,
        "ocupacion": round(en_pie / base, 3) if base > 0 else None,
        "ocupacion_num": en_pie,
        "ocupacion_den": base,
        "huecos_libres": int((huecos["ocupado"] == "No").sum()) if not huecos.empty else 0,
        "huecos_reocupados": int((huecos["ocupado"] == "Sí").sum()) if not huecos.empty else 0,
    }

    conf = dia[dia["estado"] == "confirmada"].copy()
    if conf.empty:
        confirmadas_dia = pd.DataFrame(columns=["hora", "sillon", "paciente", "id_software"])
    else:
        conf = conf.sort_values(["hora_inicio", "sillon"], na_position="last")
        confirmadas_dia = pd.DataFrame(
            {
                "hora": [
                    f"{hi}–{hf}" if pd.notna(hi) and pd.notna(hf) else "—"
                    for hi, hf in zip(conf["hora_inicio"], conf["hora_fin"])
                ],
                "sillon": conf["sillon"].fillna("—").astype(str),
                "paciente": [etiqueta_paciente(r) for _, r in conf.iterrows()],
                "id_software": conf["id_software"],
            }
        ).reset_index(drop=True)

    return {
        "kpis": kpis,
        "huecos": huecos,
        "sin_horario": sin_horario,
        "cola": cola,
        "recuperados": recuperados,
        "fuera_protocolo": fuera,
        "confirmadas_dia": confirmadas_dia,
    }


def intentos(con: sqlite3.Connection, evento_id: int) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT fecha, dia_protocolo AS dia, resultado, nota FROM intentos_contacto WHERE evento_id = ? ORDER BY fecha",
        con,
        params=(evento_id,),
    )


def _evento(con: sqlite3.Connection, evento_id: int) -> sqlite3.Row:
    row = con.execute(
        "SELECT tipo, motivo_cancelacion FROM eventos_perdida WHERE evento_id = ?", (evento_id,)
    ).fetchone()
    if row is None:
        raise ValueError("Evento no encontrado.")
    return row


def _motivo_obligatorio(row: sqlite3.Row, motivo: str | None) -> None:
    if row["tipo"] == "cancelacion" and not (motivo or row["motivo_cancelacion"]):
        raise ValueError("Falta el motivo de cancelación. Selecciónelo antes de guardar.")


def _guardar_motivo(con: sqlite3.Connection, evento_id: int, row: sqlite3.Row, motivo: str | None) -> None:
    if row["tipo"] == "cancelacion" and motivo and not row["motivo_cancelacion"]:
        con.execute("UPDATE eventos_perdida SET motivo_cancelacion = ? WHERE evento_id = ?", (motivo, evento_id))


def registrar_intento(
    con: sqlite3.Connection,
    evento_id: int,
    dia: int,
    resultado: str,
    nota: str | None,
    fecha: date,
    motivo: str | None = None,
) -> None:
    if dia not in PASOS:
        raise ValueError("El día de protocolo debe ser 3, 7 o 15.")
    if resultado not in RESULTADOS:
        raise ValueError("Resultado no válido.")
    row = _evento(con, evento_id)
    _motivo_obligatorio(row, motivo)
    with con:
        _guardar_motivo(con, evento_id, row, motivo)
        con.execute(
            "INSERT INTO intentos_contacto (evento_id, fecha, dia_protocolo, canal, resultado, nota) "
            "VALUES (?,?,?,?,?,?)",
            (evento_id, fecha.isoformat(), dia, "whatsapp", resultado, (nota or "").strip() or None),
        )
        if resultado == "reagendo":
            con.execute("UPDATE eventos_perdida SET estado_cola = 'recuperado' WHERE evento_id = ?", (evento_id,))


def cerrar_sin_recuperar(con: sqlite3.Connection, evento_id: int, motivo: str | None = None) -> None:
    row = _evento(con, evento_id)
    _motivo_obligatorio(row, motivo)
    with con:
        _guardar_motivo(con, evento_id, row, motivo)
        con.execute("UPDATE eventos_perdida SET estado_cola = 'sin_recuperar' WHERE evento_id = ?", (evento_id,))
