"""
Extraccion auditable de los anos de experiencia que exige una vacante.

Por que existe este modulo
--------------------------
Quien busca practicas o su primer empleo tiene, como mucho, una practica
corta. Una vacante que pide 3 anos o mas no es alcanzable, punto. El clasificador anterior dejaba
pasar esas vacantes por tres motivos concretos:

  1. Solo miraba los anos si el TITULO no traia senal de nivel. Un anuncio
     titulado "Security Engineer, Product" que en el cuerpo pide 5 anos se
     quedaba en 'junior' porque el titulo ya habia decidido.
  2. La regex solo reconocia "N years" / "N anos" pegados. Formas normalisimas
     como "minimum of 3 years", "at least 5 years", "3+ yrs" o
     "experiencia minima de 3 anos" no se detectaban.
  3. Con varias cifras tomaba el MINIMO. Un anuncio que pide "0-2 years of
     customer service and 5+ years of security engineering" acababa en
     'junior' cuando en realidad exige 5.

Este modulo corrige los tres puntos y ademas devuelve SIEMPRE la `evidencia`:
el fragmento literal del anuncio del que salio la cifra. Nada de cajas negras:
quien lo usa tiene que poder leer la frase y darle la razon o quitarsela al
sistema.

Es autonomo a proposito (solo depende de `normalizar()` de nucleo) para poder
integrarse en `analisis.py` sin arrastrar nada mas.

Uso:
    from experiencia import anos_exigidos
    r = anos_exigidos(vacante["titulo"], vacante["descripcion"])
    if not r["alcanzable"]:
        ...  # fuera: r["minimo"] >= 3, con r["evidencia"] para auditar
"""
from __future__ import annotations

import re
import unicodedata

try:
    from nucleo import normalizar
except Exception:  # pragma: no cover - el modulo debe poder correr aislado
    def normalizar(texto: str) -> str:
        """Copia de respaldo de nucleo.normalizar: minusculas sin acentos."""
        nfkd = unicodedata.normalize("NFKD", (texto or "").lower())
        return "".join(c for c in nfkd if not unicodedata.combining(c))


# El umbral del negocio: 3 anos o mas es inalcanzable para un perfil de
# practicas o primer empleo. Vive aqui como constante para auditarlo de un vistazo.
UMBRAL_INALCANZABLE = 3

# Nadie pide mas de 20 anos en serio; si aparece es antiguedad de la empresa
# ("in business for almost 30 years"), no un requisito al candidato.
MAX_ANOS_CREIBLE = 20

_VENTANA_ANTES = 45
_VENTANA_DESPUES = 75


# ------------------------------------------------------- normalizacion ----

_ENTIDADES = {
    "&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"',
    "&#39;": "'", "&rsquo;": "'", "&lsquo;": "'", "&ldquo;": '"',
    "&rdquo;": '"', "&ndash;": "-", "&mdash;": "-",
}

# Guiones tipograficos que las bolsas de empleo usan en los rangos: el corpus
# real trae "1-3 years" escrito con guion corto U+2013.
_GUIONES = "‐‑‒–—―−"


def _normalizar_con_mapa(texto: str) -> tuple[str, list[int]]:
    """Normaliza el texto guardando de que posicion original sale cada letra.

    Hace falta porque la evidencia debe ser el fragmento LITERAL del anuncio
    (con sus acentos y mayusculas), pero el analisis se hace sobre el texto
    normalizado. Sin el mapa, los indices de una version no valen en la otra:
    quitar acentos y expandir entidades HTML cambia las longitudes.

    Devuelve (texto_normalizado, mapa) donde mapa[i] es el indice en el texto
    original del que proviene el caracter i. El mapa lleva un centinela final
    para poder cortar hasta el ultimo caracter.
    """
    original = texto or ""
    salida: list[str] = []
    mapa: list[int] = []
    i = 0
    n = len(original)
    while i < n:
        c = original[i]

        # Entidades HTML: varios caracteres del original -> uno normalizado.
        if c == "&":
            for entidad, reemplazo in _ENTIDADES.items():
                if original.startswith(entidad, i):
                    for ch in normalizar(reemplazo):
                        salida.append(ch)
                        mapa.append(i)
                    i += len(entidad)
                    break
            else:
                salida.append("&")
                mapa.append(i)
                i += 1
            continue

        if c in _GUIONES:
            salida.append("-")
            mapa.append(i)
            i += 1
            continue

        # El corpus real trae mojibake (U+FFFD) donde habia vinetas y guiones.
        # Solo lo tratamos como separador de rango cuando esta pegado entre dos
        # digitos ("1<mojibake>3 years" era "1-3 years"); en cualquier otro
        # sitio es una vineta y vale como espacio.
        if c == "�":
            entre_digitos = (
                i > 0 and original[i - 1].isdigit()
                and i + 1 < n and original[i + 1].isdigit()
            )
            salida.append("-" if entre_digitos else " ")
            mapa.append(i)
            i += 1
            continue

        for ch in normalizar(c):
            salida.append(ch)
            mapa.append(i)
        i += 1

    mapa.append(n)
    return "".join(salida), mapa


