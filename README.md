# Recuperación de pacientes y agenda — Blissens Odontología

Prototipo local para la auxiliar de la clínica. Lee la agenda, la guarda en una base de datos SQLite propia y ayuda a decidir a quién contactar y en qué orden. El envío de WhatsApp sigue siendo manual.

La descripción completa del plan está en [PLAN.md](PLAN.md).

## Estado actual

| Pieza | Estado |
|---|---|
| Base de datos SQLite (`data/blissens.db`) | Hecha. Tiene 885 citas y 255 pacientes cargados |
| Carga de los Excel a la base (`src/load.py`) | Hecha. Corre sola al abrir la app y no duplica datos |
| Línea base histórica (`src/baseline.py`) | Hecha. Resultado en `data/linea_base.json` |
| Reglas de la cola (3 grupos, alertas día 3, 7 y 15) (`src/rules.py`) | Hecho y probado |
| Cruce de huecos con candidatos (`src/rules.py`) | Hecho |
| Plantillas de WhatsApp (`src/messages.py`) | Hecho, tomadas de `Guiones_Blissens_.xlsx` |
| Pantalla Streamlit (`app.py`) | Hecha. Falta probarla con la auxiliar |
| Asistente IA con Ollama (`src/chatbot.py`) | Hecho. Usa el modelo local `llama3.2:latest` |
| Conector automático a la API o al export | Pendiente |
| Prueba 1 (agosto contra el cierre manual) | Pendiente |
| Prueba 2 (piloto de 2 semanas) | Pendiente |

## Requisitos

