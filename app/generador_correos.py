"""
Generador de correos de postulación adaptados a cada vacante.

Por qué existe. El sistema ya encuentra las vacantes buenas, pero escribir cada
correo a mano no escala, y una plantilla genérica tampoco sirve: un correo que
no nombra la vacante concreta ni cruza el CV con lo que esa vacante pide se lee
como un envío masivo y se borra.

Qué hace este módulo. Toma una vacante ya analizada (la fila de SQLite, con su
área, su ubicación, sus años exigidos y las habilidades que coincidieron con el
CV) y devuelve un correo listo para revisar, más una lista de advertencias
honestas para decidir si vale la pena mandarlo.

Las cuatro reglas de redacción NO son negociables:

  1. El asunto dice quién es y qué quiere, con un hecho concreto.
  2. La primera línea es un hecho verificable, no una presentación.
  3. Un solo pedido al final, respondible con sí o no.
  4. Nada de "Espero que se encuentre bien".

Y una regla de honestidad que pesa más que todas: aquí no se inventa nada. Todo
hecho sale de `perfil.py`: la apertura, de `LOGROS` / `LOGROS_EN`; las
habilidades, del cruce entre `HABILIDADES` y lo que la vacante pidió; la
carrera, la ciudad y la firma, de `POSTULACION` y `CANDIDATO`. Lo que está en
`HABILIDADES_EN_ESTUDIO` se escribe como lo que es, nunca como dominado. Lo que
el perfil no tiene no se rellena: el párrafo se omite y un aviso lo dice.

Uso:
    from generador_correos import generar, generar_por_id, generar_lote
    correo = generar_por_id("ID_DE_LA_VACANTE")
    print(correo["asunto"]); print(correo["cuerpo"]); print(correo["avisos"])
"""
from __future__ import annotations

import json
import re
import sys
import textwrap
import unicodedata
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from almacen import conexion, consultar  # noqa: E402
from perfil import (  # noqa: E402
    AMM,
    CANDIDATO,
    ESTADOS_EEUU,
    HABILIDADES,
    HABILIDADES_EN_ESTUDIO,
    LOGROS,
    LOGROS_EN,
    NIVEL_EXCLUIR,
    PAISES_CERRADOS,
    POSTULACION,
    ROL_NO_TECNICO,
    UBIC_EXTRANJERA,
    UBIC_MX_OTRA,
)

ANCHO = 78  # ancho de línea del cuerpo: se lee igual en móvil y en escritorio


# ------------------------------------------------------------------ texto ----

def _normalizar(texto: str) -> str:
    """Minúsculas sin acentos.

    Se reimplementa aquí en lugar de importar `nucleo.normalizar` porque
    `nucleo` arrastra `requests` y toda la pila de red: redactar un correo no
    debería depender de que las librerías HTTP estén instaladas.
    """
    nfkd = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


# Cromo de LinkedIn. Aparece en español en TODA ficha recogida desde
# mx.linkedin.com, incluso cuando el puesto está escrito en inglés, así que si
# no se quita antes de contar palabras el detector de idioma dice "español"
# para vacantes de San Francisco.
_BOILERPLATE = [
    "descubre a quien ha contratado", "unete o inicia sesion",
    "solicitar empleo de", "email o telefono", "contrasena mostrar",
    "has olvidado tu contrasena", "iniciar sesion con el email",
    "estas empezando a usar linkedin", "unete ahora",
    "al hacer clic en", "condiciones de uso", "politica de privacidad",
    "politica de cookies", "denunciar este empleo", "guardar denunciar",
    "se de los primeros", "solicitudes", "solicitar guardar",
    "enviar mensaje directo al anunciante", "iniciar sesion",
    "encontrar tu siguiente empleo", "para este puesto", "hace 1 dia",
    "sign in to", "join now", "your job alert is set", "show more",
    "by clicking continue", "user agreement", "privacy policy",
    "cookie policy", "report this job", "be among the first",
]

_ES_MARCADORES = (
    "que|de|la|el|los|las|del|para|con|por|una|unos|como|mas|este|esta|al|se|"
    "su|sus|nuestro|nuestra|experiencia|conocimientos|empresa|puesto|"
    "actividades|requisitos|ofrecemos|funciones|carrera|sueldo|prestaciones|"
    "horario|licenciatura|ingenieria|deseable|manejo|apoyo|seguimiento|"
    "buscamos|responsabilidades|habilidades|estudios|titulo|zona|anos"
)
_EN_MARCADORES = (
    "the|and|with|for|you|your|our|we|will|are|have|this|that|from|about|"
    "team|role|experience|requirements|responsibilities|skills|work|across|"
    "including|who|what|strong|ability|years|looking|join|help|build|"
    "please|preferred|qualifications|benefits|opportunity"
)
_RX_ES = re.compile(rf"\b(?:{_ES_MARCADORES})\b")
_RX_EN = re.compile(rf"\b(?:{_EN_MARCADORES})\b")

_RX_MX_OTRA = re.compile(UBIC_MX_OTRA)
_RX_EXTRANJERA = re.compile(UBIC_EXTRANJERA)
_RX_HISPANO = re.compile(
    r"\b(mexico|colombia|chile|argentina|peru|espana|spain|uruguay|paraguay|"
    r"bolivia|ecuador|venezuela|guatemala|honduras|salvador|nicaragua|"
    r"costa rica|panama|republica dominicana|puerto rico|latam|latinoamerica)\b"
)

# "mexico" a secas también casa dentro de "New Mexico", que es un estado de
# Estados Unidos. Sin el lookbehind, "Remote - New Mexico, USA" se leía como
# vacante mexicana y se contestaba en español.
_RX_MEXICO = re.compile(r"(?<!new )\bmexico\b")

