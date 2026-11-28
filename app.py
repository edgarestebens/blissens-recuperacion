"""Pantalla para la auxiliar. Ejecutar desde la carpeta del proyecto:

    streamlit run app.py

Lee data/blissens.db (se crea con: python -m src.load). No envía mensajes: solo prepara el borrador.
"""
from __future__ import annotations

import base64
import re
import sqlite3
from pathlib import Path
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


TIPOS_LEGIBLES = {
    "cancelacion": "Cancelación",
    "no_asistencia": "No asistió",
    "diagnostico_sin_continuidad": "Diagnóstico sin continuidad",
    "inactivo": "Inactivo",
}


def _tipo_legible(tipo: str) -> str:
    return TIPOS_LEGIBLES.get(tipo, str(tipo).replace("_", " ").capitalize())


def _campo_txt(fila: pd.Series, key: str) -> str | None:
    v = fila.get(key)
    if v is None or (isinstance(v, float) and pd.isna(v)) or pd.isna(v):
        return None
    s = str(v).strip()
    return s or None


LOGO_PATH = Path(__file__).parent / "assets" / "logo.png"
if not LOGO_PATH.exists():
    _jpeg = Path(__file__).parent / "image" / "logo.jpeg"
    if _jpeg.exists():
        LOGO_PATH = _jpeg


def _logo_data_uri() -> str:
    if not LOGO_PATH.exists():
        return ""
    raw = base64.b64encode(LOGO_PATH.read_bytes()).decode()
    mime = "image/png" if LOGO_PATH.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{raw}"


st.set_page_config(
    page_title="Recuperación de pacientes · Blissens",
    page_icon=str(LOGO_PATH) if LOGO_PATH.exists() else ":material/dentistry:",
    layout="wide",
    initial_sidebar_state="expanded",
)