# ------------------------------------------------------------- patrones ----

# Nucleo de una mencion de anos. Cubre, en una sola pasada:
#   "5+ years", "5 + years", "5plus years", "5 or more years", "2+ yrs",
#   "3 yr experience", "3-5 years", "3 to 5 years", "3 a 5 anos", "4 anos".
# El lookbehind evita que "2026 years" se lea como "26 years".
_RX_MENCION = re.compile(
    r"(?<!\d)(?P<n1>\d{1,2})"
    r"(?:\s*(?P<mas>\+|plus|or\s+more|or\s+greater|or\s+above|o\s+mas))?"
    r"(?:(?:\s*-\s*|\s+(?:to|a|y|and|hasta)\s+)(?P<n2>\d{1,2}))?"
    r"\s*(?P<unidad>years|year|yrs|yr|anos|ano)\b"
)

# Los numeros escritos con letra. Se detecto el 24-ago-2026: una vacante decia
# "Al menos SIETE anos de experiencia profesional" y el extractor, que solo
# leia digitos, la daba por sin requisito. Paso todos los filtros y llego a la
# cola como alcanzable.
#
# Se traducen a digitos ANTES de buscar menciones, asi el resto del modulo
# --rangos, ruido, declaraciones de "sin experiencia"-- sigue funcionando sin
# tocarlo. Solo hasta doce: por encima, quien lo escribe usa cifras.
_LETRAS = {
    "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11,
    "doce": 12,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_RX_LETRAS = re.compile(
    r"\b(" + "|".join(sorted(_LETRAS, key=len, reverse=True)) + r")\s+(?=(?:anos|ano|years|year)\b)"
)


def _cifras_en_letra(texto_n: str) -> str:
    """Reescribe 'siete anos' como '7 anos' para que el resto lo vea."""
    return _RX_LETRAS.sub(lambda m: f"{_LETRAS[m.group(1)]} ", texto_n)

# Ruido DURO: la cifra no habla de la experiencia del candidato. Se descarta
# siempre. El ancla final obliga a que la pista este pegada al numero, para
# que un "past" suelto tres frases antes no tumbe un requisito real.
_RX_RUIDO_DURO = re.compile(
    r"(?:"
    r"within|in\s+the\s+(?:last|past|next|coming)|over\s+the\s+(?:last|past)|"
    r"during\s+the\s+(?:last|past)|for\s+the\s+(?:last|past)|"
    r"the\s+(?:last|past|next|coming)|next|last|past|after|every|"
    r"up\s+to|less\s+than|under|"
    r"in\s+business\s+for|"
    r"program\s+of|programa\s+de|contrato\s+de|garantia\s+de|plan\s+de|"
    r"curso\s+de|beca\s+de|carrera\s+de|vigencia\s+de|duracion\s+de|"
    r"periodo\s+de|plazo\s+de|proyecto\s+de|visa\s+de|"
    r"ultimos?|proximos?|dentro\s+de|hace|cada|despues\s+de|antes\s+de|"
    r"hasta|menos\s+de|no\s+mas\s+de|maximo\s+de"
    r")\W{0,12}$"
)

# Ruido BLANDO: lenguaje de antiguedad ("nearly 20 years of industry
# contributions"). Solo descarta si ademas no hay ninguna palabra de
# experiencia cerca, para no perder "about 5 years of experience".
_RX_RUIDO_BLANDO = re.compile(
    r"(?:almost|nearly|about|around|approximately|casi|alrededor\s+de|"
    r"aproximadamente|mas\s+de\s+sus)\W{0,12}$"
)

# Ruido inmediatamente DESPUES de la unidad: "3 years ago", "2 years thereafter".
_RX_RUIDO_DESPUES = re.compile(r"^\W{0,3}(?:ago|atras|thereafter|en\s+adelante)\b")

# Sustantivos que nunca encabezan un requisito de experiencia laboral.
_CABEZAS_DURAS = {
    "college", "universidad", "university", "escuela", "school", "licenciatura",
    "carrera", "maestria", "posgrado", "estudios", "studies", "garantia",
    "warranty", "guarantee", "roadmap", "contributions", "contribuciones",
    "antiguedad", "tenure", "vigencia", "duracion",
}
# Mas ambiguos: solo bloquean si no hay palabra de experiencia cerca.
_CABEZAS_BLANDAS = {
    "business", "negocio", "growth", "crecimiento", "history", "historia",
    "funding", "revenue", "ingresos", "service", "servicio", "existence",
    "vida", "life", "operacion", "planning", "vision",
}

_RX_CABEZA = re.compile(
    r"^\W{0,3}(?:of|in|de|en|del|para)?\s*"
    r"(?:the\s+|la\s+|el\s+|los\s+|las\s+|un\s+|una\s+|our\s+|nuestr[oa]s?\s+)?"
    r"(?P<c1>[a-z]+)(?:\s+(?P<c2>[a-z]+))?(?:\s+(?P<c3>[a-z]+))?"
)

# Palabra de experiencia: cubre experience/experienced/experiencia de un golpe.
_RX_EXPERIENCIA = re.compile(r"experien|trayectoria|laborando|profesional")

# Formulas que marcan la cifra como requisito aunque no digan "experiencia".
_RX_CUE_REQUISITO = re.compile(
    r"(?:"
    r"minim[oa]s?(?:\s+de)?|minimum(?:\s+of)?|min\.|"
    r"at\s+least|al\s+menos|no\s+less\s+than|no\s+menos\s+de|"
    r"mas\s+de|more\s+than|over|"
    r"requier[eo]n?|requerid[oa]s?|require[sd]?|requirements?|requisitos?|"
    r"debe[sn]?\s+tener|must\s+have|should\s+have|necesita[mn]?os?|"
    r"buscamos|solicitamos|qualifications?|imprescindible|indispensable|"
    r"deseable|preferred|preferible|comprobables?|contar\s+con|"
    r"entre|between|typically"
    r")\W{0,15}$"
)

# Dominios profesionales: "5 or more years in IT systems" es un requisito
# aunque no aparezca la palabra "experience".
_DOMINIOS = (
    "it support", "it systems", "it security", "it operations",
    "it infrastructure", "soporte ti", "seguridad ti", "sistemas ti",
    "security", "seguridad", "cybersecurity", "ciberseguridad", "cyber",
    "infosec", "appsec", "soc", "grc", "pentest", "penetration testing",
    "hacking", "forensics", "engineering", "engineer", "ingenieria",
    "software", "development", "developer", "desarrollo", "devops", "sre",
    "sysadmin", "systems administration", "sistemas", "helpdesk", "help desk",
    "mesa de ayuda", "soporte tecnico", "support", "network", "networking",
    "redes", "cloud", "aws", "azure", "gcp", "data", "datos", "database",
    "analytics", "analitica", "analytical", "investigative", "research",
    "investigacion", "technology", "tecnologia", "consulting", "consultoria",
    "sales", "ventas", "marketing", "management", "gestion", "operations",
    "legal", "finance", "finanzas", "credit", "risk", "riesgo", "compliance",
    "audit", "auditoria", "qa", "testing", "machine learning", "post-sales",
)
_RX_DOMINIO = re.compile("|".join(rf"\b{re.escape(t)}\b" for t in _DOMINIOS))

# Declaracion explicita de que no se pide experiencia. Manda sobre cualquier
# cifra: si el anuncio lo dice con estas palabras, es alcanzable.
_RX_SIN_EXPERIENCIA = re.compile(
    r"no\s+(?:prior\s+|previous\s+|professional\s+|work\s+|formal\s+)?"
    r"experience\s+(?:is\s+)?(?:required|necessary|needed|expected)|"
    r"sin\s+experiencia(?:\s+(?:previa|laboral|profesional|requerida))?|"
    r"no\s+se\s+(?:requiere|necesita|pide)\s+experiencia|"
    r"no\s+(?:requiere|necesita)\s+experiencia|"
    r"no\s+es\s+necesaria?\s+(?:la\s+)?experiencia|"
    r"experiencia\s+no\s+(?:necesaria|requerida|indispensable)"
)

# Senal de practicas. 'intern' con limites de palabra para no casar con
# 'internal' ni 'international' (ese fallo ya costo caro en este sistema).
_RX_PRACTICAS = re.compile(
    r"\b(?:internship|intern|internships|becari[oa]s?|practicantes?|trainee|"
    r"aprendiz|graduate\s+program|co-?op|working\s+student|estudiante|"
    r"residencia\s+profesional|servicio\s+social|entry\s+level|entry-level|"
    r"nivel\s+inicial|recien\s+egresad[oa]s?|new\s+grad)\b|\bpracticas\b"
)


# ------------------------------------------------------------- extraccion ----

def _fragmento(original: str, mapa: list[int], texto_n: str,
               ini: int, fin: int) -> str:
    """Recorta del texto ORIGINAL el contexto de una mencion (max 120 chars)."""
    a = max(0, ini - 40)
    if a > 0:  # no cortar a media palabra
        corte = texto_n.find(" ", a, ini)
        if corte != -1:
            a = corte + 1
    b = min(len(texto_n), fin + 60)
    if b < len(texto_n):
        corte = texto_n.rfind(" ", fin, b)
        if corte != -1:
            b = corte
    bruto = original[mapa[a]:mapa[b]]
    limpio = re.sub(r"\s+", " ", bruto).strip(" -*|•")
    return limpio[:120].strip()


def _menciones(texto_n: str) -> list[dict]:
    """Todas las menciones de anos que SI son requisitos de experiencia.

    Cada mencion es {'minimo', 'maximo', 'ini', 'fin'}. Aqui vive toda la
    desambiguacion; el resto del modulo solo elige entre lo que sobrevive.
    """
    validas: list[dict] = []
    for m in _RX_MENCION.finditer(texto_n):
        n1 = int(m.group("n1"))
        n2 = int(m.group("n2")) if m.group("n2") else None
        if n1 > MAX_ANOS_CREIBLE or (n2 is not None and n2 > MAX_ANOS_CREIBLE):
            continue
        # Un rango invertido ("5 a 3") no es un rango: ignoramos el segundo.
        if n2 is not None and n2 < n1:
            n2 = None

        ini, fin = m.start(), m.end()
        antes = texto_n[max(0, ini - _VENTANA_ANTES):ini]
        despues = texto_n[fin:fin + _VENTANA_DESPUES]

        if _RX_RUIDO_DURO.search(antes):
            continue
        if _RX_RUIDO_DESPUES.match(despues):
            continue

        exp_despues = bool(_RX_EXPERIENCIA.search(despues))
        exp_antes = bool(_RX_EXPERIENCIA.search(antes))

        if _RX_RUIDO_BLANDO.search(antes) and not exp_despues:
            continue

        cabeza = _RX_CABEZA.match(despues)
        if cabeza:
            palabras = [p for p in cabeza.group("c1", "c2", "c3") if p]
            if any(p in _CABEZAS_DURAS for p in palabras):
                continue
            if palabras[0] in _CABEZAS_BLANDAS and not exp_despues:
                continue

        # Para contar como requisito hace falta al menos una senal positiva:
        # la palabra experiencia, un "+"/"or more", una formula de requisito
        # o un dominio profesional pegado a la cifra.
        positivo = (
            exp_despues or exp_antes
            or bool(m.group("mas"))
            or bool(_RX_CUE_REQUISITO.search(antes))
            or bool(_RX_DOMINIO.search(despues[:45]))
        )
        if not positivo:
            continue

        validas.append({"minimo": n1, "maximo": n2, "ini": ini, "fin": fin})
    return validas


def anos_exigidos(titulo: str, descripcion: str) -> dict:
    """Devuelve {'minimo': int|None, 'maximo': int|None, 'evidencia': str, 'alcanzable': bool, 'motivos': list[str]}."""
    original = f"{titulo or ''}\n{descripcion or ''}"
    texto_n, mapa = _normalizar_con_mapa(original)
    # "siete anos" -> "7 anos". Se hace aqui, sobre el texto ya normalizado,
    # para que todo lo que viene despues siga viendo cifras. El mapa de
    # posiciones queda desalineado en esas palabras, asi que la evidencia
    # citada puede desplazarse unos caracteres; se prefiere eso a no detectar
    # el requisito.
    texto_n = _cifras_en_letra(texto_n)

    motivos: list[str] = []
    practicas = _RX_PRACTICAS.search(texto_n)
    menciones = _menciones(texto_n)

    # 1) Declaracion explicita de "sin experiencia": manda sobre las cifras.
    sin_exp = _RX_SIN_EXPERIENCIA.search(texto_n)
    if sin_exp:
        evidencia = _fragmento(original, mapa, texto_n, sin_exp.start(), sin_exp.end())
        motivos.append("el anuncio declara que no pide experiencia previa")
        exigentes = [m for m in menciones if m["minimo"] >= UMBRAL_INALCANZABLE]
        if exigentes:
            cifras = ", ".join(str(m["minimo"]) for m in exigentes)
            motivos.append(
                f"ojo: convive con menciones de {cifras} anos; manda la declaracion explicita"
            )
        if practicas:
            motivos.append("senal de practicas/becario/trainee en el anuncio")
        return {
            "minimo": 0,
            "maximo": None,
            "evidencia": evidencia,
            "alcanzable": True,
            "motivos": motivos,
        }

    # 2) Sin ninguna mencion valida: no exige nada explicito.
    if not menciones:
        motivos.append("no se detecto exigencia explicita de anos de experiencia")
        if practicas:
            motivos.append("senal de practicas/becario/trainee en el anuncio")
        return {
            "minimo": None,
            "maximo": None,
            "evidencia": "",
            "alcanzable": True,
            "motivos": motivos,
        }

    # 3) Varias menciones: manda el MAXIMO de los minimos. Un anuncio que pide
    #    "0-2 years of customer service and 5+ years of security engineering"
    #    exige realmente 5, no 0.
    elegida = max(menciones, key=lambda m: m["minimo"])
    minimo = elegida["minimo"]
    maximo = elegida["maximo"]
    evidencia = _fragmento(original, mapa, texto_n, elegida["ini"], elegida["fin"])
    alcanzable = minimo < UMBRAL_INALCANZABLE

    if maximo is not None:
        motivos.append(f"exige de {minimo} a {maximo} anos de experiencia")
    else:
        motivos.append(f"exige un minimo de {minimo} anos de experiencia")

    if len(menciones) > 1:
        otras = len(menciones) - 1
        motivos.append(
            f"habia {len(menciones)} menciones de anos; se tomo la mas exigente "
            f"e ignoraron {otras} menos exigentes"
        )

    if alcanzable:
        motivos.append(f"alcanzable: {minimo} anos o menos esta a tu alcance")
        if practicas:
            motivos.append("senal de practicas/becario/trainee en el anuncio")
    else:
        motivos.append(
            f"no alcanzable: pide {minimo} anos o mas de experiencia profesional "
            "para un perfil de practicas o primer empleo"
        )
        if practicas:
            motivos.append(
                "menciona practicas, pero la exigencia explicita de anos manda"
            )

    return {
        "minimo": minimo,
        "maximo": maximo,
        "evidencia": evidencia,
        "alcanzable": alcanzable,
        "motivos": motivos,
    }
