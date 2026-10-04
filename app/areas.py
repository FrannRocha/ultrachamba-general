"""
Areas profesionales y zona base: el UNICO punto de configuracion de QUE se
busca y DONDE.

POR QUE EXISTE. El proyecto de origen buscaba solo ciberseguridad e IA, y esa
decision no vivia en un sitio: estaba repartida entre las consultas de cada
bolsa, el prefiltro del orquestador, el veto del clasificador, las areas
prioritarias de la cola, los filtros SQL de salud y de verificacion y los pesos
de los cursos. Cambiar solo las busquedas habria dado una interfaz que parece
funcionar y no funciona: el clasificador descartaba A PROPOSITO finanzas,
negocio, personas u operaciones. Aqui cada area declara todo lo que la define,
y los colectores Y el clasificador leen de aqui.

QUE DECLARA CADA AREA
  etiqueta        como se ve en el panel.
  valores         valores de `vacantes.area` que produce el clasificador, cada
                  uno con su etiqueta, su peso en la puntuacion y si es
                  prioritario (entra en la cola diaria y en los controles).
  consultas       frases para las bolsas que aceptan texto libre (LinkedIn,
                  OCC, Computrabajo e Indeed).
  amplias         terminos sueltos: en OCC traen mucho mas volumen.
  titulo          terminos que, en el TITULO, nombran el oficio (dominio.py).
  titulo_ambiguo  terminos que solo cuentan si nada mas decide (opcional).
  cursos          etiquetas de `cursos.area` que le sirven, con su peso.
  carreras        como nombran las convocatorias a las carreras afines.
  terminos_curso  palabras que hacen que un curso sea "del area".
  herramientas    lo que, en los anuncios de una empresa, delata que tiene
                  operacion real de esa area (empresas.py).
  remotive/jobicy categorias de esos tablones remotos. Solo se anotan las
                  comprobadas con una peticion real.

Tecnologia es especial a proposito: su clasificacion la hace el clasificador
especializado de `dominio.py`, que ya existia y tiene pruebas, y sus consultas
son las listas de cada bolsa del proyecto de origen, copiadas tal cual.

LA SELECCION no se escribe aqui: viene de `ULTRACHAMBA_AREAS` y
`ULTRACHAMBA_ZONA` (ver `config.py` y `.env.example`).

Terminos en minusculas y SIN acentos: se comparan contra texto normalizado. El
sufijo `*` significa prefijo, igual que en `nucleo.tiene_termino`.
"""
from __future__ import annotations

import re
from functools import lru_cache

import config
from nucleo import _patron, normalizar, terminos_presentes

# Marcador de "la ubicacion de la zona base" en las busquedas de LinkedIn.
ZONA = "ZONA"

# Profundidad de LinkedIn: las listas de origen usan 10 paginas (250 tarjetas);
# las generadas para otras areas usan 5 para no disparar su limitador de tasa.
PAGINAS_LINKEDIN = 10
PAGINAS_LINKEDIN_GENERADAS = 5

PESO_FUERA = -20

# ---------------------------------------------------------------------------
# Lo comun a todas las areas. Las practicas se anuncian con estas palabras en
# cualquier carrera; el clasificador decide despues de que area es cada una.
# ---------------------------------------------------------------------------
COMUNES = {
    "linkedin": [
        ("becario", ZONA, "&f_E=1"),
        ("practicante", ZONA, "&f_E=1"),
        ("intern", ZONA, "&f_E=1"),
        # 'trainee' es la palabra mas frecuente en los titulos de practicas y
        # durante un tiempo fue la unica de las tres que no se buscaba.
        ("trainee", ZONA, "&f_E=1"),
    ],
    # Terminos sueltos para OCC: rinden entre 4 y 16 veces mas que una frase,
    # porque OCC trata las frases con guion como un Y logico.
    "amplias": ["practicante", "becario", "trainee"],
    # Categorias generalistas de los tablones remotos.
    "remotive": ["all-others", "product", "design"],
    "jobicy": ["business"],
}

# Prefiltro barato de titulos comun a todas las areas (nivel de entrada).
PREFILTRO_COMUN = r"intern|becari|practicant|trainee|junior|entry|graduate|aprendiz"