# Países no hispanohablantes. Importan cuando aparecen JUNTO a México en la
# ubicación ("U.S. or Mexico Remote"): ahí la requisición la lleva el equipo de
# allá y quien lee el correo trabaja en inglés.
_RX_ANGLO = re.compile(
    r"\bu\.s\.|\bus\b|\busa\b|\bunited states\b|\bcanada\b|\buk\b|"
    r"\bunited kingdom\b|\bengland\b|\bireland\b|\baustralia\b|"
    r"\bnew zealand\b|\bindia\b|\bsingapore\b|\bgermany\b|\bdeutschland\b|"
    r"\bnetherlands\b|\bfrance\b|\bpoland\b|\bisrael\b|\bjapan\b|\bchina\b|"
    r"\bemea\b|\bapac\b"
)

# Fuentes cuyo catálogo es mexicano: si la vacante viene de ahí, la escribió
# alguien que trabaja en español aunque el título esté en inglés.
_FUENTES_MX = ("occ", "computrabajo", "empleos", "bumeran", "indeed-mx")

# Vocabulario de TÍTULO. Solo decide cuando la vacante no trae ubicación, que
# es justo el caso de los tableros extranjeros (Ashby, Greenhouse, portales
# alemanes): ahí el título es la única señal que hay.
# Ojo: aquí NO va "auditor", que se escribe igual en inglés y empujaba a
# español fichas como "IT Auditor (all genders)" de un banco austriaco.
_ES_TITULO = (
    "practicante|becario|becaria|ingeniero|ingeniera|analista|especialista|"
    "consultor|consultora|desarrollador|desarrolladora|tecnico|jefe|gerente|"
    "seguridad|informacion|sistemas|datos|redes|soporte|auditoria|"
    "riesgos|calidad|servicio|atencion|gestion|administracion|"
    "licenciatura|residente|practicas|empresa|nuestro|para"
)
# 'werkstudent', 'praktikum' y compañía son alemanas: no son español, y a una
# empresa alemana se le escribe en inglés.
_EN_TITULO = (
    "intern|internship|student|engineer|analyst|specialist|consultant|"
    "developer|manager|security|information|systems|network|support|audit|"
    "risk|quality|service|governance|compliance|associate|graduate|trainee|"
    "apprentice|summer|fall|winter|spring|senior|junior|lead|officer|"
    "scientist|architect|program|assistant|coordinator|advisor|technology|"
    "werkstudent|werkstudentin|praktikum|abschlussarbeit|stellentitel|titel"
)
_RX_ES_TITULO = re.compile(rf"\b(?:{_ES_TITULO})\b")
_RX_EN_TITULO = re.compile(rf"\b(?:{_EN_TITULO})\b")

# Ortografía que solo existe en español. Se mira sobre el texto SIN normalizar.
_RX_ORTOGRAFIA_ES = re.compile(r"[ñáéíóúü¿¡]", re.I)

# Francés y alemán también llevan acentos y diéresis, así que la señal de
# ortografía por sí sola marcaba como españolas vacantes de Ippon ("Data
# Engineer (H/F)") y de universidades duales alemanas. A esas se les escribe en
# inglés, no en español.
_RX_OTRO_IDIOMA = re.compile(
    r"\(h/f\)|\(f/h\)|\bh/f\b|\(m/w/d\)|\(w/m/d\)|\bm/w/d\b|"
    r"\bingenieur|\bchef\(?fe\)? de projet|\bstage\b|\balternance\b|"
    r"\bcdi\b|\bcdd\b|\bduales studium\b|\bkunstliche\b|\bwerkstudent|"
    r"\bpraktikum\b|\babschlussarbeit\b|\bstellentitel\b|\bmitarbeiter|"
    r"\bausbildung\b|\bund\b|\bder\b|\bdie\b|\bmit\b|\bfur\b|"
    r"\bnous\b|\bvous\b|\bpour\b|\bavec\b"
)


def _sin_ruido(texto: str) -> str:
    """Texto normalizado y sin el cromo de los agregadores."""
    t = _normalizar(texto)
    for frase in _BOILERPLATE:
        t = t.replace(frase, " ")
    return re.sub(r"\s+", " ", t)


def _envolver(parrafo: str) -> str:
    return textwrap.fill(parrafo.strip(), width=ANCHO)


# ----------------------------------------------------------- la vacante ------

def _campo(v: dict, clave: str, por_defecto=""):
    valor = v.get(clave)
    return por_defecto if valor is None else valor


def _habilidades_de(v: dict) -> list[str]:
    """Las habilidades que el análisis cruzó con el CV, venga de donde venga.

    `consultar()` devuelve la lista ya deserializada en
    `habilidades_coincidentes`; una fila cruda de SQLite la trae como JSON en
    `habilidades`. Se aceptan las dos formas para que `generar()` funcione con
    cualquiera de las dos sin que quien llama tenga que saberlo.
    """
    crudo = v.get("habilidades_coincidentes")
    if crudo is None:
        crudo = v.get("habilidades")
    if isinstance(crudo, str):
        try:
            crudo = json.loads(crudo or "[]")
        except (ValueError, TypeError):
            crudo = []
    if not isinstance(crudo, list):
        return []
    # Filtro duro: si no está en perfil.py, no es una habilidad tuya.
    propias = set(HABILIDADES) | set(HABILIDADES_EN_ESTUDIO)
    return [str(h).strip().lower() for h in crudo if str(h).strip().lower() in propias]


def _motivos_de(v: dict) -> list[str]:
    crudo = v.get("motivos")
    if isinstance(crudo, str):
        try:
            crudo = json.loads(crudo or "[]")
        except (ValueError, TypeError):
            crudo = []
    return list(crudo or [])


