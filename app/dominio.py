"""
Clasificador de dominio: ¿de que area profesional es realmente esta vacante?

Modulo autonomo. Responde una sola pregunta -- a que area pertenece el puesto,
o si queda fuera de las areas activas -- y la responde mirando sobre todo el
TITULO.

DOS PIEZAS
----------
1. Las areas de oficio (contabilidad y finanzas, administracion, mercadotecnia
   y ventas, recursos humanos, derecho, ingenieria industrial, salud) se
   reconocen por los terminos que declara `areas.py`. Esos terminos son el
   antiguo "veto de rubro ajeno" del clasificador de ciberseguridad, repartido
   por oficio: en la version de origen servian para DESCARTAR; aqui sirven
   para ASIGNAR, y siguen descartando cuando el area no esta activa.
2. Tecnologia usa el clasificador especializado de origen (ciberseguridad, IA,
   seguridad de IA, TI general) con sus reglas sobre terminos ambiguos intactas.

POR QUE EXISTIA EL VETO, y por que sigue valiendo
-------------------------------------------------
El clasificador anterior dejaba pasar vacantes como "Mortgage
Processor/Underwriter", "Influencer Strategist" o "Mac MSP Help Desk Guru"
como si fueran de ciberseguridad. La causa era doble:

  1. Terminos ambiguos ("audit", "risk", "compliance", "fraud", "identity")
     contaban como seguridad en cuanto el texto traia CUALQUIER palabra de
     contexto tecnico, y esa lista incluia comodines como "datos", "data",
     "red", "it" o "sistemas". Casi cualquier anuncio los satisface.
  2. La DESCRIPCION podia ascender una vacante de otro rubro: a un help desk
     que menciona phishing y cumplimiento le bastaba con acumular tres
     senales sueltas para volverse "ciberseguridad".

PRINCIPIO DE DISENO: EL TITULO MANDA. Es lo unico que la empresa eligio para
nombrar el puesto. La descripcion solo puede confirmar, matizar o dejar un
aviso en `motivos`; nunca convierte un puesto de un rubro en otro.

ORDEN DE DECISION (el primero que dispara, gana)
------------------------------------------------
  0a. "Security officer" sin calificador informatico -> 'fuera' (es el guardia)
  0b. Oficio que ninguna area ofrece (guardia, call center, cajero) -> 'fuera'
  0c. Rol tecnico nombrado en el titulo (desarrollador, QA, soporte tecnico):
      se clasifica como tecnologia aunque el titulo nombre otro rubro
      ("Desarrollador de software medico"). Si tecnologia no reconoce nada,
      se sigue con el paso 1.
  1.  Oficio de un area en el titulo -> esa area si esta activa; si no, 'fuera'
  2.  Clasificador de tecnologia -> su valor si esta activo; si no, 'fuera'
  3.  Termino ambiguo financiero sin nada de TI -> contabilidad (confianza baja)
  4.  Descripcion claramente de un area activa -> esa area (confianza baja)
  5.  Nada de lo anterior -> 'fuera'

API publica: `clasificar_dominio(titulo, descripcion, activos=None) -> dict`.
`activos` son los valores de `vacantes.area` que interesan; por defecto, los
de `ULTRACHAMBA_AREAS` (ver `areas.py`).
"""
from __future__ import annotations

import areas
from nucleo import normalizar, terminos_presentes

# --------------------------------------------------------------------------
# 0a. EL GUARDIA DISFRAZADO
# --------------------------------------------------------------------------
# 'Security Officer' es el titulo estandar del guardia en EE.UU., pero tambien
# la cola de 'Information Security Officer' y 'Information System Security
# Officer (ISSO)', que si son ciberseguridad de verdad. No se puede vetar a
# secas ni dejar pasar a secas: decide el calificador que lo acompana.
# 'loss prevention' vive aqui y no en la lista dura por la misma razon: solo
# es el guardia de tienda cuando va suelto. 'Data Loss Prevention' (DLP) es
# ciberseguridad pura, y meterlo en el veto duro tiro una vacante legitima.
GUARDIA_SI_NO_HAY_CALIFICADOR = [
    "security officer", "security operative", "security agent", "safety officer",
    "loss prevention",
]