# ---------------------------------------------------------------------------
# TECNOLOGIA: listas del proyecto de origen, sin tocar salvo que la ubicacion
# de la zona base se escribe como ZONA.
# ---------------------------------------------------------------------------
TECNOLOGIA = {
    "etiqueta": "Tecnologia: TI, ciberseguridad, IA y datos",
    "valores": {
        "ciber-ia": {"etiqueta": "Seguridad de IA", "peso": 25, "prioritaria": True},
        "ciberseguridad": {"etiqueta": "Ciberseguridad", "peso": 23, "prioritaria": True},
        "ia": {"etiqueta": "Inteligencia Artificial", "peso": 19, "prioritaria": True},
        # TI general queda fuera de la cola por defecto: es la puerta de
        # entrada, no el objetivo. Se cambia aqui si se quiere lo contrario.
        "ti-general": {"etiqueta": "TI general", "peso": 9, "prioritaria": False},
    },
    "linkedin": [
        ("ciberseguridad", ZONA, "&f_E=1%2C2"),
        ("seguridad informatica", ZONA, "&f_E=1%2C2"),
        ("practicante sistemas", ZONA, ""),
        ("becario tecnologia", ZONA, ""),
        ("cybersecurity", ZONA, "&f_E=1%2C2"),
        ("SOC analyst", ZONA, "&f_E=1%2C2"),
        ("inteligencia artificial", ZONA, "&f_E=1%2C2"),
        ("data science", ZONA, "&f_E=1%2C2"),
        ("riesgos tecnologia", ZONA, "&f_E=1%2C2"),
        ("auditoria de sistemas", ZONA, "&f_E=1%2C2"),
        ("ciberseguridad", "Mexico", "&f_E=1%2C2&f_WT=2"),
        ("cybersecurity intern", "Mexico", "&f_WT=2"),
        ("GRC analyst", "Mexico", "&f_E=1%2C2"),
        ("seguridad de la informacion", "Mexico", "&f_E=1%2C2"),
        ("AI safety", "Mexico", "&f_WT=2"),
        ("cybersecurity internship", "Latin America", "&f_WT=2"),
        ("security analyst latam", "Worldwide", "&f_WT=2&f_E=1%2C2"),
        ("AI red team", "Worldwide", "&f_WT=2"),
        ("trust and safety", "Latin America", "&f_WT=2&f_E=1%2C2"),
        ("prompt engineer", "Latin America", "&f_WT=2"),
        ("security intern remote", "Worldwide", "&f_WT=2&f_E=1%2C2"),
        ("soporte tecnico", ZONA, "&f_E=1%2C2"),
        ("infraestructura TI", ZONA, "&f_E=1%2C2"),
        ("analista de datos", ZONA, "&f_E=1%2C2"),
        ("SOC", ZONA, ""),
        ("SIEM", "Mexico", "&f_E=1%2C2"),
        ("ISO 27001", "Mexico", "&f_E=1%2C2"),
        ("auditoria de sistemas", "Mexico", "&f_E=1%2C2"),
        ("cumplimiento normativo TI", "Mexico", "&f_E=1%2C2"),
        ("identity access management", "Mexico", "&f_E=1%2C2"),
        ("incident response", "Mexico", "&f_E=1%2C2"),
        ("vulnerability management", "Mexico", "&f_E=1%2C2"),
        ("becario ciberseguridad", "Mexico", ""),
        ("practicante ciberseguridad", "Mexico", ""),
        ("trainee ciberseguridad", "Mexico", ""),
        ("trainee tecnologia", "Mexico", "&f_E=1"),
        ("cybersecurity analyst", "Mexico", "&f_E=1%2C2"),
        ("information security", "Mexico", "&f_E=1%2C2"),
        ("data analyst", "Mexico", "&f_E=1%2C2&f_WT=2"),
        ("machine learning", "Mexico", "&f_E=1%2C2&f_WT=2"),
        ("security engineer", "Latin America", "&f_WT=2&f_E=1%2C2"),
        ("SOC analyst", "Latin America", "&f_WT=2&f_E=1%2C2"),
        ("GRC", "Latin America", "&f_WT=2"),
        ("compliance analyst", "Latin America", "&f_WT=2&f_E=1%2C2"),
        ("data annotation", "Worldwide", "&f_WT=2"),
        ("AI evaluator", "Worldwide", "&f_WT=2"),
        ("red teaming AI", "Worldwide", "&f_WT=2"),
        ("LLM security", "Worldwide", "&f_WT=2"),
        ("junior security", "Worldwide", "&f_WT=2&f_E=1%2C2"),
        ("entry level cybersecurity", "Worldwide", "&f_WT=2&f_E=1%2C2"),
    ],
    # OCC y Computrabajo: como se nombran estos puestos en Mexico, incluidas
    # las variantes que no llevan la palabra "ciberseguridad".
    "occ_consultas": [
        "practicante-ciberseguridad", "becario-ciberseguridad",
        "practicante-seguridad-informatica", "becario-seguridad-informatica",
        "practicante-seguridad-de-la-informacion", "analista-ciberseguridad-junior",
        "analista-soc", "analista-seguridad-junior", "practicante-ti",
        "practicante-sistemas", "becario-ti", "practicante-inteligencia-artificial",
        "becario-inteligencia-artificial", "practicante-ciencia-de-datos",
        "becario-datos", "practicante-infraestructura", "trainee-ciberseguridad",
        "practicante-riesgos", "practicante-auditoria-ti", "analista-grc",
        "practicante-redes", "junior-cybersecurity", "residencia-profesional-ti",
        "becario-sistemas", "becario-informatica", "practicante-informatica",
        "practicante-soporte-tecnico", "becario-soporte-tecnico",
        "practicante-desarrollo", "becario-desarrollo-de-software",
        "analista-de-seguridad", "especialista-en-ciberseguridad",
        "ingeniero-de-ciberseguridad", "consultor-de-ciberseguridad",
        "analista-de-riesgos-ti", "auditor-de-sistemas", "auditor-ti",
        "analista-de-cumplimiento", "oficial-de-seguridad-de-la-informacion",
        "administrador-de-seguridad", "seguridad-perimetral",
        "analista-de-vulnerabilidades", "pentester", "hacking-etico",
        "analista-de-monitoreo", "monitoreo-de-seguridad", "noc",
        "practicante-de-datos", "analista-de-datos-junior", "cientifico-de-datos",
        "ingeniero-de-datos-junior", "machine-learning", "aprendizaje-automatico",
        "becario-automatizacion", "practicante-automatizacion",
        "becario-transformacion-digital", "practicante-innovacion",
        "trainee-ti", "trainee-sistemas", "graduate-program-ti",
        "practicante-infraestructura-ti", "becario-redes-y-telecomunicaciones",
        "practicante-cloud", "becario-cloud", "practicante-devops",
        "analista-de-identidades", "administrador-de-active-directory",
        "practicante-gobierno-de-datos", "becario-calidad-de-software",
        "analista-de-fraude", "prevencion-de-fraude", "analista-siem",
        "operador-soc", "analista-soc-n1", "mesa-de-servicio",
    ],
    "amplias": [
        "ciberseguridad", "seguridad-informatica", "inteligencia-artificial",
        "ciencia-de-datos", "soporte-tecnico", "sistemas", "redes",
    ],
    # Indeed filtra las frases largas en Y y se queda sin resultados: por eso
    # son deliberadamente amplias y el cribado fino lo hace `analisis.py`.
    "indeed": [
        "ciberseguridad", "seguridad informatica", "seguridad de la informacion",
        "practicante ciberseguridad", "becario ciberseguridad",
        "analista de seguridad", "analista SOC", "analista de vulnerabilidades",
        "pentester", "hacking etico", "analista SIEM", "monitoreo de seguridad",
        "auditor de sistemas", "auditoria de TI", "analista de riesgos TI",
        "GRC ciberseguridad",
        "practicante sistemas", "practicante TI", "becario sistemas", "becario TI",
        "practicante informatica", "practicante redes", "practicante infraestructura",
        "becario soporte tecnico", "trainee TI", "residencia profesional sistemas",
        "mesa de servicio junior",
        "inteligencia artificial", "practicante inteligencia artificial",
        "machine learning junior", "analista de datos junior",
        "practicante ciencia de datos", "becario datos",
        "practicante cloud", "administrador de active directory",
        "analista de identidades", "devops junior",
    ],
    # El prefiltro de titulos del orquestador de origen.
    "prefiltro": (
        r"secur|segurid|cyber|ciber|infosec|soc\b|siem|grc|risk|riesgo|audit|"
        r"complian|cumplimient|privacy|privacid|fraud|threat|amenaza|vulnerab|"
        r"pentest|malware|forens|hacking|hardening|identity|iam\b|"
        r"\bai\b|\bia\b|artificial|machine learning|\bml\b|llm|nlp|deep learning|"
        r"data scien|ciencia de datos|analytic|analitic|datos|data\b|prompt|model|"
        r"\bit\b|\bti\b|sistemas|informatic|tecnolog|infraestructura|infrastructure|"
        r"network|redes|cloud|nube|devops|soporte|help ?desk|mesa de ayuda"
    ),
    "remotive": ["software-dev", "devops", "data", "qa"],
    "jobicy": ["security", "engineering", "data-science", "devops", "it"],
    # Pesos de las etiquetas de curso del catalogo de origen.
    "cursos": {"nube": 30, "ia": 22, "ciberseguridad": 20, "redes": 14, "general": 6},
    "carreras": [
        "ciberseguridad", "seguridad informatica", "sistemas computacionales",
        "ciencias computacionales", "ingenieria en computacion", "informatica",
        "tecnologias de la informacion", "tecnologias computacionales",
        "ingenieria de software", "desarrollo de software", "ciencia de datos",
        "inteligencia artificial", "telecomunicaciones", "redes y telecomunicaciones",
        "electronica y comunicaciones", "matematicas aplicadas",
        "afin a las tic", "ingenierias", "stem", "computer science",
        "information technology", "engineering",
    ],
    "terminos_curso": [
        "ciberseguridad", "seguridad informatica", "seguridad de la informacion",
        "cybersecurity", "hacking", "pentest*", "soc", "siem",
        "inteligencia artificial", "artificial intelligence", "machine learning",
        "ciencia de datos", "data", "datos", "software", "programacion",
        "computo", "computacion", "computing", "informatica", "sistemas",
        "redes", "networking", "nube", "cloud", "devops", "python",
        "tecnologias de la informacion", "tic", "digital", "ingenieria",
        "telecomunicaciones", "criptograf*", "blockchain",
    ],
    "herramientas": [
        "siem", "splunk", "sentinel", "qradar", "soc", "edr", "crowdstrike",
        "firewall", "fortinet", "palo alto", "checkpoint", "cyberark", "okta",
        "iso 27001", "nist", "pentest*", "vulnerabilit*", "aws", "azure", "gcp",
        "kubernetes", "docker", "terraform", "python", "sql", "power bi",
        "machine learning", "tensorflow", "pytorch", "llm", "active directory",
    ],
}