def _area_de(v: dict) -> str:
    """El área tal como la clasificó `dominio.py`: un valor de `areas.py`.

    Aquí no se reclasifica: dos clasificadores que discrepan acaban escribiendo
    correos que contradicen al panel. Si falta o no es un valor conocido, el
    correo usa solo lo "general" del perfil.

    `areas` se importa dentro de la función, igual que el resto de lo que
    arrastra la pila de red: redactar un correo no debería exigirla al importar.
    """
    import areas
    area = str(_campo(v, "area")).strip().lower()
    return area if area in areas.VALORES else "general"


def _grupo_de(area: str) -> str:
    """La clave de `areas.AREAS` a la que pertenece un valor ("ia" -> "tecnologia")."""
    import areas
    return areas.VALORES[area][0] if area in areas.VALORES else "general"


def _en_amm(v: dict) -> bool:
    """¿La ubicación es del área metropolitana de Monterrey?

    Solo decide el IDIOMA: es geografía mexicana, no la zona activa. Una vacante
    en Monterrey se contesta en español aunque la zona elegida sea `nacional`.
    """
    ubic = _normalizar(_campo(v, "ubicacion"))
    return any(m in ubic for m in AMM)


def _en_zona(v: dict) -> bool:
    """¿La vacante está en tu zona base (`ULTRACHAMBA_ZONA`)?"""
    import areas
    return areas.en_zona(_campo(v, "ubicacion"))


def _es_remota(v: dict) -> bool:
    if str(_campo(v, "modalidad")).lower() in ("remoto", "hibrido"):
        return True
    campo = _normalizar(f"{_campo(v, 'ubicacion')} {_campo(v, 'titulo')}")
    return bool(re.search(r"\bremot(e|o|a)\b|\banywhere\b|work from home", campo))


# ---------------------------------------------------------------- idioma -----

def detectar_idioma(v: dict) -> tuple[str, list[str]]:
    """Devuelve ('es'|'en', razones).

    Se combinan varias señales porque ninguna basta sola, pero NO pesan igual:

      - La ubicación manda. Una vacante en México la lee alguien que trabaja en
        español, aunque la ficha esté redactada en inglés porque la empresa es
        multinacional. Antes esta señal valía 4 puntos y la descripción valía
        5, así que 175 vacantes de Monterrey y CDMX salían en inglés: justo lo
        contrario de lo que dice la regla. Ahora México es decisivo.
      - La excepción es la ubicación mixta ("U.S. or Mexico Remote"): ahí la
        requisición la lleva el equipo de allá y se contesta en inglés.
      - El título solo decide cuando no hay ubicación, que es el caso de los
        tableros extranjeros.
      - Ante la duda se escribe en INGLÉS. Un correo en inglés a un reclutador
        mexicano se lee sin problema; uno en español a un reclutador que no
        habla español se va a la basura sin leerse. El riesgo no es simétrico.
    """
    puntos = {"es": 0.0, "en": 0.0}
    razones: list[str] = []

    ubic_n = _normalizar(_campo(v, "ubicacion"))
    en_mexico = bool(_en_amm(v) or _RX_MX_OTRA.search(ubic_n)
                     or _RX_MEXICO.search(ubic_n))
    tambien_anglo = bool(_RX_ANGLO.search(ubic_n))

    if en_mexico and not tambien_anglo:
        puntos["es"] += 9  # decisivo: supera a cualquier combinación de texto
        razones.append("ubicacion en Mexico")
    elif en_mexico and tambien_anglo:
        puntos["en"] += 3
        razones.append("ubicacion mixta Mexico/extranjero: la lleva el equipo de alla")
    elif _RX_HISPANO.search(ubic_n):
        puntos["es"] += 6
        razones.append("ubicacion en pais hispanohablante")
    elif _RX_EXTRANJERA.search(ubic_n) or tambien_anglo:
        puntos["en"] += 4
        razones.append("ubicacion en el extranjero")
    elif ubic_n.strip():
        puntos["en"] += 1.5
        razones.append("ubicacion sin senal de pais hispano")

    if str(_campo(v, "fuente")).split(":")[0] in _FUENTES_MX:
        puntos["es"] += 3
        razones.append("fuente de catalogo mexicano")

    titulo_crudo = _campo(v, "titulo")
    titulo_n = _sin_ruido(titulo_crudo)
    t_es = len(_RX_ES.findall(titulo_n)) + len(_RX_ES_TITULO.findall(titulo_n))
    t_en = len(_RX_EN.findall(titulo_n)) + len(_RX_EN_TITULO.findall(titulo_n))
    puntos["es"] += min(3.0, t_es * 1.5)
    puntos["en"] += min(3.0, t_en * 1.5)
    if t_es or t_en:
        razones.append(f"titulo ({t_es} es / {t_en} en)")

    desc_n = _sin_ruido(_campo(v, "descripcion"))[:6000]

    # Francés y alemán se descartan ANTES de contar marcadores. El francés
    # comparte con el español las dos palabras más frecuentes de la lista
    # ("de", "la"), así que una ficha de Ippon en francés puntuaba 70 a 6 a
    # favor del español y salía un correo en español para Francia.
    otro_idioma = bool(_RX_OTRO_IDIOMA.search(f"{titulo_n} {desc_n[:1200]}"))
    hispano = bool(en_mexico or _RX_HISPANO.search(ubic_n))

    if otro_idioma and not hispano:
        puntos["en"] += 6
        razones.append("ficha en frances o aleman: se responde en ingles")
    else:
        d_es, d_en = len(_RX_ES.findall(desc_n)), len(_RX_EN.findall(desc_n))
        if d_es + d_en >= 12:
            if d_es > d_en * 1.3:
                puntos["es"] += 5
                razones.append(f"descripcion en espanol ({d_es} vs {d_en} marcadores)")
            elif d_en > d_es * 1.3:
                puntos["en"] += 5
                razones.append(f"descripcion en ingles ({d_en} vs {d_es} marcadores)")
            else:
                razones.append(f"descripcion mezclada ({d_es} es / {d_en} en)")
        # Ortografía que solo existe en español, sobre el texto sin normalizar.
        # Es el último recurso cuando no hay ni ubicación ni descripción.
        if _RX_ORTOGRAFIA_ES.search(
                f"{titulo_crudo} {_campo(v, 'descripcion')[:600]}"):
            puntos["es"] += 1.5
            razones.append("ortografia espanola (acentos o enes)")

    # Empate = sin evidencia. Se va a inglés por el riesgo asimétrico.
    idioma = "es" if puntos["es"] > puntos["en"] else "en"
    razones.append(f"puntaje es={puntos['es']:.1f} en={puntos['en']:.1f}")
    return idioma, razones


