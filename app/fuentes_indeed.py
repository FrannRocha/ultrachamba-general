"""
Fuente Indeed México.

POR QUÉ NO SE RASPA EL HTML. Se probaron las cuatro vías el 2026-08-16, con
peticiones reales desde esta máquina, y todas están cerradas:

    https://mx.indeed.com/jobs?q=...&l=...      -> 403 (Cloudflare + captcha)
    https://mx.indeed.com/m/jobs?q=...&l=...    -> 403 (Cloudflare + captcha)
    https://mx.indeed.com/viewjob?jk=...        -> 403 (Cloudflare + captcha)
    https://mx.indeed.com/                      -> 403 (Cloudflare + captcha)
    https://mx.indeed.com/rss?q=...&l=...       -> 404 (el feed RSS ya no existe)
    https://mx.indeed.com/jobs?...&format=rss   -> 403

El 403 llega con la interstitial de Cloudflare, no con una página de resultados
degradada: cambiar el User-Agent a móvil no lo evita. Raspar ese HTML exigiría
proxies residenciales de pago y un resolvedor de captcha. No hace falta.

LA VÍA QUE SÍ FUNCIONA. Indeed expone la misma búsqueda por la API GraphQL que
consume su propia aplicación móvil:

    POST https://apis.indeed.com/graphql        -> 200, JSON limpio

Es la técnica que usa `speedyapply/JobSpy` (MIT), adaptada aquí: no se copió su
archivo, se tomó el endpoint, la forma de la consulta y el par de cabeceras que
la identifican como la app de iOS. Ventajas sobre raspar HTML: devuelve la
descripción completa (1.000-4.000 caracteres), el salario ya estructurado, la
fecha de publicación y la URL directa del ATS de la empresa. Nada de eso está
en las tarjetas de resultados que se raspan en OCC o Computrabajo.

MEDICIONES REALES (2026-08-16, esta máquina, sin proxy):
  - 54 peticiones secuenciales: 16,4 s -> 0,30 s por petición, 100% HTTP 200.
  - 40 peticiones con concurrencia 40: 0,6 s, 40/40 HTTP 200, ningún 429.
  - 12 peticiones (6 consultas x 2 zonas, limit 100): 950 vacantes únicas.
  - Paginación por cursor 'practicante'/Monterrey: 728 únicas en 8 páginas,
    cero repetidas.

LÍMITES QUE HAY QUE CONOCER:
  - `limit` tope 100 por petición.
  - NO hay desplazamiento numérico. Se probaron `offset`, `start`, `from`,
    `skip` y `page`: los cinco responden 400 "Unknown argument". La única
    paginación es `cursor`, que es SECUENCIAL: para pedir la página 2 hace
    falta haber leído la 1. La introspección del esquema está deshabilitada.
  - La clave de API es obligatoria (sin ella: 401 "An API Key is required") y
    solo viaja por CABECERA. Reverificado el 2026-08-16 con DIEZ nombres de
    parámetro (api-key, apiKey, api_key, key, indeed-api-key, indeed_api_key,
    indeedApiKey, apikey, access_token, token): los diez responden 401. El
    método GET da 405.
  - El país viaja por query string `?co=MX` O por la cabecera `indeed-co: MX`,
    pero NUNCA por las dos a la vez: mandar ambas responde 400 "Both
    'indeed-co' header and URL query parameter are present". En minúsculas
    ('mx') también responde 400.
  - El `user-agent` de la app es obligatorio. Medido quitando las cabeceras de
    una en una: de las nueve, solo dos cambian el resultado — sin
    `indeed-api-key` es 401, y sin `user-agent` es 403 con el HTML de
    Cloudflare en vez de JSON. El UA de Chrome que fija `red.py` también da
    403: no basta con añadir la clave, hay que SUSTITUIR el user-agent.
  - Los términos largos filtran en AND y se quedan sin resultados en el área
    metropolitana: "practicante ciberseguridad" da 0 en Monterrey y 6 a nivel
    nacional, mientras que "ciberseguridad" da 38 y "seguridad informatica" 65.
    Por eso las consultas locales son deliberadamente amplias: el cribado fino
    lo hace `analisis.py`, no la búsqueda.
  - El atributo VDTG7 (prácticas) NO APARECE NUNCA en las respuestas de
    México: cero veces en 1.215 vacantes inspeccionadas el 2026-08-16. Las
    claves que sí se pueblan son CPAHG ("Aprendiz", 93/715) y 4BQ7N ("Empleos
    para estudiantes", 101/715). El remoto sí tenía la clave correcta: DSQF7
    es "Home Office (Desde casa)" y sale en 104 de 500 vacantes. Aun así el
    cribado fino de nivel lo hace `analisis.py` sobre el texto; estos
    atributos son solo una señal de apoyo.

RITMO recomendado para el diccionario `RITMO` de `red.py` (no lo edito yo,
hay otros agentes trabajando en paralelo):

    "apis.indeed.com": (6, 0.15),

Justificación: NO se observó limitación de tasa — 40 peticiones simultáneas
pasaron todas con 200 en 0,6 s, así que el límite técnico está muy por encima
de lo que este sistema necesita. El valor conservador no es por miedo al 429
local sino porque la clave de la app es COMPARTIDA por todos los usuarios de
JobSpy: si se la castiga, se revoca para todos y esta fuente muere. Con (6,
0.15) una corrida completa de ~180 peticiones tarda unos 30 s, que sobra.
Si alguna vez aparecen 429, bajar a (3, 0.40).
"""
from __future__ import annotations

