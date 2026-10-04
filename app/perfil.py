"""
Perfil del candidato: la unica fuente de verdad sobre quien usa el sistema.

ESTE ARCHIVO ES UNA PLANTILLA. Todos los datos de identidad son EJEMPLOS
FICTICIOS marcados con "EJEMPLO"; sustituyelos por los tuyos antes de usar el
generador de correos, los correos en frio o la preparacion de postulaciones.
No publiques tu perfil real en un repositorio (ver README, "Configuracion").

Lo que NO es identidad -- el vocabulario de nivel, geografia y areas que
importa `analisis.py` -- se deja tal cual: cambiarlo cambia la clasificacion de
todas las vacantes.

La regla que manda sobre todo el sistema: ningun dato que no este aqui se
inventa. Lo que vale None no se rellena solo: se pregunta, o no se usa.
"""

CANDIDATO = {
    "nombre": "EJEMPLO — Tu Nombre",
    "correo": "tu.correo@example.com",
    "telefono": "EJEMPLO — +52 00 0000 0000",
    "linkedin": "https://www.linkedin.com/in/EJEMPLO-tu-perfil",
    "github": "https://github.com/EJEMPLO-tu-usuario",
    "ciudad": "EJEMPLO — Tu ciudad, Estado, Mexico",
    "zona_horaria": "EJEMPLO — America/Mexico_City (UTC-6)",
    "titulo_objetivo": "EJEMPLO — Practicas o primer empleo en tu area",
    "grado": "EJEMPLO — Tu carrera, tu universidad (anio de inicio - anio de fin)",
    "ingles": "EJEMPLO — B1 / intermedio",
    "espanol": "nativo",
    "requiere_patrocinio_visa": True,
    "puede_presencial": ["EJEMPLO — tu ciudad"],
    "acepta_remoto_global": True,
}

# Municipios del Area Metropolitana de Monterrey. Es vocabulario de la zona
# base `monterrey`, no un dato personal: la zona activa se elige con
# ULTRACHAMBA_ZONA y su definicion vive en `areas.py`. Se conserva aqui porque
# otros modulos lo importan.
AMM = [
    "monterrey", "nuevo leon", "san pedro garza garcia", "san nicolas",
    "guadalupe", "apodaca", "santa catarina", "escobedo", "garcia",
    "juarez, n", "santiago, n", "cadereyta", "salinas victoria", "mty",
]

# Habilidades verificables de TU CV, con el peso (1 a 10) que cada una aporta
# al encaje. Pesa mas lo que puedes demostrar con un entregable. Solo cuenta lo
# que pongas aqui: vacio, el sistema no suma puntos por habilidades y lo dice.
# Formato (terminos en minusculas y sin acentos):
#     HABILIDADES = {"excel": 6, "sap": 8, "power bi": 5, "conciliaciones": 7}
HABILIDADES: dict[str, int] = {}

# Habilidades que estas estudiando pero todavia no puedes demostrar. El
# generador de correos las nombra con ese matiz, nunca como "lo hice".
HABILIDADES_EN_ESTUDIO: set[str] = set()

# Señales de que la vacante es alcanzable para alguien sin años de experiencia.
NIVEL_PRACTICAS = [
    "intern", "internship", "interno de", "becario", "becaria", "beca ",
    "practicante", "practicas profesionales", "practicas ", "trainee",
    "co-op", "coop program", "apprentice", "aprendiz", "student program",
    "estudiante", "summer analyst", "working student", "werkstudent",
    "graduate program", "programa de graduados", "early talent",
    "residencia profesional", "servicio social",
]
NIVEL_JUNIOR = [
    "junior", "jr", "entry level", "entry-level", "nivel inicial",
    "associate", "asociado", "new grad", "recien egresado", "graduate",
    "early career", "level 1", "tier 1", "tier i", "l1",
    "principiante", "sin experiencia",
]
NIVEL_EXCLUIR = [
    "senior", "sr", "snr", "staff", "principal", "lead", "leader", "head of",
    "director", "vp", "vice president", "chief", "manager", "gerente",
    "architect", "arquitecto", "expert", "especialista senior",
    "distinguished", "fellow", "iii", "iv", "sme", "supervisor", "jefe",
    "coordinador", "coordinator",
]