# ---------------------------------------------------------------------------
# LAS DEMAS AREAS. Los terminos de `titulo` salen del veto de rubro ajeno del
# clasificador de origen (depurado con falsos positivos reales), repartido por
# oficio, mas unos pocos terminos anadidos que se marcan como tales.
# ---------------------------------------------------------------------------
CONTABILIDAD_FINANZAS = {
    "etiqueta": "Contabilidad y finanzas",
    "valores": {"contabilidad-finanzas": {
        "etiqueta": "Contabilidad y finanzas", "peso": 23, "prioritaria": True}},
    "consultas": [
        "practicante contabilidad", "becario contabilidad", "auxiliar contable",
        "contador junior", "practicante finanzas", "becario finanzas",
        "analista financiero junior", "auxiliar de nominas",
        "auxiliar de cuentas por pagar", "practicante auditoria",
    ],
    "amplias": ["contabilidad", "finanzas", "contador"],
    "titulo": [
        "fiscal", "contable*", "contabilidad", "contadur*", "impuestos", "tax",
        "actuari*", "actuarial", "seguros", "insurance", "siniestros", "claims",
        "nomina*", "payroll", "tesoreria", "treasury", "cobranza", "collections",
        "credito", "crediticio", "credit", "financier*", "finanzas",
        "financial", "finance", "balances", "facturacion", "accounting", "accountant*",
        "hipotecas", "hipotecario", "mortgage", "underwriter", "underwriting",
        "prestamos", "lending", "banca patrimonial", "inversiones", "trading",
        "rentabilidad", "costos", "presupuesto*", "utilidades", "margenes",
        "cuentas por pagar", "cuentas por cobrar", "conciliacion*",
        # anadidos para esta version
        "contador*", "auditoria financiera", "auditoria fiscal", "auditor financiero",
        # vistos en la corrida real de validacion (13-sep-2026): se quedaban fuera
        "controlling",
    ],
    # "Auditor Interno" o "Analista de Riesgos" sin nada de TI en el titulo son,
    # casi siempre, auditoria o riesgo financiero. Solo deciden si nada mas lo
    # hace, y con confianza baja.
    "titulo_ambiguo": [
        "auditoria", "auditor*", "audit", "auditing", "riesgo*", "risk",
        "control interno", "internal control", "fraude*", "fraud",
        "cumplimiento", "compliance", "regulatorio", "normativ*",
    ],
    "cursos": {"general": 20},
    "carreras": [
        "contaduria", "contador publico", "contabilidad", "finanzas", "economia",
        "actuaria", "administracion financiera", "ciencias economicas",
    ],
    "terminos_curso": [
        "contabilidad", "contable", "finanzas", "financiera", "impuestos", "fiscal",
        "auditoria", "nomina", "economia", "actuaria", "contadur*",
    ],
    "herramientas": [
        "sap", "contpaqi", "aspel", "excel", "power bi", "nif", "ifrs", "cfdi",
        "quickbooks", "netsuite",
    ],
}

