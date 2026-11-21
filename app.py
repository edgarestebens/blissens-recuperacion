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


def _alerta_badge(alerta: str) -> str:
    if alerta.startswith("Día 15"):
        return "red"
    if alerta.startswith("Día 7"):
        return "orange"
    if alerta.startswith("Día 3"):
        return "blue"
    if alerta.startswith("Al día"):
        return "green"
    return "gray"


def _campo_txt(fila: pd.Series, key: str) -> str | None:
    v = fila.get(key)
    if v is None or (isinstance(v, float) and pd.isna(v)) or pd.isna(v):
        return None
    s = str(v).strip()
    return s or None


st.set_page_config(
    page_title="Recuperación de pacientes · Blissens",
    page_icon=":material/dentistry:",
    layout="wide",
    initial_sidebar_state="expanded",
)

try:
    aviso_carga = load.cargar_si_hace_falta()
except FileNotFoundError as e:
    st.error(str(e))
    st.stop()
except Exception as e:  # Excel con otro formato, archivo abierto en Excel, etc.
    st.error(f"No se pudo cargar la agenda desde los Excel: {e}")
    st.stop()

if aviso_carga:
    st.toast(aviso_carga, icon=":material/check_circle:")

con = db.connect()
db.init_db(con)

fmin, fmax = rules.rango_fechas(con)

with st.sidebar:
    st.markdown("### Blissens")
    st.caption("Recuperación de pacientes")
    st.divider()
    st.markdown("**Trabajo del día**")
    R = st.date_input(
        "Fecha de referencia",
        value=fmax,
        min_value=fmin,
        max_value=fmax,
        help="La app muestra lo que se sabía ese día. Por defecto, la última fecha con datos.",
    )
    R = pd.Timestamp(R)
    st.caption(
        "Los datos llegan hasta la última fecha del export. "
        "Los huecos solo se calculan en fechas con horario (octubre)."
    )

rules.sincronizar(con, R)
res = rules.calcular(con, R)
k = res["kpis"]
n_cola = len(res["cola"])

with st.sidebar:
    st.divider()
    st.markdown(f"**{n_cola}** en cola · **{k['huecos_libres']}** huecos libres")
    st.caption("Versión de prueba · uso en computador de la clínica")

# ---------- Cabecera ----------
h1, h2 = st.columns([3, 1], vertical_alignment="bottom")
with h1:
    st.title("Recuperación de pacientes")
    st.caption("Blissens Odontología · seguimiento día 3, 7 y 15 con datos de contacto")
with h2:
    st.markdown(f"**Fecha de referencia**  \n{R:%d/%m/%Y}")

st.divider()

tab_panel, tab_cola, tab_chat = st.tabs(
    [
        ":material/dashboard: Panel del día",
        ":material/format_list_bulleted: Cola de recuperación",
        ":material/smart_toy: Chat IA",
    ]
)

# ---------- Panel del día ----------
with tab_panel:
    with st.container(border=True):
        st.subheader("Agenda del día")
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Citas", k["citas"])
        c2.metric("Atendidas", k["atendidas"])
        c3.metric("No asistieron", k["no_asiste"])
        c4.metric("Cancelaciones", k["cancelaciones"])
        c5.metric("Huecos libres", k["huecos_libres"])
        c6.metric(
            "Ocupación",
            f"{k['ocupacion']:.0%}" if k["ocupacion"] is not None else "—",
            help="Citas que se mantienen (atendidas, confirmadas o agendadas) sobre citas, sin contar cambios de fecha.",
        )

    st.write("")
    with st.container(border=True):
        st.subheader("Recuperación")
        a, b, cc = st.columns(3)
        a.metric("En protocolo", n_cola)
        b.metric("Recuperados (15 días)", res["recuperados"])
        cc.metric("Fuera de protocolo", res["fuera_protocolo"])

    st.write("")
    st.subheader("Huecos del día")
    if res["sin_horario"]:
        st.info(
            "El archivo de agenda no tiene horario para este día.",
            icon=":material/schedule:",
            title="Sin horario en el export",
        )
    elif res["huecos"].empty:
        st.success(
            "No hubo citas canceladas, no asistidas ni movidas con horario en este día.",
            icon=":material/check_circle:",
            title="Sin huecos",
        )
    else:
        huecos = res["huecos"].copy()
        huecos["ocupado_badge"] = huecos["ocupado"].map(lambda x: [x])
        st.dataframe(
            huecos,
            hide_index=True,
            width="stretch",
            alt="Huecos del día con candidato sugerido",
            column_order=["hora", "sillon", "estado", "paciente", "ocupado_badge", "candidato"],
            column_config={
                "hora": "Hora",
                "sillon": "Sillón",
                "estado": "Estado",
                "paciente": "Paciente",
                "ocupado_badge": st.column_config.MultiselectColumn(
                    "Ocupado",
                    options=["Sí", "No"],
                    color=["red", "green"],
                    disabled=True,
                ),
                "candidato": "Candidato",
                "ocupado": None,
            },
        )
        st.caption("Candidato: primer paciente de la cola (sin contar al del hueco) con la alerta más urgente.")