CALIFICADOR_INFORMATICO = [
    "information", "informacion", "cyber*", "ciber*", "infosec", "ti", "it",
    "sistemas", "system*", "digital", "red*", "network*", "datos", "data",
    "software", "aplicaciones", "cloud", "informatic*", "tecnologic*",
]

# --------------------------------------------------------------------------
# 0c. ROLES TECNICOS
# --------------------------------------------------------------------------
# Nombres de PUESTO, no de tema. Cuando el titulo dice que el trabajo es
# desarrollar, probar software o dar soporte, el rubro que lo acompane es el
# cliente, no el oficio: "Desarrollador de software medico" no es un puesto
# de salud. Deliberadamente NO incluye 'ti', 'it' ni 'sistemas': "IT Recruiter"
# es un reclutador y "Ejecutivo de ventas TI" es un vendedor.
TI_ROL = [
    "desarrollador*", "developer*", "programador*", "software engineer*",
    "ingeniero de software", "ingeniera de software", "ingenieria de software",
    "calidad de software", "qa engineer", "tester*", "devops", "sre",
    "data engineer*", "ingeniero de datos", "ingeniera de datos",
    "cientifico de datos", "cientifica de datos", "data scien*",
    "machine learning", "ai trainer", "almacen de datos", "full stack",
    "fullstack", "backend", "frontend", "ingeniero de redes",
    "administrador de redes", "administrador de sistemas", "sysadmin",
    "soporte tecnico", "help desk", "helpdesk", "mesa de ayuda", "service desk",
]

# NOTA sobre "help desk", "mesa de ayuda" y "soporte tecnico": aqui NO son
# veto. El soporte tecnico es la puerta de entrada real a TI (y varias vacantes
# de SOC N1 se publican con ese nombre), asi que se clasifican como
# 'ti-general': visibles, pero nunca confundidos con ciberseguridad. Como los
# oficios sin area se evaluan ANTES, "Help Desk Call Center" termina en 'fuera'.
TI_SOPORTE = [
    "help desk", "helpdesk", "service desk", "servicedesk", "mesa de ayuda",
    "mesa de servicio", "soporte tecnico", "soporte a usuarios",
    "soporte de ti", "soporte en sitio", "desktop support", "technical support",
    "it support", "user support", "field service", "soporte",
]

# --------------------------------------------------------------------------
# 1. TERMINOS INEQUIVOCOS DE TECNOLOGIA
# --------------------------------------------------------------------------
# Si uno de estos aparece en el TITULO, la vacante es de ciberseguridad.
# Ninguno tiene un uso frecuente en otro rubro.
# Ojo: 'security' va exacto, no como prefijo: 'securit*' casaria con
# 'securities' (finanzas).
CIBER_FUERTE = [
    "ciber*", "cyber*", "infosec", "security", "appsec", "devsecops", "secops",
    "seguridad de la informacion", "seguridad informatica",
    "information security", "seguridad ofensiva", "seguridad defensiva",
    "soc", "siem", "soar", "edr", "xdr", "dlp", "iam", "pki",
    "pentest*", "penetration test*", "ethical hack*", "hacking etico",
    "hacking", "hacker*", "bug bounty",
    "red team", "blue team", "purple team",
    "malware", "ransomware", "phishing", "forense", "forensic*",
    "threat*", "amenaza*", "vulnerabilidad*", "vulnerabilit*",
    "ciso", "grc", "governance, risk", "gobierno, riesgo",
    "iso 27001", "iso/iec 27001", "27001", "iso 42001",
    "nist", "owasp", "mitre", "zero trust", "hardening",
    "incident response", "respuesta a incidentes", "criptograf*", "cryptograph*",
    # Huecos que destapo la limpieza de las descripciones: sin ellos, un
    # "Ingeniero de Identidad y Acceso" (que es IAM puro) quedaba fuera porque
    # 'identidad' sola es un termino ambiguo.
    "identidad y acceso", "gestion de identidades", "identity and access",
    "control de acceso", "access management", "privileged access",
    "acceso privilegiado", "pam", "sso", "mfa", "autenticacion",
    "ai safety", "seguridad de la ia", "trust and safety",
    "llm security", "prompt injection", "jailbreak", "guardrails",
]