ADMINISTRACION = {
    "etiqueta": "Administracion",
    "valores": {"administracion": {
        "etiqueta": "Administracion", "peso": 23, "prioritaria": True}},
    "consultas": [
        "practicante administracion", "becario administracion",
        "auxiliar administrativo", "asistente administrativo",
        "practicante compras", "auxiliar de compras",
        "practicante administracion de empresas",
    ],
    "amplias": ["administracion", "administrativo"],
    "titulo": [
        "practicante de administracion", "becario de administracion",
        "auxiliar administrativo", "administrativo", "administrativa",
        "compras", "abastecimiento",
        # anadidos para esta version
        "becaria de administracion", "auxiliar administrativa", "administrativos",
        "asistente administrativo", "asistente administrativa",
        "administracion de empresas", "gestion administrativa",
        "asistente de direccion", "back office", "comprador*", "procurement",
        "purchasing", "office manager", "administrative assistant",
    ],
    "cursos": {"general": 20},
    "carreras": [
        "administracion", "administracion de empresas", "negocios",
        "negocios internacionales", "gestion empresarial", "comercio",
    ],
    "terminos_curso": [
        "administracion", "negocios", "gestion", "emprendimiento", "liderazgo",
        "proyectos", "project management",
    ],
    "herramientas": ["sap", "excel", "erp", "power bi", "salesforce", "odoo"],
}

MERCADOTECNIA_VENTAS = {
    "etiqueta": "Mercadotecnia y ventas",
    "valores": {"mercadotecnia-ventas": {
        "etiqueta": "Mercadotecnia y ventas", "peso": 23, "prioritaria": True}},
    "consultas": [
        "practicante mercadotecnia", "becario marketing",
        "practicante marketing digital", "community manager",
        "practicante comercial", "ejecutivo de ventas junior",
        "trade marketing", "practicante publicidad",
    ],
    "amplias": ["mercadotecnia", "marketing", "ventas"],
    "titulo": [
        "ventas", "sales", "comercial", "account executive", "account manager",
        "ejecutivo de cuenta", "business development", "desarrollo de negocio",
        "preventa", "pre-sales", "customer success", "marketing", "mercadotecnia",
        "influencer", "redes sociales", "social media", "community manager",
        "publicidad", "branding", "ecommerce", "pricing",
        "promociones", "mercancia*",
        # anadidos para esta version
        "vendedor*", "e-commerce", "comercio electronico", "relaciones publicas",
        "merchandising", "copywriter*",
    ],
    "cursos": {"general": 20},
    "carreras": [
        "mercadotecnia", "marketing", "comunicacion", "publicidad",
        "relaciones publicas", "negocios", "comercio internacional",
    ],
    "terminos_curso": [
        "marketing", "mercadotecnia", "ventas", "publicidad", "redes sociales",
        "comercio electronico", "e-commerce", "seo", "branding", "marketing digital",
    ],
    "herramientas": [
        "google ads", "meta ads", "hubspot", "salesforce", "google analytics",
        "seo", "canva", "crm", "power bi",
    ],
}

RECURSOS_HUMANOS = {
    "etiqueta": "Recursos humanos",
    "valores": {"recursos-humanos": {
        "etiqueta": "Recursos humanos", "peso": 23, "prioritaria": True}},
    "consultas": [
        "practicante recursos humanos", "becario recursos humanos",
        "auxiliar de recursos humanos", "practicante reclutamiento",
        "reclutador junior", "practicante capacitacion",
    ],
    "amplias": ["recursos humanos", "reclutamiento"],
    "titulo": [
        "reclutamiento", "reclutador*", "recruiter", "recruiting", "recruitment",
        "recursos humanos", "human resources", "capital humano",
        "talent acquisition", "atraccion de talento", "integracion de talento",
        "capacitacion", "capacitador*", "entrenador*", "instructor*", "trainer",
        # anadidos para esta version
        "rh", "rrhh", "talento humano", "desarrollo organizacional",
        "relaciones laborales", "hrbp",
        # vistos en la corrida real de validacion (13-sep-2026): los titulos en
        # ingles abrevian "HR" y se quedaban fuera. Van en frases y no "hr" a
        # secas, para no reclasificar puestos que solo lo mencionan.
        "hr intern", "hr internship", "hr apprentice", "hr trainee", "general hr",
        "hr generalist", "hr assistant", "hr coordinator", "hr business partner",
        "talent intern", "people and culture",
    ],
    "cursos": {"general": 20},
    "carreras": [
        "recursos humanos", "psicologia", "psicologia organizacional",
        "relaciones industriales",
    ],
    "terminos_curso": [
        "recursos humanos", "reclutamiento", "talento", "capacitacion",
        "psicolog*", "desarrollo organizacional", "liderazgo",
    ],
    "herramientas": ["successfactors", "workday", "nomina", "imss", "excel", "power bi"],
}

DERECHO = {
    "etiqueta": "Derecho",
    "valores": {"derecho": {"etiqueta": "Derecho", "peso": 23, "prioritaria": True}},
    "consultas": [
        "practicante derecho", "pasante de derecho", "becario juridico",
        "auxiliar juridico", "abogado junior", "paralegal",
    ],
    "amplias": ["derecho", "abogado"],
    "titulo": [
        "legal", "juridic*", "counsel", "abogad*", "notarial",
        # anadidos para esta version
        "notaria", "derecho", "litigio*", "litigante", "paralegal", "contencioso",
        "propiedad intelectual",
    ],
    "cursos": {"general": 20},
    "carreras": ["derecho", "ciencias juridicas", "criminologia"],
    "terminos_curso": [
        "derecho", "juridic*", "legal", "leyes", "litigio", "notarial",
        "propiedad intelectual",
    ],
    "herramientas": ["litigio", "contratos", "compliance", "propiedad intelectual", "amparo"],
}

