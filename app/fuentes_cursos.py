"""
El vigilante de convocatorias: mira las paginas donde vuelven a abrirse.

POR QUE ESTO NO ES UN RASTREADOR. `datos_cursos.py` lo dice y tiene razon: los
cursos no tienen API ni bolsa que consultar, y una lista corta y comprobada
vale mas que un rastreador que devuelve ruido. Pero los cursos si tienen algo
que las vacantes no: **se publican siempre en el mismo sitio**. Los programas
publicos anuncian la convocatoria del ano que viene en la misma URL que la del
ano pasado.

Asi que no se rastrea el mundo: se vigilan unas pocas paginas y se avisa
cuando CAMBIAN. Es la senal mas barata que existe de "abrio algo", y ataca de frente
el unico error irreversible de este carril -- se perdio MEXIA por seis semanas
sin que nada avisara.

LAS TRES REGLAS DE ESTE MODULO

  1. **403 y 429 no son una pagina rota.** Comprobado ya en `cursos.verificar`:
     MEXIA, Saberes, la EPC, Oracle, TryHackMe y Fortinet bloquean peticiones
     automatizadas y abren perfectamente en un navegador. Un 403 se guarda como
     `inaccesible` y la semilla sigue viva. Solo el 404/410 la marca `rota`.
  2. **Lo que encuentra entra como CANDIDATO, no al catalogo.** `estado_revision
     = 'candidato'` y `origen = 'semilla:<id>'`. El catalogo de 26 entradas
     vale porque cada URL se comprobo a mano; mezclar ahi lo que saco una
     expresion regular destruye justo lo que lo hace fiable.
  3. **Una fecha solo se guarda si la pagina dice que es un cierre.** Una fecha
     suelta en una pagina puede ser el inicio del curso, la de publicacion o el
     pie de pagina. Se exige una palabra de plazo cerca ("hasta el", "cierre",
     "fecha limite"). Sin eso, `cierra` queda NULL -- que significa "no se
     sabe", nunca "no cierra".

LA CICATRIZ 13, aplicada aqui: un catalogo congelado no avisa. El sistema
estuvo SIETE DIAS sin recolectar y nada se puso rojo. Por eso `semillas` guarda
`ultima_vez` y `--estado` lo enseña: un vigilante que dejo de mirar tiene que
verse, no parecer que "no hay novedades".

Uso:
    python fuentes_cursos.py                # mira las semillas y reporta cambios
    python fuentes_cursos.py --estado       # que vio la ultima vez, sin red
    python fuentes_cursos.py --candidatos   # lo encontrado que espera revision
    python fuentes_cursos.py --aceptar ID   # pasa un candidato al catalogo
    python fuentes_cursos.py --descartar ID "motivo"
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from almacen import conexion              # noqa: E402
from nucleo import ahora_iso, normalizar  # noqa: E402

# ---------------------------------------------------------------------------
# LAS SEMILLAS
#
# Cada una es una pagina donde una convocatoria util para un estudiante de
# carrera afin vuelve a abrirse. Los campos `area`, `gratis` y `publico` NO los
# adivina el codigo: los declara esta lista, escrita a mano, igual que
# `datos_cursos.py`. Lo unico que el codigo saca de la pagina es si cambio, que
# titulos aparecen y si hay una fecha de cierre declarada.
#
# `pistas` son las palabras que hacen que un enlace de esa pagina merezca
# mirarse. Sin ellas, cualquier menu de navegacion entraria como candidato.
# ---------------------------------------------------------------------------
SEMILLAS = [
    {
        "id": "mexia",
        "nombre": "MEXIA / Centro Publico de Formacion en IA",
        # La URL de la convocatoria, no la portada: es la que hay que vigilar
        # y la que ya esta comprobada en `datos_cursos.py`.
        # Responde 403 a peticiones automatizadas -- eso es `inaccesible`, no
        # una pagina rota, y abre bien en un navegador.
        "url": "https://www.mexia.gob.mx/convocatoria/",
        "institucion": "Gobierno de Mexico",
        "area": "ia", "gratis": "beca", "publico": "estudiantes",
        "pistas": ["convocatoria", "registro", "inscripcion", "postula", "beca"],
        # El mejor programa gratuito de la lista, y su 2a convocatoria se
        # perdio por no vigilarla.
    },
    {
        "id": "samsung-innovation-campus",
        "nombre": "Samsung Innovation Campus - sede Nuevo Leon",
        # La sede, no el portal global de Samsung: `samsung.com/mx/campus/` da
        # 404 (comprobado el 4-sep-2026). Esta es la que recibe la postulacion
        # y la que ya figura verificada en el catalogo.
        "url": "https://samsunginnovationcampus.udem.edu.mx/",
        "institucion": "Samsung Mexico / UDEM",
        "area": "ia", "gratis": "total", "publico": "estudiantes",
        "pistas": ["convocatoria", "registro", "inscripcion", "campus", "curso"],
    },
    {
        "id": "cisco-netacad",
        "nombre": "Cisco Networking Academy - cursos gratuitos",
        "url": "https://www.netacad.com/catalogs/learn",
        "institucion": "Cisco",
        "area": "redes", "gratis": "total", "publico": "abierto",
        "pistas": ["cybersecurity", "networking", "python", "course", "curso"],
    },
    {
        "id": "capacitate-empleo",
        "nombre": "Capacitate para el Empleo (Fundacion Carlos Slim)",
        "url": "https://capacitateparaelempleo.org/",
        "institucion": "Fundacion Carlos Slim",
        "area": "general", "gratis": "total", "publico": "abierto",
        "pistas": ["curso", "tecnologia", "informatica", "redes", "seguridad"],
    },
    {
        "id": "becas-santander",
        "nombre": "Becas Santander - tecnologia",
        # becas-santander.com redirige a santanderopenacademy.com desde 2025;
        # se guarda el destino para no depender de que el redirector siga vivo.
        "url": "https://app.santanderopenacademy.com/es/search?q=tecnologia",
        "institucion": "Santander Universidades",
        "area": "general", "gratis": "beca", "publico": "estudiantes",
        "pistas": ["beca", "programa", "tecnologia", "digital", "convocatoria"],
    },
    # Aqui van las paginas de becas y convocatorias de TU universidad y de tu
    # facultad: suelen ser las que mas convocatorias a tu medida publican. No
    # vienen de fabrica porque dependen de donde estudies. Mismo formato:
    #   {"id": "mi-universidad-becas", "nombre": "...", "url": "https://...",
    #    "institucion": "...", "area": "general", "gratis": "beca",
    #    "publico": "estudiantes", "pistas": ["convocatoria", "beca", "registro"]},
    {
        "id": "google-grow",
        "nombre": "Google - certificados de carrera (Grow with Google)",
        "url": "https://grow.google/certificates/",
        "institucion": "Google",
        "area": "general", "gratis": "beca", "publico": "abierto",
        "pistas": ["cybersecurity", "data analytics", "it support", "certificate"],
    },
    {
        "id": "ibm-skillsbuild",
        "nombre": "IBM SkillsBuild para estudiantes",
        "url": "https://skillsbuild.org/students",
        "institucion": "IBM",
        "area": "ia", "gratis": "total", "publico": "estudiantes",
        "pistas": ["cybersecurity", "artificial intelligence", "credential", "course"],
    },
    {
        "id": "fortinet-nse",
        "nombre": "Fortinet Training Institute - programa academico",
        "url": "https://www.fortinet.com/training/cybersecurity-professionals",
        "institucion": "Fortinet",
        "area": "ciberseguridad", "gratis": "total", "publico": "abierto",
        "pistas": ["free", "certification", "fcf", "fcp", "training"],
    },
    {
        "id": "conahcyt",
        "nombre": "Secihti / Conahcyt - convocatorias",
        "url": "https://secihti.mx/convocatorias/",
        "institucion": "Gobierno de Mexico",
        "area": "general", "gratis": "beca", "publico": "estudiantes",
        "pistas": ["convocatoria", "beca", "estancia", "verano", "formacion"],
    },
    {
        # Sustituye a una semilla de nl.gob.mx que se probo el 4-sep-2026 y dio
        # 404 en las cuatro rutas plausibles. Antes que dejar una URL inventada
        # --que llenaria el parte de "rota" todas las semanas sin aportar
        # nada-- se vigila Saberes, que es donde el gobierno publica de verdad
        # la formacion en IA y ya esta comprobada en `datos_cursos.py`.
        "id": "saberes-cfia",
        "nombre": "Saberes MX - Escuela Publica de Codigo / CFIA",
        "url": "https://saberes.gob.mx/cms/index.php/cfia",
        "institucion": "Gobierno de Mexico",
        "area": "ia", "gratis": "total", "publico": "abierto",
        "pistas": ["convocatoria", "curso", "registro", "inscripcion",
                   "programa", "codigo", "inteligencia"],
    },
]

CABECERAS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0 Safari/537.36"),
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
}

# ---------------------------------------------------------------------------
# Fechas de cierre.
#
# Regla 3 del modulo: una fecha suelta no es un plazo. Solo se acepta si a su
# izquierda, en una ventana corta, hay una palabra que la declare como cierre.
# El coste de equivocarse aqui es alto en las dos direcciones: inventar un
# plazo mete prisa falsa; perderlo repite lo de MEXIA.
# ---------------------------------------------------------------------------
MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5,
         "junio": 6, "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9,
         "octubre": 10, "noviembre": 11, "diciembre": 12}

PALABRA_DE_PLAZO = re.compile(
    r"(hasta el|hasta las|cierre|cierra|fecha limite|fecha de cierre|vence|"
    r"ultimo dia|limite de registro|registro hasta|inscripciones hasta|"
    r"deadline|closes on|apply by)", re.I)

FECHA_LARGA = re.compile(
    r"(\d{1,2})\s+de\s+(" + "|".join(MESES) + r")(?:\s+(?:de|del)\s+(\d{4}))?",
    re.I)
FECHA_CORTA = re.compile(r"(\d{1,2})[/-](\d{1,2})[/-](20\d{2})")

# Cuantos caracteres antes de la fecha se miran buscando la palabra de plazo.
# 90 sale de leer las convocatorias reales: "Las inscripciones estaran abiertas
# hasta el 18 de septiembre" cabe de sobra; un parrafo entero, no.
VENTANA_PLAZO = 90


def _texto_plano(html: str) -> str:
    """Quita script, style y etiquetas. No pretende ser un parser: solo deja
    el texto legible para buscar fechas y titulos."""
    sin = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    sin = re.sub(r"(?s)<[^>]+>", " ", sin)
    sin = sin.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", sin).strip()


def buscar_cierre(texto: str) -> str | None:
    """La primera fecha que la pagina declara como plazo, en ISO. None si no
    hay ninguna: NULL significa 'no se sabe', jamas 'no cierra'."""
    candidatas: list[str] = []
    for m in FECHA_LARGA.finditer(texto):
        antes = texto[max(0, m.start() - VENTANA_PLAZO):m.start()]
        if not PALABRA_DE_PLAZO.search(antes):
            continue
        dia = int(m.group(1))
        mes = MESES[m.group(2).lower()]
        anio = int(m.group(3)) if m.group(3) else None
        if anio is None:
            # Sin ano explicito no se completa con el actual: en septiembre,
            # "hasta el 15 de febrero" casi siempre es del ano siguiente y
            # adivinarlo produce un plazo vencido que esconde la convocatoria.
            continue
        candidatas.append(f"{anio:04d}-{mes:02d}-{dia:02d}")
    for m in FECHA_CORTA.finditer(texto):
        antes = texto[max(0, m.start() - VENTANA_PLAZO):m.start()]
        if not PALABRA_DE_PLAZO.search(antes):
            continue
        dia, mes, anio = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mes <= 12 and 1 <= dia <= 31:
            candidatas.append(f"{anio:04d}-{mes:02d}-{dia:02d}")
    return sorted(candidatas)[0] if candidatas else None


# ---------------------------------------------------------------------------
# EL FILTRO DE RUIDO
#
# Medido, no supuesto: la primera corrida (4-sep-2026) saco 40 candidatos y
# solo ~16 eran algo a lo que un estudiante pueda inscribirse. El resto era
# navegacion del sitio -- "Authorized Training Center", "Overview", "Portal"--
# y hasta una direccion de correo colada como si fuera el nombre de un curso.
# Una cola de revision con 60% de basura no se revisa: se abandona.
#
# El filtro es ESTRUCTURAL a proposito, no tematico. La cicatriz 29 avisa de lo
# contrario: "promocion" tambien significa generacion de egresados en Mexico y
# ese filtro tiraba la convocatoria de MEXIA. Aqui no se descarta por tema --de
# eso se encarga `formacion.evaluar`, que ademas deja el motivo escrito-- sino
# por lo que un enlace ES: un directorio, una portada, un correo.
#
# CONTROLES NEGATIVOS, casos que DEBEN sobrevivir a este filtro. Estan en
# `test_formacion.py` y se ejecutan: sin ellos, un filtro de descarte solo se
# comprueba el dia que ya tiro algo bueno.
# ---------------------------------------------------------------------------
RUIDO = [
    # Directorios y paginas de "donde encontrar", no cosas a las que inscribirse
    "authorized training center", "authorized training centers",
    "find an authorized", "training center",
    # Navegacion pura
    "overview", "portal", "codigo de honor", "code of honor", "aviso de privacidad",
    "preguntas frecuentes", "mapa del sitio", "iniciar sesion", "log in",
    "ver mas", "leer mas", "read more", "conoce mas",
    # Material comercial
    "product demo", "free product demo", "solicitar demo", "contactar a ventas",
    "digital credentials",
    # Encabezados de seccion. Solo caen por IGUALDAD EXACTA --la regla de abajo
    # lo garantiza-- asi que "Free Training & On-demand Labs" y "Becas
    # Nacionales" sobreviven, y estan en el test para probarlo. Entraron al
    # bajar el minimo de longitud de 12 a 6 caracteres, que es lo que recupero
    # "IT Support"; el intercambio se midio: dos etiquetas por una pista real.
    "cursos", "curso", "training", "courses", "convocatorias", "becas",
    "programas", "certificaciones", "capacitacion",
]

# Un enlace cuyo texto es una direccion de correo no es un curso. Salio
# literal en la primera corrida: "innovationcampus@udem.edu.mx".
ES_CORREO = re.compile(r"^[^\s@]+@[^\s@]+\.[a-z]{2,}$", re.I)


def es_ruido(titulo: str) -> tuple[bool, str]:
    """Dice si un enlace es navegacion del sitio en vez de algo inscribible.

    Devuelve (es_ruido, motivo) para que el descarte quede explicado: un
    descarte sin motivo se repite.
    """
    limpio = (titulo or "").strip()
    if ES_CORREO.match(limpio):
        return True, "es una direccion de correo, no un curso"
    n = normalizar(limpio)
    for patron in RUIDO:
        # Se exige que el patron sea el texto ENTERO o casi: "training center"
        # dentro de "Fortinet Training Center Program de becas" no deberia
        # descartar. Con `==` o con el patron ocupando la mayor parte, si.
        if n == patron or (patron in n and len(patron) >= len(n) - 12):
            return True, f"navegacion del sitio, no una convocatoria ('{patron}')"
    # NO hay regla de "titulo demasiado corto". Se escribio, se probo el
    # 4-sep-2026 y tiro "Cybersecurity" -- el enlace al Google Cybersecurity
    # Certificate, uno de los dos mejores candidatos de toda la corrida. Un
    # titulo pobre no es ruido: el ruido es lo que el enlace HACE, y un enlace
    # de una palabra puede llevar perfectamente a una certificacion. Queda
    # escrito para que nadie la vuelva a anadir por parecer razonable.
    return False, ""


def _titulos_candidatos(html: str, pistas: list[str]) -> list[tuple[str, str]]:
    """Enlaces cuyo texto menciona alguna pista. Devuelve (texto, url)."""
    salida: list[tuple[str, str]] = []
    vistos = set()
    for m in re.finditer(r'(?is)<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html):
        href, dentro = m.group(1), _texto_plano(m.group(2))
        # El minimo era 12 caracteres, y el `jefe` senalo la contradiccion: dos
        # funciones mas arriba hay un comentario largo jurando que NO existe
        # una regla de "titulo demasiado corto" porque tiraba "Cybersecurity"
        # ... que sobrevivia por UN caracter. "IT Support" (10) y "Beca IA" (7)
        # se caian aqui, en silencio y sin motivo escrito, antes de llegar a la
        # base -- y `it support` es una de las pistas declaradas de la semilla
        # de Google. Un descarte que no deja rastro no se puede auditar.
        #
        # Ahora el minimo solo quita lo que no puede ser un nombre ("Ver", "+"),
        # y de decidir se encarga `es_ruido`, que escribe el porque.
        if not dentro or len(dentro) < 6 or len(dentro) > 130:
            continue
        n = normalizar(dentro)
        if not any(p in n for p in pistas):
            continue
        if n in vistos:
            continue
        ruido, _motivo = es_ruido(dentro)
        if ruido:
            continue
        vistos.add(n)
        salida.append((dentro.strip(), href))
    return salida[:12]


def _absoluta(base: str, href: str) -> str:
    if href.startswith("http"):
        return href
    from urllib.parse import urljoin
    return urljoin(base, href)


def _id_curso(nombre: str, institucion: str) -> str:
    return hashlib.sha1(normalizar(f"{institucion}|{nombre}").encode("utf-8")
                        ).hexdigest()[:16]


def revisar(solo: str | None = None, guardar_candidatos: bool = True) -> dict:
    """Mira cada semilla y reporta lo que cambio.

    Devuelve el parte, no lo imprime: lo consume tambien `arranque.py`.
    """
    import httpx

    semillas = [s for s in SEMILLAS if not solo or s["id"] == solo]
    ahora = ahora_iso()
    parte = {"revisadas": 0, "cambiaron": [], "inaccesibles": [], "rotas": [],
             "candidatos_nuevos": 0}

    with conexion() as con:
        previas = {r["id"]: dict(r) for r in con.execute("SELECT * FROM semillas")}

    resultados = []
    candidatos: list[dict] = []
    with httpx.Client(follow_redirects=True, timeout=30, headers=CABECERAS) as cli:
        for s in semillas:
            parte["revisadas"] += 1
            try:
                r = cli.get(s["url"])
                codigo = r.status_code
                cuerpo = r.text
            except Exception as e:
                resultados.append((s, "inaccesible", None,
                                   f"fallo la peticion: {type(e).__name__}",
                                   None, None))
                parte["inaccesibles"].append(s["nombre"])
                continue

            if codigo in (404, 410):
                # Lo unico autoritativo. Cicatriz 4: solo el 404/410 cierra.
                resultados.append((s, "rota", codigo,
                                   f"la pagina ya no existe ({codigo})", None, None))
                parte["rotas"].append(f"{s['nombre']} ({codigo})")
                continue
            if codigo in (403, 429) or codigo != 200:
                resultados.append((s, "inaccesible", codigo,
                                   f"el sitio no deja leer automaticamente ({codigo}); "
                                   "casi seguro abre bien en el navegador", None, None))
                parte["inaccesibles"].append(f"{s['nombre']} ({codigo})")
                continue

            texto = _texto_plano(cuerpo)
            # La huella se calcula sobre el TEXTO, no sobre el HTML: media web
            # mete un identificador de sesion o una marca de tiempo en el
            # marcado y entonces todo "cambia" cada dia y el aviso deja de
            # significar nada.
            huella = hashlib.sha1(texto.encode("utf-8")).hexdigest()
            previa = previas.get(s["id"])
            cambio = bool(previa and previa.get("huella") and previa["huella"] != huella)
            cierre = buscar_cierre(texto)

            if cambio:
                parte["cambiaron"].append({"nombre": s["nombre"], "url": s["url"],
                                           "cierra": cierre})
            resultados.append((s, "viva", codigo,
                               "responde y se pudo leer", huella,
                               ahora if cambio else (previa or {}).get("ultimo_cambio")))

            if guardar_candidatos:
                for titulo, href in _titulos_candidatos(cuerpo, s["pistas"]):
                    candidatos.append({
                        "id": _id_curso(titulo, s["institucion"]),
                        "nombre": titulo,
                        "institucion": s["institucion"],
                        "url": _absoluta(s["url"], href),
                        "area": s["area"], "gratis": s["gratis"],
                        "publico": s["publico"],
                        "modalidad": "linea",
                        "cierra": cierre,
                        "descripcion": f"Encontrado en {s['nombre']} ({s['url']}). "
                                       "Sin comprobar: hay que abrirlo y leer las bases.",
                        "origen": f"semilla:{s['id']}",
                    })

    with conexion() as con:
        huerfanas = _limpiar_huerfanas(con)
        if huerfanas:
            parte["huerfanas_borradas"] = huerfanas
        for s, estado, http, detalle, huella, ultimo_cambio in resultados:
            anterior = previas.get(s["id"]) or {}
            cambios = (anterior.get("cambios") or 0) + (1 if ultimo_cambio and
                       ultimo_cambio == ahora else 0)
            con.execute("""
                INSERT INTO semillas (id, nombre, url, institucion, huella, estado,
                                      http, detalle, ultimo_cambio, cambios,
                                      primera_vez, ultima_vez)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    nombre=excluded.nombre, url=excluded.url, estado=excluded.estado,
                    http=excluded.http, detalle=excluded.detalle,
                    -- Si esta corrida no pudo leer, se CONSERVA la huella previa.
                    -- Sobrescribirla con NULL haria que la siguiente lectura
                    -- buena pareciera "sin cambios" y el aviso se perderia.
                    huella=COALESCE(excluded.huella, semillas.huella),
                    ultimo_cambio=COALESCE(excluded.ultimo_cambio, semillas.ultimo_cambio),
                    cambios=excluded.cambios,
                    ultima_vez=excluded.ultima_vez
                """, (s["id"], s["nombre"], s["url"], s["institucion"], huella,
                      estado, http, detalle, ultimo_cambio, cambios, ahora, ahora))

        # Los candidatos entran SOLO si no existen ya. Un curso que ya se
        # acepto o descarto no vuelve a la cola de revision cada semana:
        # eso es exactamente el ruido que mata un vigilante.
        for c in candidatos:
            hay = con.execute("SELECT id FROM cursos WHERE id=?", (c["id"],)).fetchone()
            if hay:
                con.execute("UPDATE cursos SET ultima_vez=? WHERE id=?",
                            (ahora, c["id"]))
                continue
            # La elegibilidad se calcula YA, al entrar, y no cuando alguien
            # acepte el candidato. No es adelantar trabajo: es lo que ordena la
            # cola de revision. Sin esto, "Estancias Posdoctorales" y
            # "Rotaciones Medicas" --las dos salieron en la primera corrida--
            # esperan turno junto a la convocatoria que si le sirve.
            #
            # Se llama a `formacion.evaluar` en vez de repetir aqui las reglas:
            # dos filtros que dicen lo mismo con palabras distintas acaban
            # discrepando, y este proyecto ya pago esa factura con los filtros
            # duplicados del panel.
            import formacion
            elegible, motivo = formacion.evaluar(c)
            con.execute("""
                INSERT INTO cursos (id, nombre, institucion, url, area, gratis,
                                    publico, modalidad, cierra, descripcion,
                                    origen, estado_revision, convocatoria,
                                    elegible, elegible_motivo,
                                    primera_vez, ultima_vez)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,'candidato','abierta',?,?,?,?)
                """, (c["id"], c["nombre"], c["institucion"], c["url"], c["area"],
                      c["gratis"], c["publico"], c["modalidad"], c["cierra"],
                      c["descripcion"], c["origen"], elegible, motivo,
                      ahora, ahora))
            parte["candidatos_nuevos"] += 1
    return parte


def estado() -> list[dict]:
    """Que vio el vigilante la ultima vez, y cual no esta vigilada de verdad.

    LA COLUMNA QUE IMPORTA es `vigilada`, y la puso el `jefe` el 4-sep-2026 con
    una observacion que dejaba el modulo en evidencia: la deteccion de cambios
    compara la huella nueva con la previa, y **de un 403 no sale huella**. MEXIA
    responde 403. Luego MEXIA no tendra huella nunca, luego el vigilante no
    podra avisar jamas de que MEXIA abrio convocatoria -- y este modulo existe,
    con esas palabras en su cabecera, porque se perdio MEXIA por seis semanas.

    Decir "solo MEXIA da 403, que es inaccesible y no rota" era cierto y
    tranquilizador de mas. Una fuente sin huella hay que mirarla A MANO, y eso
    tiene que estar escrito donde se lee el estado, no en la cabeza de nadie.
    """
    with conexion() as con:
        filas = [dict(r) for r in con.execute(
            "SELECT * FROM semillas ORDER BY estado, nombre")]
    vigentes = {s["id"] for s in SEMILLAS}
    salida = []
    for s in filas:
        if s["id"] not in vigentes:
            continue          # huerfana: ya no se consulta (ver `_limpiar_huerfanas`)
        s["vigilada"] = bool(s.get("huella"))
        salida.append(s)
    return salida


def _limpiar_huerfanas(con) -> list[str]:
    """Borra las semillas que ya no estan en `SEMILLAS`.

    `nl-talento` se sustituyo por `saberes-cfia` y su fila se quedo, con un
    404 rojo y permanente que ninguna corrida podia arreglar porque ya nadie
    la consultaba. Es justo la alarma que se aprende a ignorar de la cicatriz
    13, y la que hace que el dia que se ponga roja una de verdad tampoco se
    mire. Una fuente que ya no se vigila no es una fuente rota: no es una
    fuente.
    """
    vigentes = {s["id"] for s in SEMILLAS}
    fuera = [r["id"] for r in con.execute("SELECT id FROM semillas")
             if r["id"] not in vigentes]
    for i in fuera:
        con.execute("DELETE FROM semillas WHERE id=?", (i,))
    return fuera


def candidatos(limite: int = 40) -> list[dict]:
    """Lo encontrado que espera revision, ordenado por si le sirve.

    El orden pone ABAJO lo que ya se sabe que no cabe, y arriba lo que tiene
    plazo. No pone arriba los `elegible=1`, y esa es una correccion del
    4-sep-2026: mientras la elegibilidad de un candidato se dedujera del titulo
    --que es lo que hacia-- ordenar por ella era ordenar por ruido. Ahora un
    candidato sin leer vale NULL, asi que ordenar por elegibilidad separaria
    solo los descartados, que es exactamente lo que se quiere.

    (Ademas, el `CASE elegible WHEN NULL` que habia aqui no funcionaba: en SQL
    nada es igual a NULL, ni NULL. Se compara con `IS NULL`.)
    """
    with conexion() as con:
        return [dict(r) for r in con.execute(
            "SELECT id, nombre, institucion, url, area, cierra, origen, "
            "       elegible, elegible_motivo "
            "FROM cursos WHERE estado_revision='candidato' "
            "ORDER BY (elegible IS NOT NULL AND elegible = 0), "
            "         (cierra IS NULL), cierra ASC LIMIT ?",
            (limite,))]


def limpiar_candidatos() -> dict:
    """Pasa el filtro de ruido por lo ya guardado.

    Existe porque un filtro nuevo no puede dejar intacta la basura que entro
    antes de escribirlo: se quedaria en la cola para siempre, y una cola con
    basura vieja se abandona igual que una con basura nueva. No borra filas --
    las marca `descartado` con el motivo, para que el mismo enlace no vuelva a
    proponerse en la siguiente corrida.
    """
    tirados = []
    with conexion() as con:
        filas = [dict(r) for r in con.execute(
            "SELECT id, nombre FROM cursos WHERE estado_revision='candidato'")]
        for f in filas:
            ruido, motivo = es_ruido(f["nombre"])
            if ruido:
                con.execute("""UPDATE cursos SET estado_revision='descartado',
                               descartado_motivo=?, ultima_vez=? WHERE id=?""",
                            (motivo, ahora_iso(), f["id"]))
                tirados.append(f"{f['nombre'][:44]} -> {motivo}")
    return {"revisados": len(filas), "descartados": len(tirados), "detalle": tirados}


def aceptar(curso_id: str) -> dict:
    """Pasa un candidato al catalogo y le calcula elegibilidad y puntuacion."""
    import cursos as mod_cursos
    import formacion
    with conexion() as con:
        fila = con.execute("SELECT * FROM cursos WHERE id=?", (curso_id,)).fetchone()
        if not fila:
            return {"error": f"no existe {curso_id}"}
        c = dict(fila)
        puntuado = mod_cursos.puntuar(c)
        elegible, motivo = formacion.evaluar(c)
        con.execute("""UPDATE cursos SET estado_revision='aceptado', score=?,
                       motivos=?, brecha=?, elegible=?, elegible_motivo=?,
                       ultima_vez=? WHERE id=?""",
                    (puntuado["score"],
                     __import__("json").dumps(puntuado["motivos"], ensure_ascii=False),
                     puntuado["brecha"], elegible, motivo, ahora_iso(), curso_id))
    return {"id": curso_id, "nombre": c["nombre"], "score": puntuado["score"],
            "elegible": elegible, "motivo": motivo}


def descartar(curso_id: str, motivo: str) -> dict:
    if not (motivo or "").strip():
        return {"error": "un descarte sin motivo se repite: escribe por que"}
    with conexion() as con:
        cur = con.execute("""UPDATE cursos SET estado_revision='descartado',
                             descartado_motivo=?, ultima_vez=? WHERE id=?""",
                          (motivo, ahora_iso(), curso_id))
        if cur.rowcount == 0:
            return {"error": f"no existe {curso_id}"}
    return {"id": curso_id, "estado_revision": "descartado", "motivo": motivo}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--estado", action="store_true", help="lo ultimo que vio, sin red")
    p.add_argument("--candidatos", action="store_true")
    p.add_argument("--solo", metavar="ID_SEMILLA")
    p.add_argument("--sin-candidatos", action="store_true",
                   help="solo vigila cambios; no propone nada")
    p.add_argument("--aceptar", metavar="CURSO_ID")
    p.add_argument("--descartar", nargs=2, metavar=("CURSO_ID", "MOTIVO"))
    p.add_argument("--limpiar", action="store_true",
                   help="pasa el filtro de ruido por los candidatos ya guardados")
    args = p.parse_args()

    if args.limpiar:
        r = limpiar_candidatos()
        print(f"revisados {r['revisados']}, descartados {r['descartados']}")
        for d in r["detalle"]:
            print("  -", d)
        sys.exit(0)

    if args.estado:
        lista = estado()
        for s in lista:
            marca = {"viva": "ok ", "inaccesible": "?? ", "rota": "XX "}.get(
                s["estado"] or "", "   ")
            print(f"{marca}{s['nombre'][:46]:46} | visto {(s['ultima_vez'] or '')[:16]}"
                  f" | cambios: {s['cambios'] or 0}")
            if s["estado"] != "viva":
                print(f"      {s['detalle']}")
        ciegas = [s for s in lista if not s["vigilada"]]
        if ciegas:
            print("\nSIN VIGILANCIA REAL (nunca se pudo leer, asi que un cambio"
                  " suyo NO se detectaria; hay que abrirlas a mano):")
            for s in ciegas:
                print(f"  - {s['nombre']}\n    {s['url']}")
    elif args.candidatos:
        lista = candidatos()
        print(f"\n{len(lista)} candidatos esperando revision\n")
        for c in lista:
            print(f"  [{c['id']}] {c['nombre'][:56]:56} | {c['institucion'][:18]:18}"
                  f" | {c['cierra'] or 'sin plazo'}")
    elif args.aceptar:
        print(aceptar(args.aceptar))
    elif args.descartar:
        print(descartar(args.descartar[0], args.descartar[1]))
    else:
        parte = revisar(solo=args.solo, guardar_candidatos=not args.sin_candidatos)
        print(f"\nRevisadas {parte['revisadas']} semillas."
              f" Candidatos nuevos: {parte['candidatos_nuevos']}")
        if parte["cambiaron"]:
            print("\nCAMBIARON (mirar: puede haber convocatoria nueva):")
            for c in parte["cambiaron"]:
                plazo = f" | cierre declarado: {c['cierra']}" if c["cierra"] else ""
                print(f"  - {c['nombre']}{plazo}\n    {c['url']}")
        else:
            print("Ninguna cambio desde la ultima revision.")
        if parte["inaccesibles"]:
            print("\nNo dejaron leer (NO es que esten cerradas):")
            for x in parte["inaccesibles"]:
                print(f"  - {x}")
        if parte["rotas"]:
            print("\nROTAS (404/410, hay que sustituir la URL):")
            for x in parte["rotas"]:
                print(f"  - {x}")