# --------------------------------------------------------------- ángulos -----

# La primera línea de cada correo es un hecho verificable del CV, y se elige
# por área porque lo que impresiona en un despacho contable no es lo mismo que
# lo que impresiona en un laboratorio. Sale de `perfil.LOGROS` (español) y de
# `perfil.LOGROS_EN` (inglés): primero los del valor exacto del área, luego los
# de su área y al final los generales. Aquí no hay logros de fábrica: un
# generador que los trae escritos los pone en boca de quien no los hizo.

def _logros_para(area: str, idioma: str) -> list[str]:
    fuente = LOGROS if idioma == "es" else LOGROS_EN
    salida: list[str] = []
    for clave in (area, _grupo_de(area), "general"):
        for logro in fuente.get(clave, []):
            if logro and logro not in salida:
                salida.append(logro)
    return salida


def _angulo(area: str, idioma: str) -> str:
    """La apertura: el primer logro que aplica, o nada si el perfil no tiene."""
    logros = _logros_para(area, idioma)
    return logros[0] if logros else ""


def _quien_soy(nivel: str, idioma: str) -> str:
    """Cómo se presenta en el asunto, con la carrera de `POSTULACION` si consta."""
    if nivel == "practicas":
        return "Prácticas profesionales" if idioma == "es" else "Internship application"
    carrera = POSTULACION.get("carrera")
    if carrera and idioma == "es":
        return (f"Egresado/a de {carrera}" if POSTULACION.get("titulado") is True
                else f"Estudiante de {carrera}")
    return "Postulación" if idioma == "es" else "Application"


# ----------------------------------------------------------- habilidades -----

def _nombre_habilidad(h: str) -> str:
    """La habilidad como se escribe en una frase: las siglas, en mayúsculas."""
    return " ".join(p.upper() if p in _SIGLAS else p for p in h.split())


def _conceptos_coincidentes(habilidades: list[str], area: str) -> tuple[list[dict], list[dict]]:
    """Separa lo que manejas de lo que solo estudias, sin repetir la apertura.

    Cada habilidad se escribe tal como la declara `perfil.py`, sin frases de
    fábrica: una frase escrita para otro CV afirma cosas que este no respalda.
    Lo que está en `HABILIDADES_EN_ESTUDIO` va aparte y con su matiz.
    """
    apertura = _normalizar(" ".join(_logros_para(area, "es")[:1]
                                    + _logros_para(area, "en")[:1]))
    hechos: list[dict] = []
    estudio: list[dict] = []
    # Se ordena por el peso que perfil.py le da a la habilidad: lo más
    # diferenciador primero.
    ordenadas = sorted(dict.fromkeys(habilidades),
                       key=lambda h: (-HABILIDADES.get(h, 0), h))
    for hab in ordenadas:
        if apertura and re.search(rf"\b{re.escape(hab)}\b", apertura):
            continue
        nombre = _nombre_habilidad(hab)
        concepto = {"id": hab, "es": nombre, "en": nombre}
        (estudio if hab in HABILIDADES_EN_ESTUDIO else hechos).append(concepto)
    return hechos[:3], estudio[:2]


# --------------------------------------------------------------- asunto ------

# Siglas que tienen que seguir en mayúsculas cuando hay que rescatar un título
# escrito TODO EN MAYÚSCULAS. Sin esta lista, .capitalize() dejaba
# "ANALISTA DE CIBERSEGURIDAD JR" como "Analista de ciberseguridad jr" y
# "PRACTICANTE TI" como "Practicante ti".
_SIGLAS = {
    "ti", "it", "ia", "ai", "ml", "bi", "qa", "rh", "hr", "sap", "erp", "crm",
    "sgsi", "isms", "grc", "iso", "nist", "soc", "siem", "edr", "xdr", "dlp",
    "pam", "iam", "mfa", "sso", "ciso", "cio", "cto", "vpn", "api", "sql",
    "aws", "gcp", "sre", "noc", "iot", "pki", "dfir", "csirt", "devops",
    "devsecops", "jr", "sr", "ux", "ui", "etl", "llm", "nlp", "kpi", "poc",
    "cdmx", "usa", "us", "uk", "mx", "eeuu", "sox", "itgc", "pci", "dss",
}
# Partículas que van en minúscula dentro de un título, salvo al principio.
_ATONAS = {
    "de", "del", "la", "las", "el", "los", "y", "e", "en", "para", "por",
    "con", "a", "al", "o", "u", "the", "of", "and", "in", "for", "to", "at",
    "on", "an",
}
_RX_PALABRA = re.compile(r"^([^\w]*)(\w[\w'’·-]*)(.*)$", re.UNICODE)