- Python 3.10 o superior.
- Las librerías de `requirements.txt`: `pandas`, `openpyxl`, `streamlit` y `ollama`.
- [Ollama](https://ollama.com/) instalado y en ejecución, con el modelo `llama3.2:latest` descargado (solo si va a usar la pestaña **Asistente IA**).

Instalación, una sola vez, desde la carpeta del proyecto:

```powershell
pip install -r requirements.txt
```

### Ollama (asistente IA)

Desde PowerShell:

```powershell
pip install ollama
irm https://ollama.com/install.ps1 | iex
```

Luego descargue el modelo que usa la app y compruebe que responde:

```powershell
ollama pull llama3.2:latest
ollama run llama3.2:latest
```

Sin Ollama activo o sin ese modelo, el resto de la app funciona; solo falla la pestaña **Asistente IA**.

### Instalación en un computador sin Python

1. Descargue Python 3.10 o superior desde [python.org](https://www.python.org/downloads/).
2. En el instalador, marque **"Add python.exe to PATH"** antes de presionar *Install*. Si no lo marca, PowerShell no reconocerá `python` ni `pip`.
3. Abra PowerShell en la carpeta del proyecto y ejecute `pip install -r requirements.txt`.
4. Si va a usar el asistente IA, ejecute `pip install ollama` y `irm https://ollama.com/install.ps1 | iex`, luego `ollama pull llama3.2:latest`.
5. Si la carpeta `documentos iniciales` tiene los Excel de agenda, la app carga los datos sola al abrirse. No hace falta ningún paso adicional.
6. Abra la aplicación con `streamlit run app.py`.

Para llevar el proyecto a otro computador, copie toda la carpeta, incluida `data/`. La base ya tiene los datos cargados. Si contiene datos reales de la clínica, solo debe copiarse a un computador autorizado.

## Cómo correr lo que existe hoy

Abra una terminal en la carpeta del proyecto, `c:\cursos\cursos IA\studIA\odontologica`.

```powershell
# 1. Calcula la línea base y la guarda en data/linea_base.json
python -m src.baseline

# Opcional: línea base hasta una fecha (para excluir el piloto)
python -m src.baseline --hasta 2026-11-10
```

Es seguro correr `src.load` varias veces. Si la agenda cambia, se actualizan las citas que cambiaron de estado y el cambio queda registrado en `citas_historial`.

## De dónde salen los datos

Ambos archivos se unen por `# Cita`.

**`Agenda citas y estados .xlsx`** (885 filas)

| Columna del Excel | Columna en la base | Transformación |
|---|---|---|
| `# Cita` | `citas.cita_id` | Ninguna. Es la clave de la carga |
| `# Paciente` | `pacientes.paciente_id` | Código con sal local, por ejemplo `P00aa8eaf37` (clave estable) |
| `# Paciente` | `pacientes.id_software` | Se guarda el número del software |
| `Nombre Paciente` | `pacientes.nombre` | Texto limpio |
| `Apellidos Paciente` | `pacientes.apellidos` | Texto limpio |
| `# Tratamiento` | `citas.tratamiento_ref` | Código con sal, por ejemplo `T9bf0608fef` |
| `Fecha Cita` | `citas.fecha` | Formato `aaaa-mm-dd` |
| `Tratamiento o Diagnóstico` | `citas.tipo_cita` | Ninguna |
| `Estado actual cita` | `citas.estado_original` | Se guarda tal cual |
| `Estado actual cita` | `citas.estado` | Se normaliza, por ejemplo `Anulado por pcte. via Whatsapp` pasa a `anulado_paciente` |
| `Antigüedad paciente` | `pacientes.antiguedad` | Si un paciente tiene varias filas, gana `Nuevo` sobre `Antiguo`. Sin dato queda `Desconocida` |
| `Fecha Cita` | `pacientes.primera_cita` | Fecha mínima del paciente. No es columna del Excel |

**`Agenda y citas .xlsx`** (231 filas con horario)

| Columna del Excel | Columna en la base | Transformación |
|---|---|---|
| `Hora Inicio Cita` | `citas.hora_inicio` | Se corta a `HH:MM` |
| `Hora Fin Cita` | `citas.hora_fin` | Se corta a `HH:MM` |
| `Sillón (Recurso)` | `citas.sillon` | Ninguna |
| `Comentario Cita` | `citas.servicio` | No se guarda el texto. Se convierte en categoría (limpieza, alineadores, laboratorio, etc.) |
| `Tipo Paciente` | `pacientes.tipo_paciente` | Los guiones `-` quedan vacíos |
| `Celular` | `pacientes.celular` | Texto; si falta en estados, se toma de aquí |
| `Teléfono` | `pacientes.telefono` | Texto; los guiones `-` quedan vacíos |
| `E-Mail` | `pacientes.email` | Texto |

El estado sale solo de `Agenda citas y estados`. La columna `Estado Cita` de este archivo no se usa.

**No se cargan:** cédulas, fecha de nacimiento, apoderado, convenio, profesional, sucursal, observaciones ni motivo de atención.

**Tablas que no vienen de los Excel**

- `citas_historial`: se llena sola cuando una cita cambia de estado en una carga posterior.
- `eventos_perdida` e `intentos_contacto`: se llenarán con la app al registrar cancelaciones, motivos e intentos.
- `huecos`: creada pero vacía. Su cálculo todavía no está programado.
- `sqlite_sequence`: la crea SQLite automáticamente.

## Cómo mirar los datos de la base

El archivo `data/blissens.db` es binario. El editor lo muestra como texto ilegible, así que conviene cerrar esa pestaña antes de trabajar.

**Desde la terminal**, para listar las tablas:

```powershell
python -c "import sqlite3; c=sqlite3.connect('data/blissens.db'); print([r[0] for r in c.execute(\"select name from sqlite_master where type='table'\")])"
```

Para ver las primeras filas de una tabla:

```powershell
python -c "import pandas as pd, sqlite3; c=sqlite3.connect('data/blissens.db'); print(pd.read_sql('select * from citas limit 20', c).to_string())"
```

Cambie `citas` por `pacientes`, `eventos_perdida`, `intentos_contacto` o `citas_historial` para ver otras tablas.

**Con una aplicación**, cualquiera de estas dos opciones:

- Extensión **SQLite Viewer** (de Florian Klampfer) en VS Code. Al hacer clic en el archivo se abre como tablas.
- **DB Browser for SQLite** (gratuita, sqlitebrowser.org). Es la opción más cómoda para explorar y filtrar.

## Cómo correr el aplicativo

Desde la carpeta del proyecto:

```powershell
streamlit run app.py
```

Los Excel de agenda están en la carpeta `documentos iniciales/`. La app revisa al abrirse si cambiaron desde la última carga, si falta `data/blissens.db`, o si los pacientes todavía no tienen nombre. Si aplica, carga la agenda sola y muestra un aviso. No hace falta correr `python -m src.load` a mano.

Se abre en el navegador la pantalla para la auxiliar. Tiene tres pestañas:

- **Panel del día:** KPIs del día, en cola, y huecos con candidato sugerido (solo en fechas con horario).
- **Cola de recuperación:** tres grupos, alerta día 3, 7 o 15, nombre y celular del paciente, historial de intentos, registro de intento con motivo obligatorio en cancelaciones, y el mensaje de WhatsApp con el nombre ya completado.
- **Asistente IA:** chat local con Ollama. Pregunta en español sobre KPIs, cola, huecos y seguimiento. La respuesta se basa solo en un resumen de la base del día; si no hay dato, el asistente debe indicarlo.

En la barra lateral se elige la **fecha de referencia**. La app muestra lo que se sabía ese día, así que sirve para repetir la Prueba 1 con agosto. Por defecto usa la última fecha con datos (12/11/2026).

La app no envía mensajes: el mensaje se copia y la auxiliar lo envía a mano por WhatsApp. Si hay celular en la base, aparece junto a la plantilla.

### Cómo funciona el asistente IA

- El módulo `src/chatbot.py` arma un resumen del día (KPIs, recuperados, fuera de protocolo, parte de la cola y de los huecos) y se lo pasa al modelo junto con la pregunta.
- Usa el cliente Python de Ollama contra el modelo `llama3.2:latest` en la máquina local. No llama a APIs en la nube.
- Conserva hasta las últimas 10 intervenciones del historial de la sesión de Streamlit.
- No ejecuta consultas SQL libres ni inventa pacientes: solo interpreta los datos que le entrega la app.

### Reglas que aplica la cola

- **Tratamiento interrumpido:** cancelación, no asistencia o diagnóstico atendido sin cita válida posterior, de un paciente antiguo.
- **Paciente nuevo que no volvió:** lo mismo para pacientes con antigüedad Nuevo.
- **Inactivo más de 3 meses:** última cita válida hace más de 90 días.
- Un evento entra a la cola en el día 0 y aparece con alerta en los días 3, 7 y 15. Un intento en el día 7 cubre también el día 3.
- Si el paciente tiene una cita válida dentro de los 15 días, sale como **recuperado**.
- Pasados 15 días sin recuperación, sale de la cola como **fuera de protocolo** hasta que se cierre.
- Orden de prioridad: alerta más alta primero, luego antiguos antes que nuevos, luego los más antiguos.

## Estructura del proyecto

```
odontologica/
├── src/
│   ├── db.py          # esquema de la base SQLite
│   ├── load.py        # lectura de los Excel y carga (incluye datos básicos del paciente)
│   ├── baseline.py    # línea base histórica
│   ├── rules.py       # huecos, cola, alertas 3/7/15 y registro de intentos
│   ├── messages.py    # plantillas de WhatsApp
│   └── chatbot.py     # asistente IA local con Ollama
├── app.py             # pantalla Streamlit
├── documentos iniciales/   # Excel de agenda, guiones, arancel, ficha del reto y propuesta
├── data/
│   ├── blissens.db    # base SQLite (no se versiona)
│   └── linea_base.json
├── PLAN.md
├── README.md
├── requirements.txt
└── .gitignore
```

## Datos personales

- La base **sí guarda** datos básicos del paciente: nombre, apellidos, celular, teléfono, email e `id_software`.
- No se cargan cédulas, fecha de nacimiento, apoderado ni observaciones clínicas.
- El `paciente_id` interno sigue siendo un código con sal (clave estable entre cargas); el `# Paciente` del software queda en `id_software`.
- Los comentarios de las citas se convierten en una categoría (limpieza, alineadores, etc.). El texto libre no se guarda.
- El asistente IA corre en local con Ollama: el resumen del día y las preguntas no se envían a un servicio externo.
- Los Excel originales, la base (`data/blissens.db`) y la línea base están en `.gitignore`. No se suben a GitHub. Use la app solo en un computador autorizado de la clínica.

## Limitaciones de los datos actuales

- Los Excel no traen motivo de cancelación. En el histórico queda como "Sin registrar" y empieza a existir con la app.
- Solo octubre trae hora y sillón. La medición de huecos ocupados solo es válida para ese mes.
- Las citas de "cambio de fecha" (266) se tratan como cupos movidos, no como pérdidas. Conviene confirmarlo con la auxiliar.
- El histórico cubre unos 3,5 meses. Eso no alcanza para medir la recuperación de inactivos de más de 3 meses.