INGENIERIA_INDUSTRIAL = {
    "etiqueta": "Ingenieria industrial y operaciones",
    "valores": {"ingenieria-industrial": {
        "etiqueta": "Ingenieria industrial y operaciones", "peso": 23, "prioritaria": True}},
    "consultas": [
        "practicante ingenieria industrial", "becario produccion",
        "practicante calidad", "practicante logistica",
        "practicante cadena de suministro", "practicante mejora continua",
        "practicante seguridad e higiene", "ingeniero industrial junior",
    ],
    "amplias": ["ingeniero industrial", "logistica", "produccion"],
    "titulo": [
        "logistic*", "manufacturing", "logistica", "almacen", "inventarios",
        "produccion", "manufactura", "planta", "calidad", "ambiental",
        "electromecanic*", "automotriz", "mantenimiento industrial",
        # del veto de "otras seguridades": en Mexico son puestos de EHS
        "seguridad industrial", "seguridad e higiene", "higiene y seguridad",
        "proteccion civil", "seguridad alimentaria",
        # anadidos para esta version
        "cadena de suministro", "supply chain", "mejora continua",
        "lean manufacturing", "six sigma", "seis sigma", "ingenieria industrial",
        "ingeniero industrial", "ingeniera industrial", "embarques", "ehs",
    ],
    "cursos": {"general": 20},
    "carreras": [
        "ingenieria industrial", "ingenieria mecanica", "mecatronica",
        "ingenieria en manufactura", "logistica", "ingenierias", "stem", "engineering",
    ],
    "terminos_curso": [
        "industrial", "manufactura", "calidad", "logistica", "lean", "six sigma",
        "seis sigma", "cadena de suministro", "produccion", "seguridad industrial",
        "mantenimiento",
    ],
    "herramientas": [
        "sap", "lean", "six sigma", "kaizen", "autocad", "minitab", "iso 9001",
        "iatf 16949", "mrp",
    ],
}

SALUD = {
    "etiqueta": "Salud",
    "valores": {"salud": {"etiqueta": "Salud", "peso": 23, "prioritaria": True}},
    "consultas": [
        "enfermera", "enfermero", "auxiliar de enfermeria", "pasante de enfermeria",
        "medico general", "quimico farmacobiologo", "nutriologo",
    ],
    "amplias": ["enfermeria", "medico"],
    "titulo": [
        "enfermeria", "medico", "clinico", "nurse*", "nursing", "clinical",
        "medicare", "medicaid", "paciente*", "farmac*",
        # del veto de "otras seguridades"
        "seguridad del paciente",
        # anadidos para esta version
        "enfermer*", "medica", "medicina", "clinica", "hospital*", "odontolog*",
        "nutriolog*", "nutricion", "fisioterap*", "quimico farmacobiologo",
        "laboratorista",
    ],
    "cursos": {"general": 20},
    "carreras": [
        "medicina", "enfermeria", "nutricion", "quimico farmacobiologo",
        "odontologia", "fisioterapia", "ciencias de la salud",
    ],
    "terminos_curso": [
        "salud", "enfermeria", "medic*", "clinic*", "nutricion", "farmac*",
        "paciente", "hospital", "odontolog*",
    ],
    "herramientas": ["expediente clinico", "cofepris", "farmacovigilancia"],
}

AREAS = {
    "tecnologia": TECNOLOGIA,
    "contabilidad-finanzas": CONTABILIDAD_FINANZAS,
    "administracion": ADMINISTRACION,
    "mercadotecnia-ventas": MERCADOTECNIA_VENTAS,
    "recursos-humanos": RECURSOS_HUMANOS,
    "derecho": DERECHO,
    "ingenieria-industrial": INGENIERIA_INDUSTRIAL,
    "salud": SALUD,
}

# Oficios que no son ninguna de las areas ofrecidas: siempre "fuera". Salen
# del mismo veto de origen (seguridad fisica, atencion telefonica, oficios de
# planta sin carrera) mas docencia y construccion, que esta version no ofrece.
OFICIOS_SIN_AREA = [
    "seguridad patrimonial", "seguridad fisica", "physical security",
    "seguridad privada", "vigilancia", "guardia de seguridad", "custodio",
    "security guard", "armed security", "unarmed security", "event security",
    "security patrol", "patrol officer", "crowd control",
    "bodyguard", "gate guard", "flex officer", "escolta", "guard card",
    "atencion a clientes", "atencion al cliente", "call center", "callcenter",
    "servicio al cliente", "customer service", "telemarketing", "cajero",
    "recepcionista", "chofer", "operador de montacargas",
    "construccion", "obra civil", "docente", "profesor*", "maestro",
]

# Dominios de curso ajenos que ninguna area de esta version cubre. Sirven para
# que `formacion.py` descarte, por ejemplo, un curso de musica.
OTROS_DOMINIOS_CURSO = [
    "veterinar*", "humanidades", "filosof*", "literatura", "historia del arte",
    "gastronom*", "turismo", "agropecuar*", "agronom*", "arquitectura",
    "diseno de modas", "trabajo social", "docencia basica", "educacion preescolar",
    "musica", "danza", "deporte*",
]

# Dominios de curso "fuertes" que SI reclama un area: son ajenos solo mientras
# esa area este inactiva. Es el resto del vocabulario de origen repartido entre
# sus areas, sin anadir terminos: un filtro de descarte falla en silencio
# (cicatriz 29), y las palabras suaves de cada area ("gestion", "calidad",
# "datos") aparecen en cursos de cualquier carrera. Con tecnologia como unica
# area activa, la lista de ajenos es la misma que en el sistema de origen.
DOMINIOS_CURSO_POR_AREA = {
    "salud": ["medic*", "salud", "enfermeria", "odontolog*", "farmaceut*"],
    "derecho": ["derecho", "juridic*", "leyes"],
    "contabilidad-finanzas": ["contadur*"],
    "recursos-humanos": ["psicolog*"],
}
assert set(DOMINIOS_CURSO_POR_AREA) <= set(AREAS), "DOMINIOS_CURSO_POR_AREA nombra un area inexistente"