# Etiquetas de género de las ofertas europeas y mexicanas: "(m/f/d)",
# "(all genders)", "(H/F)", "Becario (a)". No aportan nada a la frase.
_RX_GENERO = re.compile(
    r"\s*\(\s*(?:[mwfhdxsi](?:\s*[/|]\s*[mwfhdxsi])+|all\s+genders?|"
    r"todos\s+los\s+g[eé]neros|[ao](?:\s*/\s*[ao])?)\s*\)",
    re.I,
)
# Códigos internos entre corchetes: "[IC3]", "[AI Team]", "[Remote / Global]".
# Además de no decir nada, dejaban corchetes en el cuerpo y el correo parecía
# tener marcadores sin sustituir.
_RX_CORCHETES = re.compile(r"\s*\[[^\]]*\]")
# Cola de marketing pegada al título con un separador.
_RX_COLA = re.compile(
    r"\s*[|/–—]\s*[^|/–—]*\b(?:100\s*%|remot\w*|h[ií]brid\w*|presencial|"
    r"urgente|inmediat\w*|sueldo|salario|prestaciones|contrataci[oó]n|"
    r"only|full[-\s]?time|part[-\s]?time|medio\s+tiempo|temporal)\b[^|/–—]*$",
    re.I,
)


def _capitalizar_titulo(t: str) -> str:
    """Title Case que respeta siglas y partículas."""
    palabras = t.split(" ")
    salida: list[str] = []
    for i, p in enumerate(palabras):
        m = _RX_PALABRA.match(p)
        if not m:
            salida.append(p)
            continue
        pre, nucleo, post = m.groups()
        bajo = nucleo.lower()
        if bajo in _SIGLAS:
            nucleo = nucleo.upper()
        elif i > 0 and bajo in _ATONAS:
            nucleo = bajo
        else:
            nucleo = bajo[:1].upper() + bajo[1:]
        salida.append(pre + nucleo + post)
    return " ".join(salida)


def _grita(t: str) -> bool:
    letras = [c for c in t if c.isalpha()]
    return bool(letras) and sum(c.isupper() for c in letras) / len(letras) > 0.7


def _titulo_legible(titulo: str) -> str:
    """El título de la vacante tal y como puede escribirse dentro de una frase.

    El título crudo se metía sin tocar en "Le escribo por la vacante de ...",
    con tres consecuencias feas: los títulos en mayúsculas gritaban en mitad
    del párrafo, los códigos entre corchetes parecían marcadores sin sustituir
    y las colas de marketing ("- México Only", "| 100% Remoto") delataban que
    el texto venía copiado de un portal.
    """
    t = re.sub(r"\s+", " ", (titulo or "")).strip()
    t = _RX_CORCHETES.sub(" ", t)
    t = _RX_GENERO.sub(" ", t)
    t = _RX_COLA.sub("", t)
    t = re.sub(r"\s*[-–—]\s*[^-–—]*\b(?:only|remoto?|remote|h[ií]brido)\b\s*$", "", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" ,;:-–—|/")
    if _grita(t):
        t = _capitalizar_titulo(t)
    return t or re.sub(r"\s+", " ", (titulo or "")).strip()


def _puesto_limpio(titulo: str) -> str:
    """El título recortado a lo que cabe en un asunto sin ruido de marketing."""
    t = _titulo_legible(titulo)
    t = re.split(r"\s+[-–—|(]\s*|\s*\(", t)[0].strip(" -–—|")
    if _grita(t):
        t = _capitalizar_titulo(t)
    return t[:52].strip() or _titulo_legible(titulo)[:52]


def _empresa_limpia(empresa: str) -> str:
    """Quita la puntuacion final del nombre.

    Hay empresas registradas como "DaCodes." con punto incluido, y al meterlas
    a mitad de una frase salia "en DaCodes..". Se recorta solo el final; los
    puntos internos de siglas como "S.A." se respetan.
    """
    e = re.sub(r"\s+", " ", (empresa or "").strip())
    return e.rstrip(" .,;:·-–—") or e


def _asunto(v: dict, area: str, idioma: str, nivel: str) -> str:
    quien = _quien_soy(nivel, idioma)
    # El hecho del asunto es el logro de apertura, pero solo si cabe: un asunto
    # de cien caracteres se corta en la bandeja y deja media frase.
    apertura = _angulo(area, idioma)
    hecho = apertura if len(apertura) <= 60 else ""
    cola = f": {hecho}" if hecho else ""
    puesto = _puesto_limpio(_campo(v, "titulo"))
    union = "para" if idioma == "es" else "for"

    # Si el titulo del puesto ya dice que son practicas, anteponer "Practicas
    # para..." suena a tartamudeo: "Security internship for Security Engineer
    # Intern". En ese caso el titulo habla por si solo.
    if re.search(r"\b(intern|internship|becari|practicant|pr[aá]cticas|trainee)\b",
                 puesto, re.I):
        largo = f"{puesto}{cola}"
        return largo if len(largo) <= 92 else f"{puesto}"[:92]

    largo = f"{quien} {union} {puesto}{cola}"
    if len(largo) <= 92:
        return largo
    corto = f"{quien} {union} {puesto}"
    return corto if len(corto) <= 92 else (f"{quien}{cola}" if hecho else corto)[:92]


# ---------------------------------------------------------------- cuerpo -----

def _presentacion(idioma: str) -> str:
    """Quién escribe, solo con lo que dice `perfil.py`. Nada que no conste."""
    carrera = POSTULACION.get("carrera")
    universidad = POSTULACION.get("universidad")
    titulado = POSTULACION.get("titulado") is True
    if idioma == "es":
        if not carrera:
            return "Adjunto mi CV."
        verbo = "Soy egresado/a de" if titulado else "Estudio"
        donde = f" en {universidad}" if universidad else ""
        return f"{verbo} {carrera}{donde} y adjunto mi CV."
    partes: list[str] = []
    if carrera:
        verbo = "I graduated in" if titulado else "I'm studying"
        donde = f" at {universidad}" if universidad else ""
        partes.append(f"{verbo} {carrera}{donde}.")
    ingles = str(CANDIDATO.get("ingles") or "")
    if ingles and "EJEMPLO" not in ingles:
        partes.append(f"Spanish is my native language; my English level is {ingles}.")
    partes.append("My CV is attached.")
    return " ".join(partes)