# Dominios que usan las mismas palabras que la seguridad ("auditoria",
# "riesgo", "control interno") pero que NO son ciberseguridad. Si el título
# los nombra y no hay un término fuerte de seguridad, la vacante queda fuera.
NEGATIVO_DOMINIO = [
    "fiscal", "contable", "contabilidad", "impuestos", "actuari*",
    "nomina", "tesoreria", "cobranza", "credito", "crediticio",
    "seguros", "siniestros", "financiero", "financiera", "balances",
    "auditoria fiscal", "auditoria financiera", "calidad", "ambiental",
    "seguridad e higiene", "seguridad industrial", "seguridad patrimonial",
    "seguridad fisica", "guardia", "vigilancia",
]

# Roles no técnicos: siguen siendo visibles, pero no son el objetivo dentro de
# tecnologia (en `analisis.py` solo penalizan vacantes de ese area).
ROL_NO_TECNICO = [
    "comercial", "ventas", "sales", "account executive", "business development",
    "marketing", "reclutamiento", "recursos humanos", "atencion a clientes",
    "customer success", "preventa", "pre-sales",
]

# Palabras que definen el área.
# El sufijo '*' significa "coincide como prefijo": lo necesitan las palabras
# compuestas del español (ciberseguridad) y los plurales (riesgos, amenazas).
# Términos que POR SÍ SOLOS acreditan que la vacante es de ciberseguridad.
AREA_CIBER = [
    "security", "securit*", "cyber*", "ciber*", "infosec", "soc",
    "seguridad de la informacion", "seguridad informatica",
    "grc", "siem", "soar", "edr", "xdr", "dlp",
    "threat*", "amenaza*", "vulnerabilit*", "vulnerabilidad*",
    "pentest*", "penetration test*", "appsec", "malware", "ransomware",
    "phishing", "forensic*", "forense", "hardening", "ciso",
    "blue team", "red team", "purple team", "trust and safety",
    "iso 27001", "nist", "hacking", "ethical hack*", "owasp",
    "incident response", "respuesta a incidentes", "zero trust",
]

# Términos AMBIGUOS: existen igual en auditoría contable, riesgo financiero y
# cumplimiento legal. Solo cuentan como ciberseguridad si van acompañados de
# un término del contexto técnico de abajo.
# Sin esta separación, "Becario de Auditoria Fiscal" puntuaba 83/100.
AREA_CIBER_DEBIL = [
    "audit*", "auditor*", "risk*", "riesgo*", "compliance", "cumplimiento",
    "privacy", "privacidad", "fraud*", "identity", "iam", "control interno",
    "governance", "gobierno", "detection", "deteccion", "incident*",
]

# Contexto que convierte un término ambiguo en ciberseguridad de verdad.
CONTEXTO_TECNICO = [
    "ti", "it", "tecnologia*", "tecnologias", "sistemas", "informatica",
    "information technology", "cyber*", "ciber*", "security", "seguridad",
    "datos", "data", "digital", "software", "network", "redes", "red",
    "cloud", "nube", "infraestructura", "infrastructure", "sox", "itgc",
    "informacion", "aplicaciones", "applications", "devops", "sistemas de informacion",
]
AREA_IA = [
    # 'ai', 'ml' e 'ia' son seguros con límite de palabra: no casan dentro de
    # 'available' ni de 'tecnologia' porque ahí no hay frontera de palabra.
    "ai", "ml", "ia",
    "artificial intelligence", "inteligencia artificial",
    "machine learning", "aprendizaje automatico",
    "llm", "llms", "language model", "deep learning", "data scien*",
    "ciencia de datos", "nlp", "prompt*", "genai", "generative",
    "generativa", "annotation", "anotacion", "rlhf",
    "alignment", "alineacion", "evals", "neural", "chatbot",
    "computer vision", "vision artificial", "mlops",
]