import dataclasses
import json
import time

import httpx

import areas
import config
from nucleo import log, vacante
from red import Peticion, Respuesta

# --------------------------------------------------------------- endpoint ----

API = "https://apis.indeed.com/graphql"

# Estas cabeceras identifican la petición como la app de iOS de Indeed.
#
# LA CLAVE NO VIVE EN EL CÓDIGO. Es la de la aplicación móvil pública de Indeed
# (la documenta el proyecto MIT JobSpy), pero una clave escrita en un
# repositorio público la marcan los escáneres de secretos y ata el proyecto a
# un uso que Indeed no ha autorizado por escrito. Se configura en
# `INDEED_API_KEY` (ver `.env.example`); sin ella esta fuente queda desactivada
# y lo dice en el log, en vez de mandar peticiones que responderían 401.
def cabeceras(pais_en_cabecera: bool = True) -> dict:
    """Cabeceras de la app. Sin `indeed-co` ni `Host` si el país va en la URL.

    No es un detalle de estilo: mandar la cabecera `indeed-co` y el parámetro
    `?co=MX` a la vez hace que la API responda 400 y devuelva cero vacantes.
    `Host` lo deduce httpx de la URL.
    """
    c = {
        "Host": "apis.indeed.com",
        "content-type": "application/json",
        "indeed-api-key": config.indeed_api_key(),
        "accept": "application/json",
        "indeed-locale": "es-MX",
        "accept-language": "es-MX,es;q=0.9,en;q=0.8",
        "user-agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6_1 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Indeed App 193.1"
        ),
        "indeed-app-info": "appv=193.1; appid=com.indeed.jobsearch; osv=16.6.1; os=ios; dtype=phone",
        "indeed-co": "MX",
    }
    if not pais_en_cabecera:
        c = {k: v for k, v in c.items() if k not in ("indeed-co", "Host")}
    return c


def activa() -> bool:
    """¿Hay clave configurada? Sin ella la API responde 401 a todo."""
    return bool(config.indeed_api_key())

# --------------------------------------------------------------- consultas ----

# Las consultas y las ubicaciones NO se escriben aquí: salen de las áreas
# activas y de la zona base (ver `areas.py`). Lo que importa es la amplitud: ver
# la nota sobre el filtrado en AND de arriba.
def consultas_por_defecto() -> list[str]:
    return areas.consultas_indeed()


# Ubicaciones: (dónde, radio en millas). El radio se midió: con 50 millas desde
# Monterrey ya entran San Pedro, Guadalupe y Apodaca, y subir a 100 no añade ni
# una vacante más. La entrada vacía es la búsqueda nacional, que es la que trae
# el remoto contratado desde México.
def ubicaciones_por_defecto() -> list[tuple[str, int]]:
    return areas.ubicaciones_indeed()

# Páginas por consulta, solo para `recolectar()`. `peticiones()` no puede
# paginar: el cursor es secuencial y el modelo de la excavadora declara todas
# las URLs antes de pedir ninguna.
PAGINAS = 4

# Tope duro de Indeed por petición.
LIMITE = 100