# Comodines de las convocatorias que admiten a cualquier carrera.
CARRERAS_CUALQUIERA = [
    "cualquier carrera", "todas las carreras", "cualquier licenciatura",
    "todas las licenciaturas",
]

# ---------------------------------------------------------------------------
# ZONAS BASE. Solo Monterrey tiene definido su vocabulario de area
# metropolitana (en `geo.py`); `nacional` no presupone ninguna ciudad y por
# eso NO calcula si una vacante exige mudarse.
# ---------------------------------------------------------------------------
ZONAS = {
    "monterrey": {
        "etiqueta": "Monterrey y su area metropolitana",
        "corta": "Monterrey",
        "linkedin": "Monterrey, Nuevo Leon, Mexico",
        "occ": ["en-nuevo-leon", "en-monterrey-nuevo-leon"],
        "computrabajo": ["en-nuevo-leon", "en-monterrey"],
        "indeed": [("Monterrey, N. L.", 50), ("Nuevo León", 50)],
        "geo": "monterrey",
        # Subcadenas sobre la ubicacion normalizada (puntuacion y correos).
        "subcadenas": [
            "monterrey", "nuevo leon", "san pedro garza garcia", "san nicolas",
            "guadalupe", "apodaca", "santa catarina", "escobedo", "garcia",
            "juarez, n", "santiago, n", "cadereyta", "salinas victoria", "mty",
        ],
        # LIKE sobre la ubicacion en SQL (panel y filtro rapido).
        "sql_like": ["monterrey", "nuevo le", "apodaca", "san pedro", "guadalupe",
                     "santa catarina", "escobedo", "garcia", "san nicol"],
        "regex_js": "monterrey|nuevo le|apodaca|san pedro|guadalupe|santa catarina|"
                    "escobedo|garc[ií]a|san nicol",
        # Criterio de viabilidad de postulacion (postular.SQL_VIABLE).
        "ficha_like": ["monterrey", "nuevo le", "san pedro", "apodaca", "escobedo",
                       "santa catarina", "guadalupe", "pesqueria"],
        "ubicacion_like": ["monterrey", "nuevo le", "n. l."],
        "ciudades_lejos": ["ciudad de mexico", "cdmx", "guadalajara", "queretaro",
                           "puebla", "merida", "tijuana", "leon, guanajuato", "toluca",
                           "san luis potosi", "aguascalientes", "chihuahua", "cancun"],
        # Donde se puede asistir en persona a un curso (formacion.py).
        "cerca_cursos": ["monterrey", "nuevo leon", "san nicolas", "san pedro",
                         "guadalupe", "apodaca", "santa catarina", "escobedo", "amm",
                         "area metropolitana"],
    },
    "nacional": {
        "etiqueta": "Todo Mexico (sin zona base)",
        "corta": "Mexico",
        "linkedin": "",
        "occ": [],
        "computrabajo": [],
        "indeed": [],
        "geo": None,
        "subcadenas": [],
        "sql_like": [],
        "regex_js": "",
        "ficha_like": [],
        "ubicacion_like": [],
        "ciudades_lejos": [],
        "cerca_cursos": [],
    },
}

# ---------------------------------------------------------------------------
# Indices derivados
# ---------------------------------------------------------------------------
VALORES: dict[str, tuple[str, dict]] = {}
for _clave, _area in AREAS.items():
    for _valor, _datos in _area["valores"].items():
        VALORES[_valor] = (_clave, _datos)


def _unicas(lista):
    vistos, salida = set(), []
    for x in lista:
        if x not in vistos:
            vistos.add(x)
            salida.append(x)
    return salida


def _slug(frase: str) -> str:
    t = re.sub(r"[^a-z0-9]+", "-", normalizar(frase))
    return t.strip("-")


@lru_cache(maxsize=None)
def _regex(terminos: tuple[str, ...]) -> re.Pattern:
    return re.compile("|".join(f"({_patron(t)})" for t in terminos))


# ---------------------------------------------------------------------------
# Seleccion activa
# ---------------------------------------------------------------------------
def seleccion() -> tuple[list[str], set[str]]:
    """(claves de area activas, valores de `vacantes.area` activos).

    Admite claves de area (`salud`), valores concretos (`ciberseguridad`) o
    `todas`. Un nombre desconocido PARA el programa con un mensaje claro: una
    area mal escrita que se ignorase en silencio daria un panel vacio sin
    explicacion.
    """
    fichas = [t.strip().lower() for t in config.areas_texto().split(",") if t.strip()]
    claves: list[str] = []
    valores: set[str] = set()
    for ficha in fichas or ["todas"]:
        if ficha == "todas":
            for clave, area in AREAS.items():
                claves.append(clave)
                valores |= set(area["valores"])
        elif ficha in AREAS:
            claves.append(ficha)
            valores |= set(AREAS[ficha]["valores"])
        elif ficha in VALORES:
            claves.append(VALORES[ficha][0])
            valores.add(ficha)
        else:
            validas = ["todas", *AREAS, *[v for v in VALORES if v not in AREAS]]
            raise ValueError(
                f"ULTRACHAMBA_AREAS: '{ficha}' no es un area conocida. "
                f"Validas: {', '.join(validas)}")
    return _unicas(claves), valores


def claves_activas() -> list[str]:
    return seleccion()[0]


def valores_activos() -> set[str]:
    return seleccion()[1]


def valores_prioritarios() -> list[str]:
    """Valores activos que entran en la cola diaria y en los controles."""
    activos = valores_activos()
    return [v for v, (_c, d) in VALORES.items() if v in activos and d["prioritaria"]]


def etiqueta(valor: str) -> str:
    if valor == "fuera":
        return "Fuera de tus areas"
    return VALORES.get(valor, (None, {"etiqueta": valor}))[1]["etiqueta"]


def etiquetas() -> dict[str, str]:
    return {v: d["etiqueta"] for v, (_c, d) in VALORES.items()}


def peso(valor: str) -> int:
    return VALORES[valor][1]["peso"] if valor in VALORES else PESO_FUERA