ESTILO_MARCA = """
<style>
/* Etiquetas en versalitas con tracking amplio, como en las portadas de Be Talks */
.bl-eyebrow {
    font-size: 0.72rem; font-weight: 600; letter-spacing: 0.18em;
    text-transform: uppercase; color: #167A71; margin: 0 0 0.25rem 0;
}
.bl-marca { display: flex; align-items: center; gap: 0.85rem; margin-bottom: 0.25rem; }
.bl-logo {
    width: 52px; height: 52px; border-radius: 50%; background: #0B0B0C;
    display: flex; align-items: center; justify-content: center;
    font-family: 'Cormorant Garamond', serif; font-weight: 700; font-size: 1.35rem;
    color: #F3EEE6; letter-spacing: 0.02em;
    box-shadow: 0 0 0 2px #0B0B0C, 0 0 0 4px #2FB5A8, 0 0 0 6px #8E7CC3;
}
.bl-logo-img { width: 56px; height: 56px; border-radius: 50%; flex-shrink: 0; }
.bl-nombre { font-family: 'Cormorant Garamond', serif; font-size: 1.6rem; font-weight: 600; line-height: 1.1; color: #F3EEE6; }
.bl-sub { font-size: 0.68rem; letter-spacing: 0.2em; text-transform: uppercase; color: #2FB5A8; }

/* Titulares serif, con itálica para el énfasis */
h1 { font-weight: 600 !important; letter-spacing: -0.01em; }
h1 em, h2 em { font-style: italic; color: #167A71; }

/* Sin iconos de enlace junto a los títulos */
[data-testid="stHeaderActionElements"] { display: none; }

/* Tarjetas con sombra suave */
[data-testid="stVerticalBlockBorderWrapper"] { box-shadow: 0 1px 2px rgba(20,20,20,0.04), 0 6px 18px rgba(20,20,20,0.04); }

/* Métricas: cifra en serif, etiqueta en versalitas */
[data-testid="stMetricValue"] {
    font-family: 'Cormorant Garamond', serif; font-weight: 600; font-size: 2.3rem;
    font-variant-numeric: lining-nums; font-feature-settings: "lnum" 1;
}
[data-testid="stMetricLabel"] p {
    font-size: 0.66rem; letter-spacing: 0.06em; text-transform: uppercase; color: #6F675B;
    white-space: normal; overflow: visible; text-overflow: clip;
}
[data-testid="stMetricLabel"] { overflow: visible; }

/* Pestañas */
button[data-baseweb="tab"] p { font-size: 0.78rem; letter-spacing: 0.12em; text-transform: uppercase; font-weight: 600; }

/* Botón primario */
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"], a[data-testid="stBaseLinkButton-primary"] {
    background: #0B0B0C; border-color: #0B0B0C; color: #F3EEE6; letter-spacing: 0.06em;
}
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover, a[data-testid="stBaseLinkButton-primary"]:hover {
    background: #167A71; border-color: #167A71; color: #FFFFFF;
}

/* Calendario React Aria: los días son div[role=button], no baseweb */
td[role="gridcell"] div[role="button"],
div[role="button"][aria-label*="2026"],
div[role="button"][aria-label*="2025"],
[data-testid="stDateInput"] table[role="grid"] div[role="button"] {
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
}
td[role="gridcell"] div[role="button"][aria-disabled="true"],
div[role="button"][aria-label*="2026"][aria-disabled="true"] {
    color: rgba(255, 255, 255, 0.45) !important;
    -webkit-text-fill-color: rgba(255, 255, 255, 0.45) !important;
}
[data-testid="stDateInput"] table[role="grid"] th,
[data-testid="stDateInput"] table[role="grid"] [role="columnheader"] {
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
}
section[data-testid="stSidebar"] [data-testid="stDateInput"] input,
section[data-testid="stSidebar"] [data-baseweb="input"] input,
section[data-testid="stSidebar"] [data-testid="stDateInput"] [data-baseweb="input"] {
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
}
</style>
"""
st.html(ESTILO_MARCA)

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
    _logo_uri = _logo_data_uri()
    _logo_html = (
        f'<img class="bl-logo-img" src="{_logo_uri}" alt="Logo Blissens">'
        if _logo_uri
        else '<div class="bl-logo">BS</div>'
    )
    st.markdown(
        f'<div class="bl-marca">{_logo_html}'
        '<div><div class="bl-nombre">Blissens</div>'
        '<div class="bl-sub">Wellness Dentist</div></div></div>',
        unsafe_allow_html=True,
    )
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
    st.markdown('<p class="bl-eyebrow">Blissens · Seguimiento día 3, 7 y 15</p>', unsafe_allow_html=True)
    st.title("Recuperación de *pacientes*")
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
        r1 = st.columns(7)
        r1[0].metric(
            "Citas",
            k["citas"],
            help="Total de citas de la fecha de referencia en la agenda (todos los estados).",
        )
        r1[1].metric(
            "Atendidas",
            k["atendidas"],
            help="Citas con estado atendido ese día. Cuentan en la ocupación.",
        )
        r1[2].metric(
            "Confirmadas",
            k["confirmadas"],
            help=(
                "Confirmado por teléfono, WhatsApp o email. No cuentan como atendidas ni en la "
                "ocupación ni como recuperación: la clínica las trata como pendientes de depurar. "
                "El detalle está en Confirmadas del día."
            ),
        )
        r1[3].metric(
            "Agendadas",
            k["agendadas"],
            help="Citas aún sin confirmar (p. ej. “No confirmado” en el Excel). Cuentan en la ocupación.",
        )
        r1[4].metric(
            "No asistieron",
            k["no_asiste"],
            help="Citas con estado no asiste ese día. Liberan hueco y pueden entrar a la cola de recuperación.",
        )
        r1[5].metric(
            "Cancelaciones",
            k["cancelaciones"],
            help="Citas anuladas o anuladas por el paciente ese día. Liberan hueco y pueden entrar a la cola.",
        )
        r1[6].metric(
            "Cambio de fecha",
            k["cambio_fecha"],
            help="Citas movidas a otro día. Liberan hueco, no entran a la cola y se excluyen del denominador de ocupación.",
        )
        r2 = st.columns(2)
        r2[0].metric(
            "Huecos libres",
            k["huecos_libres"],
            help=(
                "Cupos del día liberados (anulado, anulado por paciente, no asiste o cambio de fecha) "
                "que aún no tienen otra cita válida en el mismo sillón y horario."
            ),
        )
        if k["ocupacion"] is not None:
            ayuda_ocup = (
                f"Ocupación = (atendidas + agendadas) ÷ (citas − cambio de fecha) "
                f"= {k['ocupacion_num']} ÷ {k['ocupacion_den']} = {k['ocupacion']:.0%}. "
                "Las confirmadas no entran: pendientes de depuración."
            )
        else:
            ayuda_ocup = (
                "Ocupación = (atendidas + agendadas) ÷ (citas − cambio de fecha). "
                "Las confirmadas no entran. Sin citas en el denominador para este día."
            )
        r2[1].metric(
            "Ocupación",
            f"{k['ocupacion']:.0%}" if k["ocupacion"] is not None else "—",
            help=ayuda_ocup,
        )

    st.write("")
    with st.container(border=True):
        st.subheader("Confirmadas del día")
        conf_dia = res["confirmadas_dia"]
        st.caption(
            "Citas en estado confirmado ese día. No suman a ocupación ni cierran recuperación: "
            "según la clínica son citas no cerradas, pendientes de depurar como inasistencia "
            "(no se meten solas a la cola hasta cerrar el estado en el software)."
        )
        if conf_dia.empty:
            st.info(
                "No hay citas confirmadas en esta fecha.",
                icon=":material/info:",
                title="Sin confirmadas",
            )
        else:
            st.dataframe(
                conf_dia,
                hide_index=True,
                width="stretch",
                alt="Citas confirmadas del día para depuración",
                column_config={
                    "hora": st.column_config.TextColumn("Hora", width="medium"),
                    "sillon": st.column_config.TextColumn("Sillón", width="small"),
                    "paciente": st.column_config.TextColumn("Paciente", width="large"),
                    "id_software": st.column_config.NumberColumn("ID software", format="%d", width="small"),
                },
            )

    st.write("")
    with st.container(border=True):
        st.subheader("Recuperación")
        a, b, cc = st.columns(3)
        a.metric(
            "En protocolo",
            n_cola,
            help="Pacientes en la cola de recuperación (evento abierto, dentro de los 15 días del protocolo).",
        )
        b.metric(
            "Recuperados (15 días)",
            res["recuperados"],
            help="Pacientes con una cita válida (atendida o agendada) dentro de los 15 días posteriores al evento. Las confirmadas no cuentan.",
        )
        cc.metric(
            "Fuera de protocolo",
            res["fuera_protocolo"],
            help="Casos abiertos con más de 15 días desde el evento. Ya no aparecen en la cola activa.",
        )

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

        # Sin celular ni email en la tabla: se ven solo en la ficha del paciente elegido.
        tabla = vista[["paciente", "tipo", "fecha_evento", "dias", "alerta_badge", "intentos", "grupo"]].copy()
        tabla["tipo"] = tabla["tipo"].map(_tipo_legible)
        tabla["fecha_evento"] = pd.to_datetime(tabla["fecha_evento"]).dt.strftime("%d/%m/%Y")

        st.caption("Haga clic en una fila para abrir la ficha del paciente.")
        seleccion = st.dataframe(
            tabla,
            hide_index=True,
            width="stretch",
            height=320,
            on_select="rerun",
            selection_mode="single-row",
            key=f"tabla_cola_{grupo_sel}",
            alt="Cola de recuperación: seleccione una fila para ver la ficha",
            column_config={
                "paciente": st.column_config.TextColumn("Paciente", width="medium"),
                "tipo": st.column_config.TextColumn("Evento", width="medium"),
                "fecha_evento": st.column_config.TextColumn("Fecha", width="medium"),
                "dias": st.column_config.NumberColumn("Días", format="%d", width="small"),
                "alerta_badge": st.column_config.MultiselectColumn(
                    "Alerta",
                    options=alerta_opts,
                    color=alerta_colors,
                    disabled=True,
                    width="small",
                ),
                "intentos": st.column_config.NumberColumn("Intentos", width="small"),
                "grupo": st.column_config.TextColumn("Grupo", width="medium"),
            },
        )

        filas_sel = seleccion.selection.rows
        idx = filas_sel[0] if filas_sel else 0
        evento_id = vista.iloc[idx]["evento_id"]
        fila = vista.iloc[idx]
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
                    st.badge(_tipo_legible(fila["tipo"]), color="violet")

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
                    f"**Evento:** {_tipo_legible(fila['tipo'])} el {pd.Timestamp(fila['fecha_evento']):%d/%m/%Y}  \n"
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

    chat_container = st.container(height=300, border=True)
    with chat_container:
        if not st.session_state.chat_history:
            st.markdown('<p class="bl-eyebrow">Pregúntame sobre el día</p>', unsafe_allow_html=True)
            st.caption("Elija una sugerencia o escriba su propia pregunta abajo.")
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    sugerida = None
    if not st.session_state.chat_history:
        sugerencias = [
            "¿Cuántas citas se cancelaron hoy?",
            "¿A quién debo contactar primero?",
            "¿Qué pacientes están en alerta del día 15?",
        ]
        cols_sug = st.columns(len(sugerencias))
        for col, texto_sug in zip(cols_sug, sugerencias):
            if col.button(texto_sug, key=f"sug_{texto_sug}", width="stretch"):
                sugerida = texto_sug

    pregunta = st.chat_input("Haz una pregunta...") or sugerida

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