# Atributos que Indeed etiqueta en la vacante. Las claves son opacas, así que
# se anota la etiqueta que devuelve la API en es-MX y las veces que se observó
# en el muestreo del 2026-08-16, para que la próxima persona sepa si un cero
# significa "no aplica" o "la clave ya no existe".
ATRIB_REMOTO = "DSQF7"          # "Home Office (Desde casa)" — 104/500
ATRIB_HIBRIDO = "PAXZC"         # "Trabajo híbrido"          —  66/500
# `VDTG7` figuraba aquí como el atributo de prácticas y no aparece ni una vez
# en 1.215 vacantes mexicanas: marcaba `practicas: False` en el 100% de los
# casos. Estas dos sí se pueblan.
ATRIBS_PRACTICAS = {
    "CPAHG",                    # "Aprendiz"                  —  93/715
    "4BQ7N",                    # "Empleos para estudiantes"  — 101/715
}


# ---------------------------------------------------------------- consulta ----

# Solo se piden los campos que el pipeline usa. Pedir el dossier completo del
# empleador (industria, plantilla, facturación, logos) multiplica el tamaño de
# la respuesta y nada de eso llega al modelo normalizado de `vacante()`.
_CAMPOS = """
        key
        title
        datePublished
        dateOnIndeed
        description { html }
        location {
          city
          admin1Code
          countryCode
          formatted { short long }
        }
        compensation {
          baseSalary { unitOfWork range { ... on Range { min max } } }
          currencyCode
        }
        attributes { key label }
        employer { name relativeCompanyPageUrl }
        recruit { viewJobUrl }
"""


def _consulta_graphql(que: str, donde: str = "", radio: int = 50,
                      limite: int = LIMITE, cursor: str = "") -> str:
    """Arma la consulta GraphQL. Los argumentos vacíos se omiten enteros.

    Indeed no acepta `what: ""` ni un `location` a medias: o se pone el
    argumento completo o no se pone.
    """
    que_esc = que.replace("\\", "\\\\").replace('"', '\\"')
    a_que = f'what: "{que_esc}"' if que else ""
    a_donde = (
        f'location: {{where: "{donde}", radius: {radio}, radiusUnit: MILES}}'
        if donde else ""
    )
    a_cursor = f'cursor: "{cursor}"' if cursor else ""
    return (
        "query BusquedaEmpleo {"
        f"  jobSearch({a_que} {a_donde} limit: {limite} {a_cursor} sort: RELEVANCE) {{"
        "    pageInfo { nextCursor }"
        f"    results {{ job {{ {_CAMPOS} }} }}"
        "  }"
        "}"
    )


def _cuerpo(que: str, donde: str, radio: int, cursor: str = "") -> dict:
    return {"query": _consulta_graphql(que, donde, radio, LIMITE, cursor)}


# --------------------------------------------------------------- peticiones ----

def _red_soporta_cabeceras() -> bool:
    """¿Sabe `red.py` mandar cabeceras propias en cada petición?

    Se le pregunta al dataclass en lugar de dejarlo escrito a mano para que
    esta fuente se encienda sola el día que alguien añada el campo, sin que
    nadie tenga que acordarse de volver aquí a descomentar una línea.
    """
    try:
        return any(c.name == "cabeceras" for c in dataclasses.fields(Peticion))
    except Exception:
        return False