# Igual, pero para IA / datos. Tambien son inequivocos en un titulo.
IA_FUERTE = [
    "ia", "ai", "inteligencia artificial", "artificial intelligence",
    "machine learning", "aprendizaje automatico", "deep learning",
    "redes neuronales", "neural",
    # OJO: el comodin '*' solo funciona al FINAL del termino, nunca en medio.
    # "ingenier* de datos" y "cientific* de datos" estaban escritos asi y no
    # coincidian con nada: "Practicante de Ingenieria de Datos" salia
    # clasificada como fuera. Se escriben las variantes completas.
    "data scien*", "ciencia de datos", "cientifico de datos",
    "cientifica de datos", "cientificos de datos",
    "data engineer*", "ingenieria de datos", "ingeniero de datos",
    "ingeniera de datos", "practicante de datos", "becario de datos",
    "data analyst", "analista de datos",
    "analitica de datos", "analitica avanzada", "data analytics",
    "gobierno de datos", "data governance",
    "llm", "llms", "language model", "modelo de lenguaje",
    "nlp", "procesamiento de lenguaje", "mlops", "genai", "gen ai",
    "generative ai", "ia generativa", "computer vision", "vision artificial",
    "interpretability", "interpretabilidad", "rlhf", "big data",
]

# --------------------------------------------------------------------------
# 2. TERMINOS AMBIGUOS Y SU CONTEXTO
# --------------------------------------------------------------------------
# Estos existen identicos en auditoria contable, riesgo financiero, actuaria y
# cumplimiento legal. Solo acreditan ciberseguridad si el MISMO TITULO trae
# contexto tecnologico explicito.
AMBIGUOS = [
    "auditoria", "auditor*", "audit", "auditing",
    "riesgo*", "risk", "compliance", "cumplimiento", "control interno",
    "internal control", "governance", "gobierno", "identidad", "identity",
    "fraude*", "fraud", "privacidad", "privacy", "deteccion", "detection",
    "incidente*", "regulatorio", "normativ*",
]

# Contexto ESTRICTO: lo unico que convierte un termino ambiguo en seguridad.
# Deliberadamente NO incluye 'datos', 'data' ni 'red': esos comodines eran la
# causa raiz de que "Becario de Auditoria Fiscal y Analisis de Bases de Datos"
# puntuara como vacante de ciberseguridad.
CONTEXTO_ESTRICTO = [
    "ti", "it", "sistemas", "sistemas de informacion", "informatica",
    "informatic*", "tecnologia de la informacion", "tecnologias de la informacion",
    "information technology", "itgc", "sox", "de la informacion",
    "cibernetic*", "digital", "tecnologic*", "tecnologia*", "tech",
    "software", "aplicaciones", "cloud", "ciberseguridad",
]

# 'seguridad' a secas es demasiado suelta en espanol para ser inequivoca, pero
# sus falsos positivos (industrial, patrimonial, fisica, e higiene) ya se van
# antes: los de planta son un oficio de ingenieria industrial y los de
# vigilancia un oficio sin area. Por eso le basta con contexto de TI amplio.
SEGURIDAD_GENERICA = ["seguridad", "safety"]