def _parrafo_vacante(v: dict, idioma: str, hechos: list[dict], estudio: list[dict]) -> list[str]:
    titulo = re.sub(r"\s+", " ", _campo(v, "titulo")).strip()
    empresa = _empresa_limpia(_campo(v, "empresa"))
    parrafos: list[str] = []

    if idioma == "es":
        destino = f" en {empresa}" if empresa else ""
        cabeza = f"Le escribo por la vacante de {titulo}{destino}."
        if hechos:
            lista = _lista_es([c["es"] for c in hechos])
            cuantas = "Tres" if len(hechos) == 3 else ("Dos" if len(hechos) == 2 else "Una")
            cosa = "cosas que piden" if len(hechos) > 1 else "cosa que piden"
            cabeza += f" {cuantas} {cosa} y que ya manejo: {lista}."
        parrafos.append(cabeza)
        if estudio:
            parrafos.append(
                f"También estoy aprendiendo {_lista_es([c['es'] for c in estudio])}, y"
                " prefiero decirlo como es: ahí voy a nivel de estudio, no de"
                " experiencia."
            )
    else:
        destino = f" at {empresa}" if empresa else ""
        cabeza = f"I'm writing about the {titulo} role{destino}."
        if hechos:
            lista = _lista_en([c["en"] for c in hechos])
            cabeza += f" Things the role asks for that I already work with: {lista}."
        parrafos.append(cabeza)
        if estudio:
            parrafos.append(
                f"I'm also learning {_lista_en([c['en'] for c in estudio])}, and I'd"
                " rather be precise about it: that part is study level, not work"
                " experience."
            )
    parrafos.append(_presentacion(idioma))
    return parrafos


def _lista(items: list[str], conjuncion: str) -> str:
    """Une frases largas sin que se pierda dónde acaba una y empieza la otra.

    Los elementos pueden ser frases que ya llevan comas y conjunciones dentro
    ("conciliaciones bancarias, con cierre mensual y reporte"). Unirlas con
    comas producía listas donde no se sabe qué "y" separa qué: en el sistema de
    origen, 167 correos salían así. Cuando algún elemento ya trae coma o
    conjunción, se separa con punto y coma, que es exactamente para lo que sirve.
    """
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    complejos = any("," in i or f" {conjuncion} " in i for i in items)
    sep = "; " if complejos else ", "
    return sep.join(items[:-1]) + f"{';' if complejos else ''} {conjuncion} " + items[-1]


def _lista_es(items: list[str]) -> str:
    return _lista(items, "y")


def _lista_en(items: list[str]) -> str:
    return _lista(items, "and")


def _ciudad() -> str:
    """Tu ciudad según `perfil.CANDIDATO`, o vacía si sigue siendo la de EJEMPLO."""
    ciudad = str(CANDIDATO.get("ciudad") or "")
    if not ciudad or "EJEMPLO" in ciudad:
        return ""
    return ciudad.split(",")[0].strip()


def _utc() -> str:
    """El desfase horario de `CANDIDATO["zona_horaria"]`, si lo declara."""
    m = re.search(r"UTC\s*[+\-\u2212]\s*\d{1,2}", str(CANDIDATO.get("zona_horaria") or ""))
    return m.group(0).replace(" ", "") if m else ""


def _parrafo_ubicacion(v: dict, idioma: str) -> str:
    """Nunca ofrece mudanza: si la vacante la exige, se deja a tu decisión.

    Solo usa la ciudad de `perfil.CANDIDATO`. Si sigue siendo la de EJEMPLO, el
    párrafo no se escribe: mejor ninguna ciudad que una inventada.
    """
    ciudad = _ciudad()
    if not ciudad:
        return ""
    utc = _utc()
    horario = f" ({utc})" if utc else ""
    if bool(_campo(v, "requiere_mudanza", 0)):
        if idioma == "es":
            return (
                f"Estoy en {ciudad}. Si el puesto admite esquema remoto o híbrido,"
                " me encantaría platicarlo."
            )
        return (
            f"I'm based in {ciudad}. If the role can be done remotely or"
            " in a hybrid setup, I'd be glad to talk about it."
        )
    if _en_zona(v) and not _es_remota(v):
        if idioma == "es":
            return (
                f"Vivo en {ciudad}, así que puedo presentarme presencial desde el"
                " primer día, sin mudanza de por medio."
            )
        return (
            f"I live in {ciudad}, so I can be on site from day one, with no"
            " relocation involved."
        )
    if _es_remota(v):
        if idioma == "es":
            return (f"Trabajo desde {ciudad}{horario} y puedo coordinarme con el"
                    " horario de su equipo.")
        return f"I work from {ciudad}{horario} and can align with your team's hours."
    if idioma == "es":
        return f"Estoy en {ciudad}{horario} y puedo coordinarme con su horario."
    return f"I'm based in {ciudad}{horario} and can align with your hours."


def _pedido(idioma: str) -> str:
    if idioma == "es":
        return "¿Tendría 15 minutos esta semana o la próxima para una llamada?"
    return "Would you have 15 minutes for a call this week or next?"


def _firma(idioma: str) -> str:
    """Firma de cuatro líneas, cada una dentro de ANCHO.

    Los dos enlaces iban antes en la misma línea separados por '·': 84
    caracteres, seis por encima del ancho del cuerpo. En un cliente de correo
    que no reflowea, esa línea se partía por la mitad y dejaba media URL
    colgando, que además rompe el enlace al hacer clic. Uno por línea.
    """
    c = CANDIDATO
    contacto = " · ".join(x for x in (c.get("telefono"), c.get("correo")) if x)
    lineas = [
        "Gracias por el tiempo," if idioma == "es" else "Best,",
        c.get("nombre") or "",
        contacto,
        c.get("github") or "",
        c.get("linkedin") or "",
    ]
    # Lo que no esta en perfil.py no se escribe: una linea vacia en la firma
    # delata una plantilla sin rellenar.
    return "\n".join(linea for linea in lineas if linea)