def peticiones() -> list[Peticion]:
    """Declara qué URLs pedir, sin pedirlas. Una por consulta y ubicación.

    DEVUELVE LISTA VACÍA MIENTRAS `red.py` NO SEPA MANDAR CABECERAS, y lo dice
    por el log. Esto es deliberado. La versión anterior devolvía las 111
    peticiones igualmente: comprobado el 2026-08-16 pasándolas por
    `descargar_todo()`, las 111 responden **401 "An API Key is required."** y
    `parsear()` saca cero vacantes de cada una. Registrar eso en `FUENTES`
    metía 111 URLs muertas en la oleada y sumaba cero al total sin una sola
    línea de error: exactamente el fallo que no se nota hasta que alguien se
    pregunta por qué Indeed nunca aporta nada. Es mejor aportar cero
    ruidosamente que aparentar que se recolecta.

    PARA ACTIVARLA por la excavadora hacen falta dos cambios en `red.py`
    (no los hago yo: hay otros agentes tocando el repositorio):

        # 1. en la clase Peticion
        cabeceras: dict | None = None

        # 2. en Excavadora._una, en la rama del POST
        resp = await cliente.post(
            p.url, json=p.cuerpo, timeout=self.timeout,
            headers={"Content-Type": "application/json",
                     "Accept": "application/json",
                     **(p.cabeceras or {})},
        )

    Hecho eso, esta función se activa sola y basta con registrar
    `Fuente("indeed", indeed.peticiones, indeed.parsear)` y añadir
    `"indeed": indeed.parsear` a `PARSERS`.

    DOS TRAMPAS COMPROBADAS que hay que respetar en ese parche:

      - Las cabeceras de la petición tienen que SOBREESCRIBIR las del cliente,
        no sumarse: `red.py` fija un `User-Agent` de Chrome y con él la API
        responde 403 con HTML de Cloudflare. En httpx el `headers=` de la
        llamada gana sobre el del cliente, así que el parche de arriba vale.
      - Aquí se mandan las cabeceras SIN `indeed-co`. Estas peticiones
        llevan el país en la URL (`?co=MX`) y añadir además la cabecera
        `indeed-co` provoca un 400. Es el error que tenía la versión anterior:
        seguir su nota de integración al pie de la letra cambiaba el 401 por
        un 400, sin arreglar nada.

    Mientras tanto la fuente funciona igual por `recolectar()`, que hace su
    propia descarga con las cabeceras correctas y usa este mismo `parsear()`.
    """
    if not activa():
        log("  indeed: desactivada — falta INDEED_API_KEY (ver .env.example)")
        return []
    if not _red_soporta_cabeceras():
        log("  indeed: inactiva por la excavadora — `red.py` no manda cabeceras "
            "por peticion y la API responde 401 sin `indeed-api-key`. "
            "La fuente sigue disponible por recolectar().")
        return []

    ps: list[Peticion] = []
    for consulta in consultas_por_defecto():
        for donde, radio in ubicaciones_por_defecto():
            ps.append(
                Peticion(
                    # El país por query string. Va con las cabeceras SIN
                    # `indeed-co`: las dos vías a la vez dan 400.
                    url=f"{API}?co=MX",
                    etiqueta="indeed",
                    meta={"consulta": consulta, "zona": donde or "nacional"},
                    json=True,
                    cache_horas=3,
                    cuerpo=_cuerpo(consulta, donde, radio),
                    # Por nombre, porque el campo no existe en la versión
                    # actual de `red.py` y solo se llega aquí si existe.
                    **{"cabeceras": cabeceras(pais_en_cabecera=False)},
                )
            )
    return ps


# ------------------------------------------------------------------ parser ----

def _texto_ubicacion(loc: dict | None) -> str:
    """La ubicación legible. `city` viene en nulo a menudo; `formatted` no."""
    if not loc:
        return ""
    fmt = loc.get("formatted") or {}
    texto = fmt.get("long") or fmt.get("short") or ""
    if texto:
        return texto
    partes = [loc.get("city"), loc.get("admin1Code"), loc.get("countryCode")]
    return ", ".join(p for p in partes if p)


_UNIDAD = {
    "HOUR": "por hora", "DAY": "por día", "WEEK": "por semana",
    "MONTH": "al mes", "YEAR": "al año", "BIWEEKLY": "por quincena",
}


def _texto_salario(comp: dict | None) -> str:
    """Indeed lo da estructurado; el resto del sistema espera una cadena."""
    if not comp:
        return ""
    base = comp.get("baseSalary") or {}
    rango = base.get("range") or {}
    minimo, maximo = rango.get("min"), rango.get("max")
    if minimo is None and maximo is None:
        return ""
    moneda = comp.get("currencyCode") or "MXN"
    unidad = _UNIDAD.get(base.get("unitOfWork") or "", "")

    def _n(v):
        return f"{int(v):,}" if v is not None else ""

    if minimo is not None and maximo is not None and minimo != maximo:
        cifra = f"${_n(minimo)} - ${_n(maximo)}"
    else:
        cifra = f"${_n(minimo if minimo is not None else maximo)}"
    return " ".join(x for x in (cifra, moneda, unidad) if x)


def _resultados(r: Respuesta) -> tuple[list, str]:
    """Saca (resultados, cursor_siguiente) de la respuesta, tolerando fallos.

    La API contesta 200 incluso cuando la consulta trae errores de GraphQL, así
    que no basta con mirar el código HTTP.
    """
    datos = r.datos
    if datos is None and r.texto:
        try:
            datos = json.loads(r.texto)
        except Exception:
            return [], ""
    if not isinstance(datos, dict):
        return [], ""
    if datos.get("errors"):
        return [], ""
    busqueda = ((datos.get("data") or {}).get("jobSearch")) or {}
    resultados = busqueda.get("results") or []
    cursor = (busqueda.get("pageInfo") or {}).get("nextCursor") or ""
    return resultados, cursor