# Señales de restricción geográfica que EXCLUYEN a alguien en México.
# Se buscan en la DESCRIPCIÓN, con límites de palabra.
BLOQUEO_GEO = [
    "us citizen", "u.s. citizen", "must be a us citizen",
    "security clearance", "ts/sci", "top secret", "public trust",
    "clearance required", "polygraph", "itar",
    "us only", "united states only", "usa only",
    "must reside in the united states", "must be located in the us",
    "must be based in the united states",
    "must live in the united states",
    "authorized to work in the united states",
    "eligible to work in the united states",
    "eu only", "europe only", "eea only", "uk only",
    "must be based in the uk", "right to work in the uk",
    "canada only", "must reside in canada",
    "india only", "australia only", "singapore only",
    "no visa sponsorship", "we do not sponsor", "unable to sponsor",
    "cannot provide sponsorship", "without sponsorship",
]

# Señales positivas de que alguien en México SÍ puede aplicar.
# Ojo: aquí NO van siglas cortas ambiguas como "mx", "est" o "cst":
# generaban falsos positivos al aparecer dentro de otras palabras.
APERTURA_GEO = [
    "worldwide", "anywhere", "work from anywhere", "any location",
    "any timezone", "fully distributed", "globally distributed",
    "latam", "latin america", "america latina", "latinoamerica",
    "mexico", "hire globally", "hiring globally", "anywhere in the world",
]

# --- Ubicación: patrones aplicados al CAMPO de ubicación (regex) ------------
# Este campo es la señal más fiable: "Remote - USA" es un remoto cerrado,
# aunque la descripción hable de un equipo global.

# Estados de EEUU: aparecen en ubicaciones como "Remote - Virginia, USA",
# que es un remoto cerrado aunque no diga "USA" pegado a "Remote".
ESTADOS_EEUU = (
    r"alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware"
    r"|florida|georgia|hawaii|idaho|illinois|indiana|iowa|kansas|kentucky"
    r"|louisiana|maine|maryland|massachusetts|michigan|minnesota|mississippi"
    r"|missouri|montana|nebraska|nevada|new\s+hampshire|new\s+jersey"
    r"|new\s+mexico|new\s+york|north\s+carolina|north\s+dakota|ohio|oklahoma"
    r"|oregon|pennsylvania|rhode\s+island|south\s+carolina|south\s+dakota"
    r"|tennessee|texas|utah|vermont|virginia|washington|wisconsin|wyoming"
)

PAISES_CERRADOS = (
    r"us\b|usa|u\.?s\.?a?\b|united\s+states|america\b|canada|uk\b"
    r"|united\s+kingdom|england|scotland|europe|emea|eea|eu\b|ireland"
    r"|germany|deutschland|france|spain|espana|portugal|poland|romania"
    r"|netherlands|belgium|switzerland|austria|sweden|norway|denmark|finland"
    r"|israel|india|pakistan|australia|new\s+zealand|anz\b|apac|japan|china"
    r"|korea|singapore|philippines|vietnam|indonesia|malaysia|thailand"
    r"|nigeria|kenya|egypt|south\s+africa|ghana|brazil|brasil|argentina"
)

# Remoto pero restringido a una región donde no se puede trabajar desde México.
UBIC_REMOTO_CERRADO = rf"""(?x)
    \b remote \s* [-–—(,/|]* \s* ({PAISES_CERRADOS}|{ESTADOS_EEUU})
  | \b ({PAISES_CERRADOS}) \s* [-–—(,/|]* \s* remote \b
  | \b remote \s* \( \s* ({PAISES_CERRADOS}|{ESTADOS_EEUU}) \s* \)
  | \b remote [-\s] friendly ,? \s* ({PAISES_CERRADOS})
  | \b remote \b [^|]{{0,28}}? \b ({ESTADOS_EEUU}) \s*,? \s* (usa|us\b|united\s+states)
  | \b (federal|skillbridge|govcloud|public\s+sector\s+us) \b
"""