# --------------------------------------------------------------------------
# 3. CONTEXTO DE TI GENERAL
# --------------------------------------------------------------------------
# Amplio a proposito: aqui no se otorga 'ciberseguridad', solo 'ti-general'.
# 'red' en singular queda fuera (casa con "redes sociales", "red de tiendas").
CONTEXTO_TI = [
    "ti", "it", "sistemas", "informatica", "informatic*", "computacion",
    "computo", "telecomunicaciones", "telematica", "tecnologia*", "tech",
    "infraestructura", "infrastructure", "redes", "network*", "cloud", "nube",
    "devops", "sre", "site reliability", "sysadmin", "administrador de sistemas",
    "servidores", "server*", "data center", "datacenter", "erp", "sap",
    "software", "hardware", "developer", "desarrollador*", "programador*",
    "desarrollo de software", "full stack", "backend", "back end", "frontend",
    "python", "java", "javascript", ".net", "sql", "base de datos", "dba",
    "linux", "windows server", "azure", "aws", "google cloud", "open source",
    "centro de datos", "centros de datos",   # la version en espanol de 'data center'
    "helpdesk", "help desk", "service desk", "mesa de ayuda", "mesa de servicio",
    "soporte", "activos ti", "gestion de activos",
]

# --------------------------------------------------------------------------
# Confianzas base de cada camino de decision.
# --------------------------------------------------------------------------
_CONF = {
    "veto": 0.93,
    "oficio": 0.85,
    "fuerte": 0.88,
    "cruce": 0.90,
    "ambiguo_ctx": 0.72,
    "seguridad_ctx": 0.70,
    "soporte": 0.80,
    "ti_ctx": 0.72,
    "ti_desc": 0.45,
    "fuera": 0.62,
    "fuera_ambiguo": 0.66,
    "ambiguo_area": 0.55,
    "desc_area": 0.45,
}


def _presentes(texto_n: str, vocabulario) -> list[str]:
    """Terminos del vocabulario presentes como palabra completa."""
    if not texto_n:
        return []
    return terminos_presentes(texto_n, vocabulario)


def _ev(origen: str, terminos) -> list[str]:
    """Formatea evidencia legible: de donde salio cada termino."""
    return [f"{origen}: {t}" for t in terminos]


def _ajustar(confianza: float, delta: float) -> float:
    return round(max(0.20, min(0.97, confianza + delta)), 2)


def _resultado(area: str, confianza: float, evidencia: list[str],
               motivos: list[str]) -> dict:
    assert area == "fuera" or area in areas.VALORES, f"area invalida: {area}"
    return {
        "area": area,
        "confianza": round(float(confianza), 2),
        "evidencia": evidencia,
        "motivos": motivos,
    }