def parsear(r: Respuesta) -> list[dict]:
    """Convierte una respuesta de la API en vacantes normalizadas."""
    if not r.ok:
        return []
    resultados, _ = _resultados(r)
    if not resultados:
        return []

    meta = r.peticion.meta or {}
    salida: list[dict] = []
    for item in resultados:
        trabajo = (item or {}).get("job") or {}
        jk = trabajo.get("key")
        titulo = trabajo.get("title")
        if not jk or not titulo:
            continue

        empleador = trabajo.get("employer") or {}
        atributos = trabajo.get("attributes") or []
        claves_atrib = {a.get("key") for a in atributos if isinstance(a, dict)}
        reclutamiento = trabajo.get("recruit") or {}

        salida.append(
            vacante(
                titulo=titulo,
                # Sin empleador es una vacante confidencial, igual que en OCC.
                empresa=empleador.get("name") or "Confidencial",
                # La URL canónica de Indeed. `viewJobUrl` apunta al ATS de la
                # empresa y se guarda aparte: sirve para postular directo, pero
                # como identidad de la vacante conviene la estable.
                url=f"https://mx.indeed.com/viewjob?jk={jk}",
                fuente="indeed",
                ubicacion=_texto_ubicacion(trabajo.get("location")),
                descripcion=(trabajo.get("description") or {}).get("html") or "",
                # Milisegundos desde época: `fecha_iso()` ya los reconoce.
                publicado=trabajo.get("datePublished") or trabajo.get("dateOnIndeed") or "",
                salario=_texto_salario(trabajo.get("compensation")),
                extra={
                    "jk": jk,
                    "consulta": meta.get("consulta", ""),
                    "zona": meta.get("zona", ""),
                    # `remoto_flag` es el nombre que lee `analisis.clasificar_geo`
                    # y el que ya usan los parsers de Ashby y Arbeitnow. La
                    # versión anterior escribía `remoto`, que no lo lee nadie:
                    # la señal de home office de Indeed —la más fiable que da
                    # esta fuente, 21% de las vacantes— se perdía entera.
                    "remoto_flag": ATRIB_REMOTO in claves_atrib,
                    "hibrido": ATRIB_HIBRIDO in claves_atrib,
                    "practicas": bool(ATRIBS_PRACTICAS & claves_atrib),
                    "url_directa": reclutamiento.get("viewJobUrl") or "",
                    "etiquetas": [
                        a.get("label") for a in atributos
                        if isinstance(a, dict) and a.get("label")
                    ][:25],
                    "pagina_empresa": (
                        "https://mx.indeed.com" + empleador["relativeCompanyPageUrl"]
                        if empleador.get("relativeCompanyPageUrl") else ""
                    ),
                },
            )
        )
    return salida


# ------------------------------------------------- recolección autónoma ----

def _respuesta_sintetica(peticion: Peticion, codigo: int, texto: str) -> Respuesta:
    """Envuelve una descarga propia en el mismo `Respuesta` que usa red.py.

    Así hay UN solo parser: el que consume la excavadora es el mismo que se
    ejercita aquí, y no se pueden desincronizar.
    """
    r = Respuesta(peticion, codigo, texto)
    if codigo == 200:
        try:
            r.datos = json.loads(texto)
        except Exception:
            r.datos = None
    return r