# Remoto genuinamente abierto. Se evalúa SOLO sobre el campo de ubicación.
# 'north america' entra aquí porque México pertenece a Norteamérica, pero el
# sistema lo marca como "confirmar al postular": muchas empresas lo usan para
# decir "EEUU y Canadá".
UBIC_REMOTO_ABIERTO = r"""(?x)
    \b(worldwide|anywhere|globally|fully\s+distributed|globally\s+distributed)\b
  | \bremote\s*[-–—(,/|]*\s*(global|worldwide|anywhere|international)\b
  | \b(latam|latin\s+america|america\s+latina|latinoamerica|americas
      |north\s+america|norteamerica)\b
  | \bmexico\b | \bméxico\b | \bmexican\b
"""

# Ubicación que no aporta información de país: hay que mirar la descripción.
UBIC_GENERICA = r"""(?x)
    ^\s*(remote|remoto|remota|work\s+from\s+home|teletrabajo|distributed
      |virtual|home\s*-?\s*based|flexible|varios|multiple\s+locations|)\s*$
"""

# Ciudades/países donde una vacante presencial exigiría visa: no viable.
UBIC_EXTRANJERA = r"""(?x)
    \b(san\s+francisco|new\s+york|nyc\b|seattle|austin|boston|chicago|denver
    |los\s+angeles|washington|atlanta|dallas|houston|miami|toronto|vancouver
    |london|dublin|berlin|munich|paris|madrid|barcelona|amsterdam|zurich
    |stockholm|warsaw|krakow|lisbon|tel\s+aviv|bangalore|bengaluru|hyderabad
    |mumbai|delhi|pune|singapore|tokyo|sydney|melbourne|sao\s+paulo|são\s+paulo
    |buenos\s+aires|bogota|bogotá|lima|santiago|montevideo|san\s+jose,\s*costa)
"""

# Estados de México fuera del área metropolitana de Monterrey: presencial ahí
# implica mudarse, así que se marca aparte en vez de descartarse.
UBIC_MX_OTRA = r"""(?x)
    \b(ciudad\s+de\s+m|cdmx|distrito\s+federal|jalisco|guadalajara|queretaro
    |querétaro|puebla|tijuana|baja\s+california|chihuahua|sonora|hermosillo
    |aguascalientes|san\s+luis|merida|mérida|yucatan|cancun|veracruz|toluca
    |estado\s+de\s+m|leon,\s*guanajuato|guanajuato|saltillo|coahuila|torreon
    |tamaulipas|reynosa|matamoros|benito\s+juarez|cuauhtemoc|miguel\s+hidalgo
    |naucalpan|tlalnepantla|zapopan|tlaquepaque)
"""


# Logros con numeros verificables, la unica moneda que vale sin experiencia
# formal. Es lo UNICO que el generador de correos y los correos en frio pueden
# afirmar: un dato inventado en un correo quema la candidatura con esa empresa.
# Claves: las areas de `areas.AREAS` y "general". Formato:
#     LOGROS = {
#         "general": ["organice el inventario de 300 articulos y lo pase a Excel"],
#         "contabilidad-finanzas": ["concilie 12 cuentas bancarias al mes durante 6 meses"],
#     }
LOGROS: dict[str, list[str]] = {"general": []}

# Los mismos logros en ingles, para los correos a empresas que trabajan en
# ingles. No se traducen solos: lo que no este aqui no se escribe.
LOGROS_EN: dict[str, list[str]] = {"general": []}


# ---------------------------------------------------------------------------
# Certificaciones. La division no es decorativa: `pendientes` existe para que
# nada las nombre como obtenidas. Presentar como conseguido un examen agendado
# y no presentado es exactamente el dato falso que quema una candidatura.
# Formato: ("Nombre de la certificacion (emisor)", "clave de area") y, en
# pendientes, ("Nombre", "estado honesto: en preparacion, examen agendado...").
CERTIFICACIONES: dict[str, list[tuple[str, str]]] = {
    "obtenidas": [],
    # Nombrarlas SIEMPRE con su estado. Nunca a secas.
    "pendientes": [],
}


def certificaciones_de(area: str) -> list[str]:
    """Las certificaciones OBTENIDAS de un area. Nunca devuelve pendientes."""
    return [n for n, a in CERTIFICACIONES["obtenidas"] if a == area]