def sql_in(columna: str, valores: list[str]) -> tuple[str, list[str]]:
    """`columna IN (?,?,...)` y sus parametros; nunca un IN vacio."""
    if not valores:
        return "(0)", []
    return f"{columna} IN ({','.join('?' * len(valores))})", list(valores)


def sql_literal_in(columna: str, valores: list[str]) -> str:
    """Igual, con los valores escritos en la consulta. Solo para constantes de
    este archivo (nunca texto que venga de fuera)."""
    if not valores:
        return "(0)"
    return f"{columna} IN (" + ",".join(f"'{v}'" for v in valores) + ")"


# ---------------------------------------------------------------------------
# Clasificacion por oficio (la usa dominio.py)
# ---------------------------------------------------------------------------
def area_por_titulo(titulo_n: str) -> tuple[str | None, list[str]]:
    """El area cuyo oficio nombra el titulo, sin mirar si esta activa.

    Si el titulo nombra oficios de dos areas, gana el que aparece ANTES: en
    espanol el puesto suele ir primero ("Auxiliar administrativo de ventas",
    "Ejecutivo de cuenta de nomina"). Con empate, el que mas terminos acumula,
    y despues el orden de `AREAS`.
    """
    mejor = None
    for orden, (clave, area) in enumerate(AREAS.items()):
        terminos = area.get("titulo")
        if not terminos:
            continue
        posiciones = [(m.start(), terminos[m.lastindex - 1])
                      for m in _regex(tuple(terminos)).finditer(titulo_n) if m.lastindex]
        if not posiciones:
            continue
        hallados = [t for t in terminos if t in {x for _, x in posiciones}]
        candidato = (min(p for p, _ in posiciones), -len(hallados), orden, clave, hallados)
        if mejor is None or candidato < mejor:
            mejor = candidato
    return (mejor[3], mejor[4]) if mejor else (None, [])


def area_por_ambiguo(titulo_n: str, activos: set[str]) -> tuple[str | None, list[str]]:
    for clave, area in AREAS.items():
        terminos = area.get("titulo_ambiguo")
        if terminos and clave in activos:
            hallados = terminos_presentes(titulo_n, tuple(terminos))
            if hallados:
                return clave, hallados
    return None, []


def area_por_descripcion(desc_n: str, activos: set[str],
                         minimo: int = 3) -> tuple[str | None, list[str]]:
    mejor: tuple[str | None, list[str]] = (None, [])
    for clave, area in AREAS.items():
        terminos = area.get("titulo")
        if not terminos or clave not in activos:
            continue
        hallados = terminos_presentes(desc_n, tuple(terminos))
        if len(hallados) >= minimo and len(hallados) > len(mejor[1]):
            mejor = (clave, hallados)
    return mejor


def oficio_sin_area(titulo_n: str) -> list[str]:
    return terminos_presentes(titulo_n, tuple(OFICIOS_SIN_AREA))


# ---------------------------------------------------------------------------
# Zona
# ---------------------------------------------------------------------------
def zona_clave() -> str:
    z = config.zona_texto().lower()
    if z not in ZONAS:
        raise ValueError(f"ULTRACHAMBA_ZONA: '{z}' no es una zona conocida. "
                         f"Validas: {', '.join(ZONAS)}")
    return z


def zona() -> dict:
    return ZONAS[zona_clave()]


def en_zona(ubicacion: str) -> bool:
    ubic_n = normalizar(ubicacion or "")
    return any(s in ubic_n for s in zona()["subcadenas"])


def sql_en_zona(columna: str = "ubicacion") -> tuple[str, list[str]]:
    like = zona()["sql_like"]
    if not like:
        return "(0)", []
    return ("(" + " OR ".join(f"LOWER({columna}) LIKE ?" for _ in like) + ")",
            [f"%{m}%" for m in like])


def sql_literal_en_zona(columna: str = "ubicacion") -> str:
    like = zona()["sql_like"]
    if not like:
        return "(0)"
    return "(" + " OR ".join(f"LOWER({columna}) LIKE '%{m}%'" for m in like) + ")"


def sql_viable_zona() -> str:
    """La parte geografica de `postular.SQL_VIABLE` para la zona activa.

    Sin zona base no se sabe que es "cerca", asi que no se filtra por ciudad:
    decidirlo seria inventar donde vive quien usa el sistema.
    """
    z = zona()
    if not z["ficha_like"]:
        return "1=1"
    ficha = "\n           OR ".join(f"LOWER(ubicacion_ficha) LIKE '%{m}%'"
                                    for m in z["ficha_like"])
    ubic = "\n           OR ".join(f"LOWER(COALESCE(ubicacion,'')) LIKE '%{m}%'"
                                   for m in z["ubicacion_like"])
    return f"""(CASE
         WHEN ubicacion_ficha IS NOT NULL THEN
              {ficha}
           OR LOWER(COALESCE(req_espacio,'')) LIKE '%casa%'
         ELSE modalidad = 'remoto'
           OR {ubic}
       END)"""


# ---------------------------------------------------------------------------
# Busquedas por fuente (las usan los colectores y la excavadora)
# ---------------------------------------------------------------------------
def busquedas_linkedin() -> list[tuple[str, str, str, int]]:
    """(palabras, ubicacion, filtros, paginas) para las areas activas."""
    ubic_zona = zona()["linkedin"] or "Mexico"
    salida, vistas = [], set()

    def agregar(palabras, ubicacion, filtros, paginas):
        ubicacion = ubic_zona if ubicacion == ZONA else ubicacion
        clave = (palabras.lower(), ubicacion, filtros)
        if clave not in vistas:
            vistas.add(clave)
            salida.append((palabras, ubicacion, filtros, paginas))

    for palabras, ubicacion, filtros in COMUNES["linkedin"]:
        agregar(palabras, ubicacion, filtros, PAGINAS_LINKEDIN)
    for clave in claves_activas():
        area = AREAS[clave]
        if area.get("linkedin"):
            for palabras, ubicacion, filtros in area["linkedin"]:
                agregar(palabras, ubicacion, filtros, PAGINAS_LINKEDIN)
            continue
        for frase in area.get("consultas", []):
            agregar(frase, ZONA, "&f_E=1%2C2", PAGINAS_LINKEDIN_GENERADAS)
        for termino in area.get("amplias", []):
            agregar(termino, "Mexico", "&f_E=1%2C2", PAGINAS_LINKEDIN_GENERADAS)
    return salida


