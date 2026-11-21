"""Pantalla para la auxiliar. Ejecutar desde la carpeta del proyecto:

    streamlit run app.py

Lee data/blissens.db (se crea con: python -m src.load). No envía mensajes: solo prepara el borrador.
"""
from __future__ import annotations

import re
import sqlite3
from urllib.parse import quote

import pandas as pd
import streamlit as st

from src import db, load, messages, rules
from src.chatbot import responder


def _digitos_celular(valor: str | None) -> str:
    return re.sub(r"\D", "", valor or "")


def _celular_paciente(fila: pd.Series) -> str:
    """Celular del paciente en la base, o vacío si no hay (la auxiliar lo escribe a mano)."""
    raw = fila.get("celular")
    if raw is None or (isinstance(raw, float) and pd.isna(raw)) or pd.isna(raw):
        return ""
    texto = str(raw).strip()
    if texto.endswith(".0"):
        texto = texto[:-2]
    return _digitos_celular(texto) or texto

st.set_page_config(page_title="Recuperación de pacientes · Blissens", layout="wide")

try:
    aviso_carga = load.cargar_si_hace_falta()
except FileNotFoundError as e:
    st.error(str(e))
    st.stop()
except Exception as e:  # Excel con otro formato, archivo abierto en Excel, etc.
    st.error(f"No se pudo cargar la agenda desde los Excel: {e}")
    st.stop()

if aviso_carga:
    st.toast(aviso_carga, icon="✅")

con = db.connect()
db.init_db(con)

fmin, fmax = rules.rango_fechas(con)
st.sidebar.header("Fecha de trabajo")
R = st.sidebar.date_input(
    "Fecha de referencia",
    value=fmax,
    min_value=fmin,
    max_value=fmax,
    help="La app muestra lo que se sabía ese día. Por defecto, la última fecha con datos.",
)
R = pd.Timestamp(R)
st.sidebar.caption(
    "Los datos llegan hasta la última fecha del export. "
    "Los huecos solo se calculan en fechas con horario (octubre)."
)

rules.sincronizar(con, R)
res = rules.calcular(con, R)

st.title("Recuperación de pacientes")
st.caption(f"Fecha de referencia: {R:%d/%m/%Y}. Incluye nombre y datos de contacto del paciente.")

tab_panel, tab_cola, tab_chat = st.tabs(["Panel del día", "Cola de recuperación", "Chat IA"])

# ---------- Panel del día ----------
with tab_panel:
    k = res["kpis"]
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Citas del día", k["citas"])
    c2.metric("Atendidas", k["atendidas"])
    c3.metric("No asistieron", k["no_asiste"])
    c4.metric("Cancelaciones", k["cancelaciones"])
    c5.metric("Huecos libres", k["huecos_libres"])
    c6.metric(
        "Ocupación",
        f"{k['ocupacion']:.0%}" if k["ocupacion"] is not None else "—",
        help="Citas que se mantienen (atendidas, confirmadas o agendadas) sobre citas, sin contar cambios de fecha.",
    )

    st.subheader("En cola de recuperación")
    a, b, cc = st.columns(3)
    a.metric("Pacientes en protocolo", len(res["cola"]))
    b.metric("Recuperados (cita válida en 15 días)", res["recuperados"])
    cc.metric("Fuera de protocolo (más de 15 días)", res["fuera_protocolo"])

    st.subheader("Huecos del día")
    if res["sin_horario"]:
        st.info("Esta fecha no trae horas en el export, así que no hay huecos que calcular.")
    elif res["huecos"].empty:
        st.success("No hubo citas canceladas, no asistidas ni movidas con horario en este día.")
    else:
        st.dataframe(res["huecos"], hide_index=True, width="stretch", alt="Huecos del día con candidato sugerido")
        st.caption("Candidato: primer paciente de la cola (sin contar al del hueco) con la alerta más urgente.")