# ---------------------------------------------------------------- avisos -----

def _saludo(v: dict, idioma: str, contacto: dict | None) -> str:
    """El saludo se resuelve solo. Nunca deja trabajo manual.

    Antes ponia "Hola [Nombre]:" y un aviso pidiendo sustituirlo. Eso convertia
    cada correo en una tarea de cinco minutos, y un sistema que deja tarea es un
    sistema que no se usa: el objetivo es que solo haya que revisar y enviar.

    Con contacto conocido va el nombre de PILA (el completo es la firma del
    correo en masa, y ademas obliga a adivinar el genero por el apellido).
    Sin contacto NO se inventa a nadie: se saluda al equipo de la empresa, que
    es correcto, enviable tal cual y no finge una cercania que no existe.
    """
    pila = ((contacto or {}).get("nombre") or "").strip().split(" ")[0]
    if pila:
        return f"Estimado/a {pila}:" if idioma == "es" else f"Hi {pila},"

    empresa = _empresa_limpia(str(_campo(v, "nombre_limpio") or _campo(v, "empresa")))
    if idioma == "es":
        return f"Hola, equipo de {empresa}:" if empresa else "Hola, buen dia:"
    return f"Hello {empresa} team," if empresa else "Hello,"


def _dias_desde(fecha: str) -> int | None:
    if not fecha:
        return None
    try:
        d = datetime.fromisoformat(str(fecha)[:10]).date()
    except ValueError:
        return None
    return (date.today() - d).days


def _avisos(v: dict, area: str, idioma: str, idioma_detectado: str,
            hechos: list[dict], estudio: list[dict],
            contacto: dict | None = None) -> tuple[list[str], list[str]]:
    """Advertencias honestas ANTES de enviar. Siempre en español."""
    avisos: list[str] = []
    codigos: list[str] = []

    def añadir(codigo: str, texto: str) -> None:
        codigos.append(codigo)
        avisos.append(texto)

    # Un perfil sin rellenar produce correos que no son de nadie. Va primero,
    # porque invalida todo lo demas.
    if "EJEMPLO" in str(CANDIDATO.get("nombre") or ""):
        añadir("perfil-ejemplo",
               "perfil.py sigue siendo la plantilla de EJEMPLO: la firma y la "
               "presentación no son tuyas. Rellénalo antes de enviar nada.")
    if not _logros_para(area, idioma):
        añadir("sin-logros",
               "No hay LOGROS en perfil.py para esta área ni generales: el correo "
               "no puede abrir con un hecho verificable, y sin eso se lee como "
               "envío masivo.")

    # El aviso ya no manda hacer nada: solo dice a quien va. Pedir "sustituye
    # [Nombre]" convertia cada correo en tarea manual, que es justo lo que este
    # sistema existe para quitar.
    if not contacto:
        añadir("contacto",
               "Va dirigido al equipo: no hay contacto verificado en esta empresa. "
               "Es enviable así; si aparece la persona, el saludo se pone solo.")

    anios = _campo(v, "anios_exigidos", None)
    tuyos = POSTULACION.get("anios_experiencia")
    if (isinstance(anios, int) and anios >= 3
            and not (isinstance(tuyos, int) and tuyos >= anios)):
        evidencia = str(_campo(v, "evidencia_experiencia")).strip()
        extra = f' La vacante dice: "{evidencia[:120]}".' if evidencia else ""
        cuantos = (f"perfil.py dice que tienes {tuyos}" if isinstance(tuyos, int)
                   else "perfil.py no dice cuántos tienes")
        añadir("experiencia",
               f"Pide {anios} años de experiencia y {cuantos}: si no los tienes, "
               f"vas con desventaja explícita, no por perfil sino por filtro.{extra}")

    if bool(_campo(v, "requiere_mudanza", 0)):
        añadir("mudanza",
               f"Es presencial en {_campo(v, 'ubicacion') or 'otra ciudad'}: "
               "implicaría mudarte. El correo NO ofrece mudanza; si te interesa, "
               "dilo tú a mano antes de enviarlo.")

    titulo_n = _normalizar(_campo(v, "titulo"))
    senior = [t for t in NIVEL_EXCLUIR if re.search(rf"\b{re.escape(t)}\b", titulo_n)]
    if senior or str(_campo(v, "nivel")) == "excluido":
        etiqueta = senior[0] if senior else "nivel excluido"
        añadir("senior",
               f"El título es de nivel superior ('{etiqueta}'): no es un puesto de "
               "entrada y probablemente te filtren antes de leerte.")

    # Solo en tecnología: en ventas o en recursos humanos, un puesto comercial
    # es justo el objetivo, no un aviso.
    comercial = [t for t in ROL_NO_TECNICO if t in titulo_n]
    if comercial and _grupo_de(area) == "tecnologia":
        añadir("no-tecnico",
               f"Parece un puesto comercial o no técnico ('{comercial[0]}'), no de "
               "ingeniería. Revisa si de verdad quieres esto.")

    ver = v.get("verificacion") or {}
    estado = ver.get("estado") if ver else _campo(v, "ver_estado")
    if estado and estado != "viva":
        añadir("sin-verificar",
               f"No se pudo confirmar que siga abierta (estado: {estado}). "
               "Ábrela antes de escribir.")

    dias = _dias_desde(_campo(v, "publicado"))
    if dias is not None and dias > 30:
        añadir("antigua",
               f"Se publicó hace {dias} días. A esa edad muchas ya están cubiertas "
               "aunque el enlace siga vivo.")

    if not bool(_campo(v, "elegible_mx", 1)):
        geo = next((m for m in _motivos_de(v)
                    if "restring" in m.lower() or "zona gris" in m.lower()
                    or "exige" in m.lower() or "visa" in m.lower()), "")
        añadir("geo",
               "El análisis marcó que quizá no puedas aplicar desde México"
               + (f": {geo[:160]}" if geo else "."))

    ubic_n = _normalizar(_campo(v, "ubicacion"))
    if _RX_EXTRANJERA.search(ubic_n) and not _es_remota(v):
        añadir("visa",
               "Es presencial en el extranjero: requeriría visa y patrocinio. "
               "Confirma que los tienes, o que la empresa los ofrece, antes de escribir.")

    if not hechos and not estudio:
        if not HABILIDADES and not HABILIDADES_EN_ESTUDIO:
            añadir("sin-habilidades",
                   "perfil.py no declara HABILIDADES: el correo no puede cruzar tu "
                   "CV con lo que pide la vacante. Rellénalas antes de usarlo en serio.")
        else:
            añadir("sin-habilidades",
                   "La vacante no coincidió con ninguna habilidad de tu CV, así que "
                   "el correo va sin ese cruce. Lee la vacante entera antes de "
                   "mandarlo: puede que no aplique.")

    if estudio:
        añadir("en-estudio",
               "El correo nombra como EN ESTUDIO: "
               + ", ".join(c["es"] for c in estudio)
               + ". No lo presentes como dominado en ningún otro lado.")

    veredicto = str(_campo(v, "veredicto"))
    if veredicto in ("zona-gris", "explorar"):
        añadir("veredicto",
               f"El sistema la clasificó como '{veredicto}', no como 'aplicar-ya': "
               "es una apuesta, no un tiro seguro.")

    if idioma != idioma_detectado:
        añadir("idioma-forzado",
               f"Forzaste el idioma '{idioma}' pero la vacante parece estar en "
               f"'{idioma_detectado}'.")

    return avisos, codigos