# ---------------------------------------------------------------------------
# Formacion. Lo que el perfil YA cubre (un curso que solo repite esto baja de
# puesto) y los huecos que quiere cerrar, cada uno con sus palabras clave.
# Formato:
#     CURSOS_YA_CUBIERTO = ["excel", "contabilidad basica"]
#     CURSOS_BRECHAS = {"sap": ["sap", "erp"], "ingles": ["ingles", "english"]}
CURSOS_YA_CUBIERTO: list[str] = []
CURSOS_BRECHAS: dict[str, list[str]] = {}


# ---------------------------------------------------------------------------
# Respuestas al formulario de una bolsa (OCC, Indeed, Computrabajo).
#
# Estos portales no piden una carta: piden campos. Y siempre los mismos. Si el
# sistema no los tiene, la postulacion se para a mitad, que es justo la
# friccion que hace que no se postule.
#
# Los que valen None NO SE INVENTAN. `postular.py` se niega a rellenar un campo
# vacio y lo saca por pantalla para que lo decida la persona. Ademas, los
# descartes que dependen del perfil (semestre, titulo, carta de la facultad,
# practicas obligatorias) solo se aplican cuando el campo esta declarado: un
# perfil sin rellenar no descarta nada.
POSTULACION = {
    "nombre": CANDIDATO["nombre"],
    "correo": CANDIDATO["correo"],
    "telefono": CANDIDATO["telefono"],
    "ciudad": None,
    "colonia": None,
    "pais": "Mexico",
    "nivel_estudios": None,          # p. ej. "Licenciatura en curso"
    "semestre": None,                # entero; se compara con el que exige el anuncio
    "carrera": None,                 # p. ej. "Contaduria Publica"
    "universidad": None,
    "titulado": None,                # True / False
    "ingles": CANDIDATO["ingles"],
    "anios_experiencia": None,
    "meses_experiencia": None,
    "experiencia_texto": None,
    "linkedin": CANDIDATO["linkedin"],
    "github": CANDIDATO["github"],
    "requiere_visa_para_mexico": False,
    "disponibilidad_mudanza": None,  # True / False
    "salario_esperado_mxn": None,
    "salario_texto": None,
    "disponibilidad_horaria": None,
    "fecha_inicio": None,
    # False = no tienes carta ni convenio de la facultad: se descartan las
    # vacantes que la exigen. None = no se descarta nada por esto.
    "carta_de_la_universidad": None,
    # False = no necesitas liberar practicas obligatorias: se descartan los
    # anuncios "postulate SOLO si requieres realizar practicas".
    "requiere_practicas_obligatorias": None,
    # True = tu institucion es publica. Algunas convocatorias solo admiten
    # estudiantes de instituciones publicas; con None quedan "por confirmar".
    "institucion_publica": None,
    "contexto_practicas": None,
}


def huecos_de_postulacion() -> list[str]:
    """Campos que faltan para poder postular sin inventar nada."""
    return [k for k, v in POSTULACION.items() if v is None]


# Niveles que piden los formularios de OCC ("Completa el nivel de
# conocimientos para postularte"). Escala de la bolsa: ninguno, basico, medio,
# avanzado, experto.
#
# Se guardan porque la pregunta se repite en CADA vacante. Y se guardan CON su
# justificacion, porque en una entrevista hay que sostener lo que se declaro:
# decir "medio" en algo que no se puede defender quema la candidatura mas
# rapido que decir "basico". Formato:
#     COMPETENCIAS = {"excel": ("medio", "tablas dinamicas y BUSCARV a diario"),
#                     "sap": ("basico", "modulo FI en practicas escolares")}
COMPETENCIAS: dict[str, tuple[str, str]] = {}


def nivel_de(competencia: str) -> tuple[str, str]:
    """Nivel declarable y su justificacion. ('ninguno', ...) si no consta."""
    from nucleo import sin_acentos
    clave = sin_acentos((competencia or "").lower()).strip()
    for k, v in COMPETENCIAS.items():
        if k in clave or clave in k:
            return v
    return ("ninguno", "no consta en perfil.py; no se inventa")