# ---------- Cola de recuperación ----------
with tab_cola:
    cola = res["cola"]
    grupo_sel = st.radio("Grupo", ["Todos"] + rules.GRUPOS, horizontal=True)
    vista = cola if grupo_sel == "Todos" else cola[cola["grupo"] == grupo_sel]

    if vista.empty:
        st.info("No hay pacientes en este grupo para la fecha de referencia.")
    else:
        vista = vista.copy()
        vista["paciente"] = [rules.etiqueta_paciente(r) for _, r in vista.iterrows()]
        columnas = {
            "grupo": "Grupo",
            "paciente": "Paciente",
            "celular": "Celular",
            "email": "Email",
            "tipo": "Evento",
            "fecha_evento": "Fecha evento",
            "dias": "Días",
            "alerta": "Alerta",
            "intentos": "Intentos",
            "antiguedad": "Antigüedad",
        }
        tabla = vista[list(columnas)].rename(columns=columnas).copy()
        tabla["Fecha evento"] = pd.to_datetime(tabla["Fecha evento"]).dt.strftime("%d/%m/%Y")
        st.dataframe(tabla, hide_index=True, width="stretch", alt="Cola de recuperación con datos del paciente")

        etiquetas = {
            r.evento_id: f"{r.paciente} · {r.tipo} · {r.alerta} · {r.dias} días"
            for r in vista.itertuples()
        }
        evento_id = st.selectbox("Paciente a contactar", list(etiquetas), format_func=lambda i: etiquetas[i])
        fila = vista[vista["evento_id"] == evento_id].iloc[0]
        es_cancelacion = fila["tipo"] == "cancelacion"
        sin_motivo = es_cancelacion and not fila["motivo"]

        izq, der = st.columns([1, 1])
        with izq:
            st.markdown(f"**Paciente:** {fila['paciente']}")
            if pd.notna(fila.get("id_software")):
                st.markdown(f"**ID software:** {int(fila['id_software'])}")
            contacto = []
            if pd.notna(fila.get("celular")):
                contacto.append(f"Celular: {fila['celular']}")
            if pd.notna(fila.get("telefono")):
                contacto.append(f"Teléfono: {fila['telefono']}")
            if pd.notna(fila.get("email")):
                contacto.append(f"Email: {fila['email']}")
            if contacto:
                st.markdown(" · ".join(contacto))
            st.markdown(f"**Grupo:** {fila['grupo']}")
            st.markdown(f"**Evento:** {fila['tipo']} el {pd.Timestamp(fila['fecha_evento']):%d/%m/%Y}")
            st.markdown(f"**Alerta:** {fila['alerta']} · **Días desde el evento:** {fila['dias']}")
            if es_cancelacion:
                st.markdown(f"**Motivo de cancelación:** {fila['motivo'] or '_sin registrar_'}")

            hist = rules.intentos(con, int(evento_id))
            if not hist.empty:
                st.markdown("**Intentos registrados**")
                hist["resultado"] = hist["resultado"].map(rules.RESULTADOS)
                st.dataframe(hist, hide_index=True, width="stretch", alt="Historial de intentos de contacto")

            if sin_motivo:
                st.warning("Esta cancelación no tiene motivo. Es obligatorio antes de registrar un intento.")

            pendiente = fila["pendiente"]
            opciones_dia = list(rules.PASOS)
            indice = opciones_dia.index(int(pendiente)) if pd.notna(pendiente) else len(opciones_dia) - 1

            with st.form("registrar_intento", clear_on_submit=True):
                st.markdown("**Registrar intento**")
                dia = st.selectbox("Día de protocolo", opciones_dia, index=indice)
                resultado = st.selectbox(
                    "Resultado", list(rules.RESULTADOS), format_func=lambda x: rules.RESULTADOS[x]
                )
                motivo = None
                if sin_motivo:
                    motivo = st.selectbox("Motivo de cancelación (obligatorio)", [""] + rules.MOTIVOS)
                nota = st.text_input("Nota")
                guardar = st.form_submit_button("Guardar intento")

            if guardar:
                try:
                    rules.registrar_intento(
                        con, int(evento_id), int(dia), resultado, nota, R.date(), motivo or None
                    )
                    st.success("Intento guardado.")
                    st.rerun()
                except (ValueError, sqlite3.IntegrityError) as e:
                    st.error(str(e))

            with st.expander("Cerrar sin recuperar"):
                motivo_cierre = None
                if sin_motivo:
                    motivo_cierre = st.selectbox("Motivo de cancelación", [""] + rules.MOTIVOS, key="cierre_motivo")
                if st.button("Cerrar este caso como sin recuperar"):
                    try:
                        rules.cerrar_sin_recuperar(con, int(evento_id), motivo_cierre or None)
                        st.success("Caso cerrado.")
                        st.rerun()
                    except (ValueError, sqlite3.IntegrityError) as e:
                        st.error(str(e))

        with der:
            st.markdown("**Mensaje de WhatsApp**")
            plantilla, texto = messages.mensaje(
                fila["grupo"],
                fila["servicio"] if pd.notna(fila["servicio"]) else None,
                fila["motivo"] if pd.notna(fila["motivo"]) else None,
                fila["nombre"] if pd.notna(fila.get("nombre")) else None,
                fila["apellidos"] if pd.notna(fila.get("apellidos")) else None,
            )
            st.caption(f"Plantilla: {plantilla}. Revise el número y abra WhatsApp para enviar.")
            st.code(texto, language=None)

            cel_paciente = _celular_paciente(fila)
            wa_key = f"wa_cel_{int(evento_id)}"
            if wa_key not in st.session_state:
                st.session_state[wa_key] = cel_paciente

            if cel_paciente:
                st.caption(f"Celular del paciente en la base: {cel_paciente}")
            else:
                st.caption("Este paciente no tiene celular en la base. Escríbalo manualmente.")

            numero = st.text_input(
                "Número de celular",
                key=wa_key,
                placeholder="Ej. 573001234567",
                help="Si está en la base se carga solo. Si no, escríbalo a mano (código 57 + número).",
            )
            digitos = _digitos_celular(numero)
            listo = len(digitos) >= 10
            url_wa = f"https://wa.me/{digitos}?text={quote(texto)}" if listo else ""
            st.link_button(
                "Abrir WhatsApp",
                url_wa or "https://wa.me/",
                type="primary",
                icon=":material/chat:",
                width="stretch",
                disabled=not listo,
                help="Abre WhatsApp Web o la app con el mensaje listo para enviar.",
            )
            if not listo:
                st.caption("Ingrese un número válido (mínimo 10 dígitos) para habilitar el botón.")


with tab_chat:

    st.subheader("Asistente IA")

    st.caption(
        "Consulta agenda, huecos, recuperación y seguimiento."
    )

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    # Historial con altura fija y scroll
    chat_container = st.container(height=400)

    with chat_container:
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    # Input siempre en la parte inferior
    pregunta = st.chat_input(
        "Haz una pregunta..."
    )

    if pregunta:

        # Mostrar inmediatamente el mensaje del usuario
        st.session_state.chat_history.append({
            "role": "user",
            "content": pregunta
        })

        with chat_container:
            for msg in st.session_state.chat_history:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

            with st.chat_message("assistant"):
                with st.spinner("Consultando información..."):

                    respuesta = responder(
                        con,
                        pregunta,
                        st.session_state.chat_history
                    )

        st.session_state.chat_history.append({
            "role": "assistant",
            "content": respuesta
        })

        st.rerun()
        
con.close()
