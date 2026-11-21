from datetime import date
import json
import pandas as pd
from ollama import chat

from .rules import calcular

# -------------------------
# HERRAMIENTAS
# -------------------------

def obtener_kpis(con):

    info = calcular(con, date.today())

    return info["kpis"]


def obtener_cola(con):

    info = calcular(con, date.today())

    cola = info["cola"]

    if cola.empty:
        return []

    cols = [
        "grupo",
        "nombre",
        "apellidos",
        "celular",
        "tipo",
        "dias",
        "alerta",
    ]

    fragmento = cola[cols].head(50).copy()
    return fragmento.astype(object).where(pd.notnull(fragmento), None).to_dict(orient="records")


def obtener_huecos(con):

    info = calcular(con, date.today())

    df = info["huecos"]

    if df.empty:
        return []

    return df.to_dict(
        orient="records"
    )


def obtener_resumen(con):

    info = calcular(con, date.today())

    return {
        "kpis": info["kpis"],
        "recuperados": info["recuperados"],
        "fuera_protocolo": info["fuera_protocolo"],
        "cola": obtener_cola(con)[:15],
        "huecos": obtener_huecos(con)[:15]
    }


# -------------------------
# CHAT
# -------------------------

SYSTEM_PROMPT = """
Eres un asistente para la clínica Blissens.

Reglas:

1. Responde únicamente usando los datos suministrados.
2. No inventes información.
3. Si el dato no existe indica:
   'No cuento con información suficiente'.
4. Explica los indicadores en lenguaje sencillo.
5. Responde siempre en español.
"""


def responder(
    con,
    pregunta,
    historial=None
):

    contexto = obtener_resumen(con)

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }
    ]

    if historial:

        for item in historial[-10:]:

            messages.append(
                {
                    "role": item["role"],
                    "content": item["content"]
                }
            )

    messages.append(
        {
            "role": "user",
            "content":
            f"""
Datos disponibles:

{json.dumps(contexto, indent=2, ensure_ascii=False)}

Pregunta:

{pregunta}
"""
        }
    )

    response = chat(
        model="llama3.2:latest",
        messages=messages
    )

    return response["message"]["content"]