# ------------------------------------------------------------------- API -----

def generar(vacante: dict, idioma: str = "auto", contacto: dict | None = None) -> dict:
    """Devuelve {'asunto', 'cuerpo', 'angulo', 'avisos'}.

    Acepta tanto la fila cruda de SQLite como el diccionario que devuelve
    `almacen.consultar()`. Además de las cuatro claves del contrato incluye
    'idioma', 'habilidades_usadas' y 'codigos_aviso', que es lo que necesitan
    el panel y las pruebas para comprobar el resultado sin re-parsear el texto.
    """
    if not isinstance(vacante, dict):
        raise TypeError("generar() espera un diccionario de vacante")

    detectado, _razones = detectar_idioma(vacante)
    idioma = detectado if idioma == "auto" else idioma
    if idioma not in ("es", "en"):
        raise ValueError(f"idioma no soportado: {idioma!r} (usa 'auto', 'es' o 'en')")

    area = _area_de(vacante)
    nivel = str(_campo(vacante, "nivel"))
    habilidades = _habilidades_de(vacante)
    hechos, estudio = _conceptos_coincidentes(habilidades, area)

    saludo = _saludo(vacante, idioma, contacto)
    parrafos = [_angulo(area, idioma)]
    parrafos += _parrafo_vacante(vacante, idioma, hechos, estudio)
    parrafos.append(_parrafo_ubicacion(vacante, idioma))
    parrafos.append(_pedido(idioma))
    # Lo que el perfil no tiene no deja un hueco: se omite el párrafo entero.
    parrafos = [p for p in parrafos if p]

    cuerpo = saludo + "\n\n" + "\n\n".join(_envolver(p) for p in parrafos)
    cuerpo += "\n\n" + _firma(idioma)

    avisos, codigos = _avisos(vacante, area, idioma, detectado, hechos, estudio, contacto)

    return {
        "asunto": _asunto(vacante, area, idioma, nivel),
        "cuerpo": cuerpo,
        "angulo": area,
        "avisos": avisos,
        "idioma": idioma,
        "habilidades_usadas": [c["id"] for c in hechos + estudio],
        "codigos_aviso": codigos,
    }


def generar_por_id(vacante_id: str, idioma: str = "auto") -> dict:
    """Igual que `generar`, pero leyendo la vacante de la base por su id."""
    with conexion() as con:
        fila = con.execute(
            "SELECT * FROM vacantes WHERE id = ?", (vacante_id,)
        ).fetchone()
    if fila is None:
        raise KeyError(f"no existe la vacante {vacante_id!r} en la base")
    vacante = dict(fila)
    correo = generar(vacante, idioma=idioma)
    correo["id"] = vacante["id"]
    correo["titulo"] = vacante["titulo"]
    correo["empresa"] = vacante["empresa"]
    correo["url"] = vacante["url"]
    return correo


def generar_lote(veredicto: str = "aplicar-ya", limite: int = 20) -> list[dict]:
    """Correos para las mejores vacantes vivas de un veredicto, de mayor score a menor."""
    vacantes = consultar(veredictos=[veredicto], minimo=0.0, solo_vivas=True, limite=limite)
    lote: list[dict] = []
    for v in vacantes:
        correo = generar(v)
        correo["id"] = v.get("id")
        correo["titulo"] = v.get("titulo")
        correo["empresa"] = v.get("empresa")
        correo["url"] = v.get("url")
        correo["score"] = v.get("score")
        lote.append(correo)
    return lote


def formatear(correo: dict) -> str:
    """Un correo listo para leer en consola, con sus avisos debajo."""
    cabecera = f"{correo.get('empresa', '')} — {correo.get('titulo', '')}".strip(" —")
    partes = [
        "=" * ANCHO,
        cabecera,
        f"[{correo['angulo']} · {correo['idioma']}] {correo.get('url', '')}",
        "=" * ANCHO,
        f"Asunto: {correo['asunto']}",
        "",
        correo["cuerpo"],
        "",
        "-- avisos antes de enviar " + "-" * (ANCHO - 26),
    ]
    partes += [f"  - {a}" for a in correo["avisos"]]
    return "\n".join(partes)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    for correo in generar_lote(limite=2):
        print(formatear(correo))
        print()