def _tecnologia(titulo_n: str, desc_n: str) -> dict:
    """El clasificador especializado de origen, sin su veto de rubro ajeno.

    Devuelve 'ciberseguridad' | 'ia' | 'ciber-ia' | 'ti-general' | 'fuera'.
    Si esta en 'fuera', sus motivos explican por que no es tecnologia.
    """
    t_ciber = _presentes(titulo_n, CIBER_FUERTE)
    t_ia = _presentes(titulo_n, IA_FUERTE)
    t_ambiguo = _presentes(titulo_n, AMBIGUOS)
    t_seguridad = _presentes(titulo_n, SEGURIDAD_GENERICA)
    t_soporte = _presentes(titulo_n, TI_SOPORTE)

    # Senales de la descripcion: solo modulan la confianza y dejan avisos.
    d_ciber = _presentes(desc_n, CIBER_FUERTE)
    d_ia = _presentes(desc_n, IA_FUERTE)
    d_ti = _presentes(desc_n, CONTEXTO_TI)

    # ---------------------------------------------------------------- 1 ----
    # Terminos inequivocos en el titulo.
    if t_ciber and t_ia:
        confianza = _CONF["cruce"]
        motivos = [f"el titulo cruza seguridad e IA: '{t_ciber[0]}' + '{t_ia[0]}'"]
        if d_ciber and d_ia:
            confianza = _ajustar(confianza, 0.05)
            motivos.append("la descripcion confirma ambos lados del cruce")
        return _resultado(
            "ciber-ia", confianza,
            _ev("titulo", t_ciber) + _ev("titulo", t_ia), motivos,
        )

    if t_ciber:
        confianza = _CONF["fuerte"]
        motivos = [f"termino inequivoco de seguridad en el titulo: '{t_ciber[0]}'"]
        evidencia = _ev("titulo", t_ciber)
        if len(d_ciber) >= 3:
            confianza = _ajustar(confianza, 0.06)
            motivos.append(f"la descripcion lo confirma ({len(d_ciber)} senales)")
            evidencia += _ev("descripcion", d_ciber[:5])
        elif not desc_n:
            confianza = _ajustar(confianza, -0.05)
            motivos.append("sin descripcion para confirmar: veredicto solo por titulo")
        return _resultado("ciberseguridad", confianza, evidencia, motivos)

    if t_ia:
        confianza = _CONF["fuerte"]
        motivos = [f"termino inequivoco de IA/datos en el titulo: '{t_ia[0]}'"]
        evidencia = _ev("titulo", t_ia)
        if t_ambiguo:
            motivos.append(
                f"el titulo tambien trae '{t_ambiguo[0]}', que es ambiguo: "
                "confirma que el analisis sea tecnico y no financiero"
            )
            confianza = _ajustar(confianza, -0.08)
        if len(d_ia) >= 3:
            confianza = _ajustar(confianza, 0.06)
            motivos.append(f"la descripcion lo confirma ({len(d_ia)} senales)")
            evidencia += _ev("descripcion", d_ia[:5])
        elif not desc_n:
            confianza = _ajustar(confianza, -0.05)
            motivos.append("sin descripcion para confirmar: veredicto solo por titulo")
        return _resultado("ia", confianza, evidencia, motivos)

    # ---------------------------------------------------------------- 2 ----
    # Termino ambiguo + contexto tecnologico ESTRICTO, ambos en el titulo.
    if t_ambiguo:
        ctx = _presentes(titulo_n, CONTEXTO_ESTRICTO)
        if ctx:
            confianza = _CONF["ambiguo_ctx"]
            motivos = [
                f"'{t_ambiguo[0]}' es ambiguo, pero el titulo lo ancla a "
                f"tecnologia con '{ctx[0]}': es auditoria/riesgo de TI"
            ]
            evidencia = _ev("titulo", t_ambiguo) + _ev("contexto", ctx)
            if len(d_ciber) >= 3:
                confianza = _ajustar(confianza, 0.08)
                motivos.append(
                    f"la descripcion refuerza el enfoque de seguridad ({len(d_ciber)} senales)"
                )
            return _resultado("ciberseguridad", confianza, evidencia, motivos)

    # 'seguridad' a secas: le basta contexto de TI amplio (ver comentario del
    # vocabulario). "Ingeniero Junior Redes y Seguridad" si es ciberseguridad.
    if t_seguridad:
        ctx_ti = _presentes(titulo_n, CONTEXTO_TI)
        if ctx_ti:
            motivos = [
                f"el titulo dice 'seguridad' junto a contexto de TI ('{ctx_ti[0]}'): "
                "es seguridad informatica, no industrial ni patrimonial"
            ]
            return _resultado(
                "ciberseguridad", _CONF["seguridad_ctx"],
                _ev("titulo", t_seguridad) + _ev("contexto", ctx_ti), motivos,
            )

    # ---------------------------------------------------------------- 3 ----
    # Familia de soporte / mesa de ayuda: TI general, nunca ciberseguridad.
    if t_soporte:
        motivos = [
            f"el titulo es de soporte ('{t_soporte[0]}'): puerta de entrada a TI, "
            "no es un puesto de ciberseguridad"
        ]
        if d_ciber:
            motivos.append(
                f"la descripcion menciona seguridad ({', '.join(d_ciber[:3])}) pero "
                "no asciende el puesto: un help desk sigue siendo soporte"
            )
        return _resultado(
            "ti-general", _CONF["soporte"], _ev("titulo", t_soporte), motivos,
        )

    # ---------------------------------------------------------------- 4 ----
    # Contexto de TI en el titulo, sin especialidad declarada.
    ctx_ti = _presentes(titulo_n, CONTEXTO_TI)
    if ctx_ti:
        motivos = [
            f"titulo de TI general ('{ctx_ti[0]}') sin especialidad de seguridad ni IA"
        ]
        if d_ciber:
            motivos.append(
                "la descripcion toca seguridad, pero el titulo manda: se queda en TI general"
            )
        return _resultado(
            "ti-general", _CONF["ti_ctx"], _ev("titulo", ctx_ti), motivos,
        )

    # ---------------------------------------------------------------- 5 ----
    # Ultimo recurso: el titulo no dice nada y la descripcion es claramente de
    # TI. Solo puede llegar a 'ti-general', jamas a seguridad ni a IA.
    if len(d_ti) >= 3:
        motivos = [
            "el titulo no declara area; la descripcion apunta a TI "
            f"({len(d_ti)} senales): clasificada como TI general con baja confianza"
        ]
        if d_ciber:
            motivos.append(
                "hay menciones de seguridad en la descripcion, pero sin respaldo "
                "en el titulo no se clasifica como ciberseguridad"
            )
        return _resultado(
            "ti-general", _CONF["ti_desc"], _ev("descripcion", d_ti[:5]), motivos,
        )

    # ---------------------------------------------------------------- 6 ----
    if t_ambiguo:
        motivos = [
            f"el titulo solo trae terminos ambiguos ('{t_ambiguo[0]}') sin contexto "
            "de TI: puede ser auditoria contable, riesgo financiero o actuarial"
        ]
        return _resultado(
            "fuera", _CONF["fuera_ambiguo"], _ev("titulo", t_ambiguo), motivos,
        )

    motivos = ["el titulo no es de seguridad, ni de IA, ni de TI"]
    if d_ciber or d_ia:
        motivos.append(
            "la descripcion menciona el tema, pero sin senal en el titulo no alcanza"
        )
    return _resultado("fuera", _CONF["fuera"], [], motivos)