# ---------- Cola de recuperación ----------
with tab_cola:
    cola = res["cola"]
    opciones_grupo = ["Todos"] + rules.GRUPOS
    grupo_sel = st.segmented_control(
        "Grupo",
        opciones_grupo,
        default="Todos",
        key="filtro_grupo",
    )
    if grupo_sel is None:
        grupo_sel = "Todos"
    vista = cola if grupo_sel == "Todos" else cola[cola["grupo"] == grupo_sel]

    if vista.empty:
        st.info(
            "No hay pacientes en este grupo para la fecha de referencia.",
            icon=":material/inbox:",
            title="Cola vacía",
        )
    else:
        vista = vista.copy()
        vista["paciente"] = [rules.etiqueta_paciente(r) for _, r in vista.iterrows()]
        vista["alerta_badge"] = vista["alerta"].map(lambda a: [a])

        alerta_opts = sorted({a for a in vista["alerta"].dropna().astype(str)})
        alerta_colors = [_alerta_badge(a) for a in alerta_opts]

        tabla = vista[
            ["grupo", "paciente", "celular", "email", "tipo", "fecha_evento", "dias", "alerta_badge", "intentos", "antiguedad"]
        ].copy()
        tabla["fecha_evento"] = pd.to_datetime(tabla["fecha_evento"]).dt.strftime("%d/%m/%Y")

        st.dataframe(
            tabla,
            hide_index=True,
            width="stretch",
            alt="Cola de recuperación con datos del paciente",
            column_config={
                "grupo": st.column_config.TextColumn("Grupo", width="medium"),
                "paciente": st.column_config.TextColumn("Paciente", width="medium"),
                "celular": "Celular",
                "email": "Email",
                "tipo": "Evento",
                "fecha_evento": "Fecha evento",
                "dias": st.column_config.NumberColumn("Días", format="%d"),
                "alerta_badge": st.column_config.MultiselectColumn(
                    "Alerta",
                    options=alerta_opts,
                    color=alerta_colors,
                    disabled=True,
                    width="small",
                ),
                "intentos": "Intentos",
                "antiguedad": "Antigüedad",
            },
        )

        etiquetas = {
            r.evento_id: f"{r.paciente} · {r.tipo} · {r.alerta} · {r.dias} días"
            for r in vista.itertuples()
        }
        evento_id = st.selectbox(
            "Paciente a contactar",
            list(etiquetas),
            format_func=lambda i: etiquetas[i],
        )
        fila = vista[vista["evento_id"] == evento_id].iloc[0]
        es_cancelacion = fila["tipo"] == "cancelacion"
        sin_motivo = es_cancelacion and not fila["motivo"]

        izq, der = st.columns([1, 1], gap="large")
        with izq:
            with st.container(border=True):
                st.markdown("##### Ficha del paciente")
                st.markdown(f"### {fila['paciente']}")
                badges = st.container(horizontal=True, gap="small")
                with badges:
                    st.badge(str(fila["alerta"]), color=_alerta_badge(str(fila["alerta"])))
                    st.badge(str(fila["antiguedad"]), color="gray")
                    st.badge(str(fila["tipo"]), color="violet")

                if pd.notna(fila.get("id_software")):
                    st.caption(f"ID software · {int(fila['id_software'])}")

                st.divider()
                c_cel = _campo_txt(fila, "celular")
                c_tel = _campo_txt(fila, "telefono")
                c_mail = _campo_txt(fila, "email")
                st.markdown(
                    f":material/call: **Celular:** {c_cel or '_sin dato_'}  \n"
                    f":material/phone: **Teléfono:** {c_tel or '_sin dato_'}  \n"
                    f":material/mail: **Email:** {c_mail or '_sin dato_'}"
                )
                st.divider()
                st.markdown(
                    f"**Grupo:** {fila['grupo']}  \n"
                    f"**Evento:** {fila['tipo']} el {pd.Timestamp(fila['fecha_evento']):%d/%m/%Y}  \n"
                    f"**Días desde el evento:** {int(fila['dias'])}"
                )
                if es_cancelacion:
                    st.markdown(f"**Motivo de cancelación:** {fila['motivo'] or '_sin registrar_'}")

            hist = rules.intentos(con, int(evento_id))
            if not hist.empty:
                st.write("")
                with st.container(border=True):
                    st.markdown("##### Intentos registrados")
                    hist = hist.copy()
                    hist["resultado"] = hist["resultado"].map(rules.RESULTADOS)
                    st.dataframe(hist, hide_index=True, width="stretch", alt="Historial de intentos de contacto")

            if sin_motivo:
                st.warning(
                    "Elija el motivo antes de registrar un intento o cerrar el caso.",
                    icon=":material/warning:",
                    title="Cancelación sin motivo",
                )

            pendiente = fila["pendiente"]
            opciones_dia = list(rules.PASOS)
            indice = opciones_dia.index(int(pendiente)) if pd.notna(pendiente) else len(opciones_dia) - 1

            st.write("")
            with st.container(border=True):
                with st.form("registrar_intento", clear_on_submit=True):
                    st.markdown("##### Registrar intento")
                    dia = st.selectbox("Día de protocolo", opciones_dia, index=indice)
                    resultado = st.selectbox(
                        "Resultado",
                        list(rules.RESULTADOS),
                        format_func=lambda x: rules.RESULTADOS[x],
                    )
                    motivo = None
                    if sin_motivo:
                        motivo = st.selectbox("Motivo de cancelación (obligatorio)", [""] + rules.MOTIVOS)
                    nota = st.text_input("Nota")
                    guardar = st.form_submit_button("Guardar intento", type="primary", width="stretch")

            if guardar:
                try:
                    rules.registrar_intento(
                        con, int(evento_id), int(dia), resultado, nota, R.date(), motivo or None
                    )
                    st.success("Intento guardado.", icon=":material/check_circle:")
                    st.rerun()
                except (ValueError, sqlite3.IntegrityError) as e:
                    st.error(str(e))

            with st.expander("Cerrar sin recuperar"):
                motivo_cierre = None
                if sin_motivo:
                    motivo_cierre = st.selectbox(
                        "Motivo de cancelación", [""] + rules.MOTIVOS, key="cierre_motivo"
                    )
                if st.button("Cerrar este caso como sin recuperar", width="stretch"):
                    try:
                        rules.cerrar_sin_recuperar(con, int(evento_id), motivo_cierre or None)
                        st.success("Caso cerrado.", icon=":material/check_circle:")
                        st.rerun()
                    except (ValueError, sqlite3.IntegrityError) as e:
                        st.error(str(e))

        with der:
            with st.container(border=True):
                st.markdown("##### Mensaje de WhatsApp")
                plantilla, texto = messages.mensaje(
                    fila["grupo"],
                    fila["servicio"] if pd.notna(fila["servicio"]) else None,
                    fila["motivo"] if pd.notna(fila["motivo"]) else None,
                    fila["nombre"] if pd.notna(fila.get("nombre")) else None,
                    fila["apellidos"] if pd.notna(fila.get("apellidos")) else None,
                )
                st.caption(f"Plantilla · {plantilla}")
                st.markdown(texto)

                st.divider()
                cel_paciente = _celular_paciente(fila)
                wa_key = f"wa_cel_{int(evento_id)}"
                if wa_key not in st.session_state:
                    st.session_state[wa_key] = cel_paciente

                if cel_paciente:
                    st.badge("Celular de la base", color="green", icon=":material/database:")
                else:
                    st.badge("Sin celular en la base", color="orange", icon=":material/edit:")

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
                else:
                    st.caption("Se abrirá WhatsApp con el mensaje listo. Revise y envíe usted.")

with tab_chat:
    st.subheader("Asistente IA")
    st.caption("Consulta agenda, huecos, recuperación y seguimiento con los datos del día.")

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    chat_container = st.container(height=400, border=True)
    with chat_container:
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    pregunta = st.chat_input("Haz una pregunta...")

    if pregunta:
        st.session_state.chat_history.append({"role": "user", "content": pregunta})

        with chat_container:
            for msg in st.session_state.chat_history:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

            with st.chat_message("assistant"):
                with st.spinner("Consultando información..."):
                    respuesta = responder(con, pregunta, st.session_state.chat_history)

        st.session_state.chat_history.append({"role": "assistant", "content": respuesta})
        st.rerun()

con.close()