def consultas_occ() -> list[str]:
    """Frases con guion para OCC y Computrabajo (profundidad normal)."""
    salida: list[str] = []
    for clave in claves_activas():
        area = AREAS[clave]
        salida += area.get("occ_consultas") or [_slug(c) for c in area.get("consultas", [])]
    return _unicas(salida)


def consultas_amplias_occ() -> list[str]:
    """Terminos sueltos para OCC (mas paginas)."""
    salida = list(COMUNES["amplias"])
    for clave in claves_activas():
        salida += [_slug(t) for t in AREAS[clave].get("amplias", [])]
    return _unicas(salida)


def zonas_occ() -> list[str]:
    return _unicas(zona()["occ"] + [""])


def zonas_computrabajo() -> list[str]:
    return _unicas(zona()["computrabajo"] + [""])


def consultas_indeed() -> list[str]:
    salida: list[str] = []
    for clave in claves_activas():
        area = AREAS[clave]
        salida += area.get("indeed") or (list(area.get("consultas", []))
                                         + list(area.get("amplias", [])))
    return _unicas(salida)


def ubicaciones_indeed() -> list[tuple[str, int]]:
    return _unicas(zona()["indeed"] + [("", 0)])


def regex_prefiltro_titulo() -> re.Pattern:
    """Prefiltro del orquestador para las areas activas.

    Se aplica al titulo tal cual Y normalizado: el de tecnologia se escribio
    para el texto crudo, y los terminos de las demas areas van sin acentos.
    """
    partes = []
    for clave in claves_activas():
        area = AREAS[clave]
        if area.get("prefiltro"):
            partes.append(area["prefiltro"])
        elif area.get("titulo"):
            partes.append("|".join(_patron(t) for t in area["titulo"]))
    partes.append(PREFILTRO_COMUN)
    return re.compile("|".join(f"(?:{p})" for p in partes), re.I)


def categorias_remotive() -> list[str]:
    salida = list(COMUNES["remotive"])
    for clave in claves_activas():
        salida += AREAS[clave].get("remotive", [])
    return _unicas(salida)


def industrias_jobicy() -> list[str]:
    salida = list(COMUNES["jobicy"])
    for clave in claves_activas():
        salida += AREAS[clave].get("jobicy", [])
    return _unicas(salida)


# ---------------------------------------------------------------------------
# Cursos, empresas y corpus
# ---------------------------------------------------------------------------
def pesos_cursos() -> dict[str, int]:
    pesos: dict[str, int] = {}
    for clave in claves_activas():
        for etiqueta_curso, p in AREAS[clave].get("cursos", {}).items():
            pesos[etiqueta_curso] = max(p, pesos.get(etiqueta_curso, 0))
    return pesos


def carreras_afines() -> list[str]:
    salida = list(CARRERAS_CUALQUIERA)
    for clave in claves_activas():
        salida += AREAS[clave].get("carreras", [])
    return _unicas(salida)


def terminos_curso() -> list[str]:
    salida: list[str] = []
    for clave in claves_activas():
        salida += AREAS[clave].get("terminos_curso", [])
    return _unicas(salida)


def terminos_otras_areas_curso() -> list[str]:
    """Dominios de curso que NO son de las areas activas.

    Los que ninguna area cubre, mas los dominios fuertes de las areas inactivas
    (`DOMINIOS_CURSO_POR_AREA`), menos lo que las areas activas nombran como
    suyo: asi la regla de dos llaves de `formacion.py` no se contradice.
    """
    activas = set(claves_activas())
    salida = list(OTROS_DOMINIOS_CURSO)
    for clave, terminos in DOMINIOS_CURSO_POR_AREA.items():
        if clave not in activas:
            salida += terminos
    propios = set(terminos_curso())
    return _unicas([t for t in salida if t not in propios])


def herramientas() -> list[str]:
    salida: list[str] = []
    for clave in claves_activas():
        salida += AREAS[clave].get("herramientas", [])
    return _unicas(salida)


def grupos_corpus() -> list[tuple[str, str, tuple[str, ...]]]:
    """(nombre de archivo, titulo, valores de area) para exportar_corpus.py."""
    salida = []
    for clave in claves_activas():
        if clave == "tecnologia":
            salida += [
                ("area-ciberseguridad", "Vacantes de ciberseguridad",
                 ("ciberseguridad", "ciber-ia")),
                ("area-inteligencia-artificial", "Vacantes de IA y datos", ("ia",)),
                ("area-ti-general", "Vacantes de TI general", ("ti-general",)),
            ]
        else:
            area = AREAS[clave]
            salida.append((f"area-{clave}", f"Vacantes de {area['etiqueta'].lower()}",
                           tuple(area["valores"])))
    return salida


def contexto_panel() -> dict:
    """Lo que el panel necesita saber de la configuracion activa."""
    z = zona()
    return {
        "zona": {"clave": zona_clave(), "etiqueta": z["etiqueta"],
                 "corta": z["corta"], "regex": z["regex_js"]},
        "areas": [{"clave": c, "etiqueta": AREAS[c]["etiqueta"]} for c in claves_activas()],
        "todas": len(claves_activas()) == len(AREAS),
        "etiquetas_area": etiquetas(),
    }


if __name__ == "__main__":
    claves, valores = seleccion()
    print(f"zona: {zona_clave()} ({zona()['etiqueta']})")
    print(f"areas activas: {', '.join(claves)}")
    print(f"valores de area: {', '.join(sorted(valores))}")
    print(f"LinkedIn: {len(busquedas_linkedin())} busquedas | "
          f"OCC: {len(consultas_occ())} frases + {len(consultas_amplias_occ())} amplias "
          f"en {len(zonas_occ())} zonas | Indeed: {len(consultas_indeed())} consultas "
          f"en {len(ubicaciones_indeed())} ubicaciones")