def _si_esta_activa(r: dict, activos: set[str]) -> dict:
    """Deja el resultado si su area esta activa; si no, lo convierte en 'fuera'."""
    if r["area"] == "fuera" or r["area"] in activos:
        return r
    return _resultado(
        "fuera", r["confianza"], r["evidencia"],
        r["motivos"] + [f"es de {areas.etiqueta(r['area'])}, que no esta entre "
                        "las areas activas"],
    )


def clasificar_dominio(titulo: str, descripcion: str,
                       activos: set[str] | None = None) -> dict:
    """Devuelve {'area', 'confianza', 'evidencia', 'motivos'}.

    `area` es un valor de `areas.VALORES` activo, o 'fuera'. `confianza` va de
    0.0 a 1.0. `evidencia` son los terminos concretos que dispararon el
    veredicto. `motivos` explica la decision en espanol sin acentos, para que
    quien use el sistema pueda auditar por que decidio eso.
    """
    activos = areas.valores_activos() if activos is None else set(activos)
    titulo_n = normalizar(titulo or "")
    desc_n = normalizar(descripcion or "")[:4000]

    if not titulo_n.strip():
        return _resultado(
            "fuera", 0.30, [],
            ["sin titulo: el titulo es la unica senal fiable y no hay ninguna"],
        )

    # --------------------------------------------------------------- 0a ----
    # Guardia de seguridad fisica disfrazado. Va antes que todo porque la
    # decision depende de lo que ACOMPANA al termino, no del termino solo.
    guardia = _presentes(titulo_n, GUARDIA_SI_NO_HAY_CALIFICADOR)
    if guardia and not _presentes(titulo_n, CALIFICADOR_INFORMATICO):
        return _resultado(
            "fuera", _CONF["veto"], _ev("titulo", guardia),
            [f"'{guardia[0]}' sin nada informatico al lado es el titulo del "
             "guardia de seguridad fisica, no de seguridad informatica",
             "si fuera del oficio diria 'information security officer', "
             "'ciso' o 'seguridad de la informacion'"],
        )

    # --------------------------------------------------------------- 0b ----
    sin_area = areas.oficio_sin_area(titulo_n)
    if sin_area:
        return _resultado(
            "fuera", _CONF["veto"], _ev("titulo", sin_area),
            [f"el titulo nombra un oficio que ninguna area de esta version "
             f"ofrece: '{sin_area[0]}'"],
        )

    # --------------------------------------------------------------- 0c ----
    rol = _presentes(titulo_n, TI_ROL)
    if rol:
        r = _tecnologia(titulo_n, desc_n)
        if r["area"] != "fuera":
            r["motivos"].insert(
                0, f"el titulo nombra un rol tecnico ('{rol[0]}'): manda sobre el "
                   "rubro que lo acompane")
            return _si_esta_activa(r, activos)

    # ---------------------------------------------------------------- 1 ----
    # Oficio de un area en el titulo: gana sobre cualquier termino fuerte de
    # seguridad. "Becario Comercial de Ciberseguridad" es una vacante de ventas
    # que vende ciberseguridad.
    area_oficio, terminos = areas.area_por_titulo(titulo_n)
    if area_oficio:
        etiqueta = areas.etiqueta(area_oficio)
        t_tec = _presentes(titulo_n, CIBER_FUERTE) + _presentes(titulo_n, IA_FUERTE)
        confianza_extra = 0.03 * (len(terminos) - 1)
        if area_oficio in activos:
            motivos = [f"el titulo nombra el oficio '{terminos[0]}': es un puesto "
                       f"de {etiqueta.lower()}"]
            if t_tec:
                motivos.append(f"tambien menciona '{t_tec[0]}', pero el oficio del "
                               "titulo manda sobre el tema")
            return _resultado(area_oficio, _ajustar(_CONF["oficio"], confianza_extra),
                              _ev("titulo", terminos), motivos)
        motivos = [
            f"el titulo nombra otro rubro: '{terminos[0]}' ({etiqueta.lower()}), que "
            "no esta entre las areas activas; ese oficio manda sobre cualquier "
            "palabra de seguridad o IA que traiga el texto"
        ]
        if t_tec:
            motivos.append(
                f"el titulo mezcla '{t_tec[0]}' con '{terminos[0]}': se descarta "
                "porque el puesto pertenece al otro rubro"
            )
        if _presentes(desc_n, CIBER_FUERTE):
            motivos.append(
                "la descripcion menciona seguridad, pero una descripcion no "
                "cambia el rubro del puesto"
            )
        return _resultado("fuera", _ajustar(_CONF["veto"], confianza_extra),
                          _ev("titulo", terminos), motivos)

    # ---------------------------------------------------------------- 2 ----
    r = _tecnologia(titulo_n, desc_n)
    if r["area"] != "fuera":
        return _si_esta_activa(r, activos)

    # ---------------------------------------------------------------- 3 ----
    if not _presentes(titulo_n, CONTEXTO_ESTRICTO):
        area_amb, hallados = areas.area_por_ambiguo(titulo_n, activos)
        if area_amb:
            return _resultado(
                area_amb, _CONF["ambiguo_area"], _ev("titulo", hallados),
                [f"'{hallados[0]}' sin nada de TI en el titulo: casi siempre es "
                 f"{areas.etiqueta(area_amb).lower()} (confianza baja: conviene "
                 "leer el anuncio)"],
            )

    # ---------------------------------------------------------------- 4 ----
    area_desc, hallados = areas.area_por_descripcion(desc_n, activos)
    if area_desc:
        return _resultado(
            area_desc, _CONF["desc_area"], _ev("descripcion", hallados[:5]),
            [f"el titulo no declara area; la descripcion apunta a "
             f"{areas.etiqueta(area_desc).lower()} ({len(hallados)} senales): "
             "confianza baja"],
        )

    # ---------------------------------------------------------------- 5 ----
    return r