def recolectar(
    consultas: list[str] | None = None,
    ubicaciones: list[tuple[str, int]] | None = None,
    paginas: int = PAGINAS,
    pausa: float = 0.15,
    verboso: bool = False,
) -> tuple[list[dict], dict]:
    """Descarga y parsea por su cuenta, con las cabeceras que la API exige.

    Existe por dos razones. La primera es que `red.py` todavía no manda
    cabeceras por petición (ver la nota en `peticiones()`), así que este es el
    camino que funciona hoy sin tocar ningún otro archivo. La segunda es que
    solo desde aquí se puede paginar: el cursor es secuencial y hay que haber
    leído una página para pedir la siguiente, cosa que el modelo declarativo de
    la excavadora no permite.

    Devuelve (vacantes, estadísticas).
    """
    consultas = consultas if consultas is not None else consultas_por_defecto()
    ubicaciones = ubicaciones if ubicaciones is not None else ubicaciones_por_defecto()

    est = {
        "urls_pedidas": 0, "http_200": 0, "http_otros": 0, "errores_red": 0,
        "errores_graphql": 0, "vacantes_crudas": 0, "codigos": {},
        # Una entrada por petición realmente enviada. Es lo que permite que el
        # test enseñe la evidencia en vez de pedir que se le crea: sin esto la
        # URL es siempre la misma cadena y no se distingue una corrida buena de
        # una en la que todo devolvió 401.
        "detalle": [],
    }
    vistas: set[str] = set()
    salida: list[dict] = []

    if not activa():
        log("  indeed: desactivada — falta INDEED_API_KEY (ver .env.example)")
        est["sin_clave"] = True
        est["vacantes_unicas"] = 0
        return salida, est

    with httpx.Client(headers=cabeceras(), timeout=30.0) as cliente:
        for consulta in consultas:
            for donde, radio in ubicaciones:
                cursor = ""
                for pagina in range(paginas):
                    peticion = Peticion(
                        url=API, etiqueta="indeed",
                        meta={"consulta": consulta, "zona": donde or "nacional",
                              "pagina": pagina + 1},
                        json=True,
                        cuerpo=_cuerpo(consulta, donde, radio, cursor),
                    )
                    est["urls_pedidas"] += 1
                    try:
                        resp = cliente.post(API, json=peticion.cuerpo)
                        codigo, texto = resp.status_code, resp.text
                    except Exception as e:
                        est["errores_red"] += 1
                        est["detalle"].append({
                            "url": API, "consulta": consulta,
                            "zona": donde or "nacional", "pagina": pagina + 1,
                            "http": 0, "error": type(e).__name__, "vacantes": 0,
                        })
                        break

                    est["codigos"][codigo] = est["codigos"].get(codigo, 0) + 1
                    registro = {
                        "url": API, "consulta": consulta,
                        "zona": donde or "nacional", "pagina": pagina + 1,
                        "http": codigo, "error": "", "vacantes": 0,
                    }
                    est["detalle"].append(registro)
                    if codigo == 200:
                        est["http_200"] += 1
                    else:
                        est["http_otros"] += 1
                        break

                    r = _respuesta_sintetica(peticion, codigo, texto)
                    if isinstance(r.datos, dict) and r.datos.get("errors"):
                        est["errores_graphql"] += 1
                        # Un 200 con `errors` es el fallo más traicionero de
                        # GraphQL: parece una corrida sana en las estadísticas
                        # de HTTP. Se anota el mensaje para que se vea.
                        registro["error"] = str(
                            (r.datos["errors"] or [{}])[0].get("message", "")
                        )[:120]
                        break

                    resultados, cursor = _resultados(r)
                    nuevas = parsear(r)
                    registro["vacantes"] = len(nuevas)
                    est["vacantes_crudas"] += len(nuevas)
                    for v in nuevas:
                        # Una misma vacante sale en varias consultas; se queda
                        # la primera, que es la de la zona más específica.
                        if v["id"] in vistas:
                            continue
                        vistas.add(v["id"])
                        salida.append(v)

                    if verboso:
                        log(f"  indeed [{consulta} / {donde or 'nacional'}] "
                            f"p{pagina + 1}: {len(resultados)} -> {len(salida)} únicas")

                    # Sin cursor no hay más páginas; sin resultados tampoco.
                    if not cursor or not resultados:
                        break
                    if pausa:
                        time.sleep(pausa)
                if pausa:
                    time.sleep(pausa)

    est["vacantes_unicas"] = len(salida)
    return salida, est


def recolectar_todo() -> tuple[list[dict], dict]:
    """Misma firma que `fuentes_mexico.recolectar_todo()`."""
    vs, est = recolectar()
    log(f"  indeed: {len(vs)} vacantes ({est['http_200']}/{est['urls_pedidas']} HTTP 200)")
    return vs, {"indeed": len(vs)}


if __name__ == "__main__":
    vs, est = recolectar(consultas=consultas_por_defecto()[:6], paginas=2, verboso=True)
    # `detalle` se omite del resumen: son cientos de entradas y aquí solo
    # interesan los totales. El test es quien las lee una a una.
    resumen = {k: v for k, v in est.items() if k != "detalle"}
    log(f"INDEED: {len(vs)} vacantes únicas | {resumen}")
    for v in vs[:15]:
        print(f"  - {v['titulo'][:52]:52} | {v['empresa'][:26]:26} | {v['ubicacion'][:30]}")
