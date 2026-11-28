"""Línea base histórica (antes del piloto).

Uso:
    python -m src.baseline                      # todo el histórico
    python -m src.baseline --hasta 2026-11-10   # excluir el periodo del piloto
Genera data/linea_base.json y la imprime.

Definiciones (se congelan antes de la Prueba 2):
- Denominador: citas excluyendo 'cambio_fecha' (ese cupo se movió a otra cita, no es una cita nueva).
- Tasa de no asistencia  = no_asiste / denominador
- Tasa de cancelación    = (anulado + anulado_paciente) / denominador
- % reagendado           = eventos (cancelación o no asistencia) con otra cita del mismo paciente
                           en estado atendido/agendada entre la fecha del evento y +15 días,
                           sobre eventos con 15 días ya transcurridos (los recientes se excluyen).
                           (confirmada no cuenta: pendiente de depuración según la clínica.)
- Huecos ocupados        = citas liberadas (anulado, anulado_paciente, no_asiste, cambio_fecha) cuyo
                           cupo (misma fecha y sillón, horas solapadas) fue tomado por otra cita válida.
                           Solo medible en las fechas que traen hora.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, timedelta

import pandas as pd

from .db import ROOT, connect

PERDIDA = {"anulado", "anulado_paciente", "no_asiste"}
LIBERA_CUPO = PERDIDA | {"cambio_fecha"}
VALIDAS = {"atendido", "agendada"}
VENTANA_DIAS = 15


def _citas(con, hasta: str | None) -> pd.DataFrame:
    df = pd.read_sql_query("SELECT * FROM citas", con)
    df["fecha"] = pd.to_datetime(df["fecha"])
    if hasta:
        df = df[df["fecha"] <= pd.Timestamp(hasta)]
    return df


def tasas(df: pd.DataFrame) -> dict:
    den = df[df["estado"] != "cambio_fecha"]
    n = len(den)
    return {
        "citas_denominador": n,
        "no_asiste": int((den["estado"] == "no_asiste").sum()),
        "cancelaciones": int(den["estado"].isin({"anulado", "anulado_paciente"}).sum()),
        "tasa_no_asistencia": round((den["estado"] == "no_asiste").sum() / n, 4) if n else None,
        "tasa_cancelacion": round(den["estado"].isin({"anulado", "anulado_paciente"}).sum() / n, 4) if n else None,
    }


def reagendados(df: pd.DataFrame, corte: pd.Timestamp) -> dict:
    """Eventos con ventana cerrada (fecha + 15 d <= corte) y si hubo otra cita válida en la ventana."""
    eventos = df[df["estado"].isin(PERDIDA) & (df["fecha"] + pd.Timedelta(days=VENTANA_DIAS) <= corte)]
    validas = df[df["estado"].isin(VALIDAS)][["cita_id", "paciente_id", "fecha"]]
    por_pac = {p: g for p, g in validas.groupby("paciente_id")}
    ok = 0
    for e in eventos.itertuples():
        g = por_pac.get(e.paciente_id)
        if g is None:
            continue
        fin = e.fecha + pd.Timedelta(days=VENTANA_DIAS)
        if ((g["cita_id"] != e.cita_id) & (g["fecha"] >= e.fecha) & (g["fecha"] <= fin)).any():
            ok += 1
    n = len(eventos)
    return {
        "eventos_con_ventana_cerrada": n,
        "reagendados_en_15d": ok,
        "pct_reagendado": round(ok / n, 4) if n else None,
        "eventos_excluidos_por_ventana_abierta": int(df["estado"].isin(PERDIDA).sum() - n),
    }


def huecos(df: pd.DataFrame) -> dict:
    h = df[df["hora_inicio"].notna() & df["sillon"].notna()]
    liberadas = h[h["estado"].isin(LIBERA_CUPO)]
    validas = h[h["estado"].isin(VALIDAS)]
    ocupados = 0
    for c in liberadas.itertuples():
        otras = validas[(validas["fecha"] == c.fecha) & (validas["sillon"] == c.sillon)
                        & (validas["cita_id"] != c.cita_id)]
        if ((otras["hora_inicio"] < c.hora_fin) & (otras["hora_fin"] > c.hora_inicio)).any():
            ocupados += 1
    n = len(liberadas)
    return {
        "periodo_con_horas": [h["fecha"].min().date().isoformat(), h["fecha"].max().date().isoformat()] if len(h) else None,
        "cupos_liberados": n,
        "cupos_reocupados": ocupados,
        "pct_ocupado": round(ocupados / n, 4) if n else None,
    }


def calcular(con, hasta: str | None = None) -> dict:
    df = _citas(con, hasta)
    corte = df["fecha"].max()
    por_mes = {
        str(m): tasas(g) for m, g in df.groupby(df["fecha"].dt.to_period("M"))
    }
    return {
        "generada_el": date.today().isoformat(),
        "rango": [df["fecha"].min().date().isoformat(), corte.date().isoformat()],
        "total": tasas(df),
        "por_mes": por_mes,
        "reagendado": reagendados(df, corte),
        "huecos": huecos(df),
        "inactivos_recuperados": "no medible: el histórico cubre menos de 90 días antes del primer evento",
        "motivo_cancelacion": "no existe en el histórico: se registra desde la app",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hasta", help="Última fecha a incluir (excluye el piloto)")
    ap.add_argument("--db", default=None)
    args = ap.parse_args()
    con = connect(args.db)
    res = calcular(con, args.hasta)
    salida = ROOT / "data" / "linea_base.json"
    salida.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
