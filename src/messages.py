"""Borradores de WhatsApp tomados de Guiones_Blissens_.xlsx (hoja "Guiones organizados").

Los textos son los del guion, con dos adaptaciones:
- Seguimiento del plan: se reemplaza "el cierre de tu plan de tratamiento" por el tratamiento
  pendiente cuando se conoce (según la categoría del comentario de la cita).
- [NOMBRE] se completa con el nombre del paciente cuando está en la base.
"""
from __future__ import annotations

from .rules import GRUPO_INACT, MOTIVOS

MOTIVO_SALUD = MOTIVOS[0]

# "Seguimiento del plan de tratamiento"
PLAN = (
    "Hola, [NOMBRE]. Te escribimos de parte de la Dra. Sara López. Tenemos pendiente agendar una cita "
    "para continuar con {tratamiento}. ¿Prefieres una cita en la mañana o en la tarde?"
)
PLAN_DEFAULT = "el cierre de tu plan de tratamiento"
TRAT_LABEL = {
    "ortodoncia": "tu tratamiento de ortodoncia",
    "alineadores": "tu tratamiento con alineadores",
    "implantes": "tu tratamiento de implantes",
    "endodoncia": "tu tratamiento de endodoncia",
    "cirugia": "tu tratamiento de cirugía",
    "resina": "tu tratamiento de resinas",
    "placa": "tu placa desprogramadora",
    "blanqueamiento": "tu blanqueamiento",
    "laboratorio": "tus trabajos de laboratorio",
}

# "Paciente de limpieza o revisión cada 4 o 6 meses"
LIMPIEZA = (
    "Hola, [NOMBRE]. En BLISSENS ODONTOLOGÍA sabemos que tienes muchas ocupaciones y por eso queremos "
    "recordarte que ya es momento de programar tu próxima limpieza dental con la Dra. Sara López. "
    "¿Agendamos tu cita? ¿Prefieres en la mañana o en la tarde?"
)

# "Paciente inactivo – recuperación de base de datos"
INACTIVO = (
    "Hola, [NOMBRE]. ¡Te extrañamos y queremos que lo sepas! En BLISSENS ODONTOLOGÍA queremos seguir "
    "cuidando tu sonrisa. Nos encantaría volver a verte y acompañarte en tu salud oral. ¿Te gustaría "
    "agendar una cita con el Dr. Juan Manuel Olarte o la Dra. Sara López?"
)

# "Respuesta a cancelación por motivo de salud"
SALUD = (
    "Buenos días, [NOMBRE]. ¿Cómo estás? Comprendemos la cancelación de la cita y les deseamos una "
    "pronta recuperación."
)


def _nombre_mostrar(nombre: str | None, apellidos: str | None = None) -> str | None:
    partes = [p for p in (nombre, apellidos) if p and str(p).strip()]
    if not partes:
        return None
    return " ".join(partes)


def mensaje(
    grupo: str,
    servicio: str | None,
    motivo: str | None,
    nombre: str | None = None,
    apellidos: str | None = None,
) -> tuple[str, str]:
    """Devuelve (nombre de la plantilla, texto). Completa [NOMBRE] si hay dato."""
    if motivo == MOTIVO_SALUD:
        plantilla, texto = "Respuesta a cancelación por motivo de salud", SALUD
    elif grupo == GRUPO_INACT:
        plantilla, texto = "Paciente inactivo – recuperación de base de datos", INACTIVO
    elif servicio in ("limpieza", "revision"):
        plantilla, texto = "Paciente de limpieza o revisión cada 4 o 6 meses", LIMPIEZA
    else:
        tratamiento = TRAT_LABEL.get(servicio or "", PLAN_DEFAULT)
        plantilla, texto = "Seguimiento del plan de tratamiento", PLAN.format(tratamiento=tratamiento)

    completo = _nombre_mostrar(nombre, apellidos)
    if completo:
        # En el saludo basta el primer nombre.
        saludo = (nombre or completo).strip().split()[0]
        texto = texto.replace("[NOMBRE]", saludo)
    return plantilla, texto
