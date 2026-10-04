"""
Verificación de vacantes: comprobar que cada una sigue VIVA hoy.

El problema real de cualquier buscador de empleo es la vacante fantasma: sigue
listada en un agregador semanas después de haberse cerrado. Aquí se ataca en
tres capas, de la más barata a la más cara:

  Capa 1 — API del ATS: si la bolsa oficial de la empresa devuelve la vacante,
           está publicada ahora mismo. Es prueba primaria, coste cero.
  Capa 2 — HTTP directo: se descarga la página y se buscan huellas de cierre
           ("no longer accepting applications", "ya no esta disponible", 404,
           redirección a la lista de empleos).
  Capa 3 — Chrome real: para páginas que exigen JavaScript o cookies. Es la
           única capa que ve exactamente lo que vería una persona al abrir el
           enlace.

Estados posibles: viva | cerrada | inaccesible | sin-verificar
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from nucleo import ahora_iso, log, normalizar, sesion

# Huellas de que la vacante ya no acepta candidatos.
HUELLAS_CERRADA = [
    "no longer accepting applications",
    "this job is no longer available",
    "this position is no longer available",
    "this posting is no longer available",
    "job posting has expired",
    "position has been filled",
    "position is closed",
    "applications are closed",
    "we are no longer accepting",
    "the job you are looking for is no longer",
    "job not found",
    "oops! we couldn't find",
    "esta vacante ya no esta disponible",
    "esta oferta ya no esta disponible",
    "la oferta no esta disponible",
    "vacante no disponible",
    "esta vacante ya fue ocupada",
    "oferta expirada",
    "vacante expirada",
    "ya no acepta postulaciones",
    "la vacante que buscas no existe",
    "no encontramos la oferta",
    "page not found",
    "404 not found",
]

# Huellas de que SÍ está viva (botón de aplicar presente).
HUELLAS_VIVA = [
    "apply for this job", "apply now", "submit application",
    "postularme", "postularse", "aplicar a esta vacante", "enviar cv",
    "quiero postularme", "apply to this job", "start your application",
    "solicitar empleo", "inscribirme",
]

# Dominios que exigen sesión iniciada: no se pueden verificar por HTTP anónimo.
DOMINIOS_CON_LOGIN = ["linkedin.com", "wellfound.com", "angel.co", "glassdoor."]


def _huellas(texto_n: str, lista) -> str | None:
    for h in lista:
        if h in texto_n:
            return h
    return None


def verificar_http(v: dict, timeout: int = 20) -> dict:
    """Capa 2. Devuelve el bloque de verificación para una vacante."""
    url = v.get("url", "")
    base = {"fecha": ahora_iso(), "metodo": "http", "url_final": url}

    if not url:
        return {**base, "estado": "inaccesible", "detalle": "sin URL", "http": 0}

    if any(d in url for d in DOMINIOS_CON_LOGIN):
        return {
            **base,
            "estado": "sin-verificar",
            "detalle": "requiere sesion iniciada",
            "http": 0,
        }

    try:
        r = sesion().get(url, timeout=timeout, allow_redirects=True)
    except Exception as e:
        return {
            **base,
            "estado": "inaccesible",
            "detalle": f"error de red: {type(e).__name__}",
            "http": 0,
        }

    base["http"] = r.status_code
    base["url_final"] = r.url

    if r.status_code in (404, 410):
        return {**base, "estado": "cerrada", "detalle": f"HTTP {r.status_code}"}
    if r.status_code in (401, 403):
        return {**base, "estado": "sin-verificar", "detalle": f"bloqueado HTTP {r.status_code}"}
    if r.status_code >= 500:
        return {**base, "estado": "inaccesible", "detalle": f"HTTP {r.status_code}"}

    texto_n = normalizar(r.text[:250_000])

    cerrada = _huellas(texto_n, HUELLAS_CERRADA)
    if cerrada:
        return {**base, "estado": "cerrada", "detalle": f"huella: '{cerrada}'"}

    # Redirección desde la vacante a la lista general = vacante retirada.
    if _redirigida_a_listado(url, r.url):
        return {**base, "estado": "cerrada", "detalle": "redirige al listado general"}

    viva = _huellas(texto_n, HUELLAS_VIVA)
    if viva:
        return {**base, "estado": "viva", "detalle": f"boton de postulacion: '{viva}'"}

    # El título de la vacante aparece en la página: existe, sin botón detectable.
    titulo_n = normalizar(v.get("titulo", ""))
    if len(titulo_n) > 12 and titulo_n[:40] in texto_n:
        return {**base, "estado": "viva", "detalle": "el titulo aparece en la pagina"}

    return {**base, "estado": "sin-verificar", "detalle": "sin senales concluyentes"}


def _redirigida_a_listado(original: str, final: str) -> bool:
    if original.rstrip("/") == final.rstrip("/"):
        return False
    patrones_listado = [
        r"/jobs/?$", r"/careers/?$", r"/empleos/?$", r"/vacantes/?$",
        r"/opportunities/?$", r"/openings/?$", r"^https?://[^/]+/?$",
    ]
    return any(re.search(p, final) for p in patrones_listado)


def verificar_lote(vacantes: list[dict], hilos: int = 12,
                   en_vivo: bool = False) -> list[dict]:
    """Verifica una lista completa. Las de ATS ya vienen probadas por API.

    `en_vivo=False` es lo que hace la excavadora: la vacante ACABA de salir de
    la API del ATS, asi que darla por viva es un hecho, no una suposicion, y
    volver a preguntar seria pagar dos veces por la misma respuesta.

    `en_vivo=True` es para REVALIDAR algo guardado --una candidatura de hace
    nueve dias, el panel, la cola de hoy--. Ahi la suposicion de arriba caduca
    y hay que preguntar de verdad: lo hace `verificar_ats_en_vivo`. Sin esta
    distincion, tres vacantes cerradas se presentaron como vivas y se
    aprobaron las tres.
    """
    por_verificar = []
    ya_verificadas = 0
    en_vivo_ok = 0
    cache_ats: dict = {}
    for v in vacantes:
        # LinkedIn se verifica al recolectar, cuando se descarga su ficha
        # pública. Volver a pedirla aquí solo gastaría peticiones, y además
        # el HTTP anónimo a linkedin.com/jobs/view cae en el muro de sesión.
        #
        # Al revalidar NO vale ese atajo: un "viva" de hace nueve dias no dice
        # nada de hoy, que es justo el fallo que trajo esta rama.
        if not en_vivo and v.get("verificacion", {}).get("estado") in ("viva", "cerrada"):
            ya_verificadas += 1
            continue
        if v.get("ats"):
            if en_vivo:
                dictamen = verificar_ats_en_vivo(v, cache_ats)
                if dictamen:
                    v["verificacion"] = dictamen
                    en_vivo_ok += 1
                else:
                    # ATS que no sabemos consultar (Workday, iCIMS...): que lo
                    # intente la capa HTTP en vez de inventarse un veredicto.
                    por_verificar.append(v)
                continue
            # Capa 1: la API oficial de la empresa la devolvió en esta corrida.
            v["verificacion"] = {
                "estado": "viva",
                "metodo": "api-ats",
                "detalle": f"publicada en la bolsa oficial ({v['ats']}) al momento de recolectar",
                "fecha": ahora_iso(),
                "http": 200,
                "url_final": v.get("url", ""),
            }
        else:
            por_verificar.append(v)

    if ya_verificadas:
        log(f"  capa 0 (verificadas al recolectar, p.ej. LinkedIn): {ya_verificadas}")
    if en_vivo:
        log(f"  capa 1-bis (API de ATS, preguntada de verdad): {en_vivo_ok} "
            f"consultadas en {len(cache_ats)} bolsas")
    else:
        log(
            f"  capa 1 (API de ATS): "
            f"{len(vacantes) - len(por_verificar) - ya_verificadas} vivas por construccion"
        )
    log(f"  capa 2 (HTTP): verificando {len(por_verificar)} de agregadores y bolsas MX...")

    with ThreadPoolExecutor(max_workers=hilos) as ex:
        futuros = {ex.submit(verificar_http, v): v for v in por_verificar}
        hechas = 0
        for fut in as_completed(futuros):
            v = futuros[fut]
            try:
                v["verificacion"] = fut.result()
            except Exception as e:
                v["verificacion"] = {
                    "estado": "inaccesible",
                    "metodo": "http",
                    "detalle": f"excepcion: {type(e).__name__}",
                    "fecha": ahora_iso(),
                    "http": 0,
                    "url_final": v.get("url", ""),
                }
            hechas += 1
            if hechas % 50 == 0:
                log(f"    ...{hechas}/{len(por_verificar)}")

    return vacantes


def resumen(vacantes: list[dict]) -> dict:
    conteo: dict[str, int] = {}
    for v in vacantes:
        estado = v.get("verificacion", {}).get("estado", "sin-verificar")
        conteo[estado] = conteo.get(estado, 0) + 1
    return conteo


# ---------------------------------------------------------------------------
# CAPA 1-BIS: preguntarle DE VERDAD a la API del ATS.
#
# EL FALLO QUE MOTIVO ESTO, el 2-sep-2026. `verificar_lote()` marca "viva"
# toda vacante que tenga `ats` sin llamar a nadie -- su propio detalle lo dice,
# "al momento de recolectar", y el log lo canta: "vivas por construccion". Eso
# es CIERTO dentro de una corrida de la excavadora, donde la vacante acaba de
# salir de la API; y es FALSO en cuanto se usa para revalidar algo guardado.
#
# Ese dia se revalidaron cinco candidaturas de hace nueve dias para
# presentarlas a aprobacion. Tres estaban cerradas y las tres salieron
# "vivas": una ficha decia "Ya no se aceptan solicitudes" y dos daban 404 en la
# API de Greenhouse. Se aprobaron creyendo que estaban abiertas. Un falso "viva" no es un dato de menos: es una candidatura
# que se gasta contra una puerta cerrada.
#
# COMO SE PREGUNTA. Se pide la LISTA entera del board, no el detalle de la
# vacante: una sola llamada sirve para todas las vacantes de ese token (por eso
# el `cache`), y evita tener que conocer seis endpoints de detalle distintos.
# Si el board contesta y la vacante ya no figura, esta cerrada. Es la regla
# dura del proyecto: solo el ATS oficial cierra una vacante.
#
# LO QUE NO HACE. Si el board entero no responde (403, 429, red caida), NO se
# dice "cerrada": se dice `inaccesible`. "No me dejan mirar" nunca es "no
# existe" -- esa confusion ya cerro vacantes vivas de gob.mx, Oracle y OCC.

# Donde vive la lista publica de cada plataforma. Workable y Recruitee llevan
# el token en sitios distintos de la URL, por eso la plantilla y no un f-string
# unico. Workday, iCIMS y SuccessFactors no estan: su subdominio es propio de
# cada cliente y no se deduce del nombre (ver `descubrir_ats.py`).
LISTAS_ATS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{t}/jobs",
    "lever": "https://api.lever.co/v0/postings/{t}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{t}",
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{t}/postings",
    "workable": "https://apply.workable.com/api/v1/widget/accounts/{t}?details=true",
    "recruitee": "https://{t}.recruitee.com/api/offers/",
}


def _id_de_url(url: str) -> str:
    """El identificador de una vacante segun su URL: el ultimo tramo util.

    Sirve para las seis plataformas porque todas terminan la URL con el id o
    el slug del anuncio. Se quita la query primero: Greenhouse a veces repite
    el id en `?gh_jid=`, y comparar con la query pegada no casaria nunca.
    """
    if not url:
        return ""
    limpia = url.split("?")[0].split("#")[0].rstrip("/")
    return limpia.split("/")[-1].strip().lower()


def _ids_publicados(plataforma: str, datos) -> set:
    """Los identificadores que el board publica AHORA, en minusculas.

    Se recogen por partida doble --el id propio y el de la URL-- porque cada
    plataforma nombra el suyo distinto y un solo criterio dejaba fuera casos
    reales: Greenhouse trae `id` numerico y `absolute_url`; Ashby y Lever usan
    UUID; Recruitee identifica por slug.
    """
    if isinstance(datos, dict):
        filas = (datos.get("jobs") or datos.get("offers")
                 or datos.get("content") or datos.get("results") or [])
    elif isinstance(datos, list):
        filas = datos
    else:
        filas = []
    fuera = set()
    for j in filas:
        if not isinstance(j, dict):
            continue
        for clave in ("id", "shortcode", "slug"):
            if j.get(clave) not in (None, ""):
                fuera.add(str(j[clave]).strip().lower())
        for clave in ("absolute_url", "jobUrl", "applyUrl", "hostedUrl",
                      "careers_url", "url", "shortlink"):
            if j.get(clave):
                fuera.add(_id_de_url(str(j[clave])))
        ref = j.get("ref") or {}
        if isinstance(ref, dict) and ref.get("jobAd"):
            fuera.add(_id_de_url(str(ref["jobAd"])))
    fuera.discard("")
    return fuera


def _plataforma_y_token(v: dict) -> tuple:
    """De donde salio la vacante. `fuente` viene como 'greenhouse:cloudflare'."""
    fuente = (v.get("fuente") or "")
    plataforma = (v.get("ats") or "").strip().lower()
    token = ""
    if ":" in fuente:
        cabeza, _, cola = fuente.partition(":")
        if not plataforma:
            plataforma = cabeza.strip().lower()
        token = cola.strip()
    extra = v.get("extra")
    if isinstance(extra, str):
        try:
            import json as _json
            extra = _json.loads(extra)
        except Exception:
            extra = {}
    if isinstance(extra, dict) and extra.get("token"):
        token = str(extra["token"])
    return plataforma, token


def verificar_ats_en_vivo(v: dict, cache: dict | None = None,
                          timeout: int = 25) -> dict:
    """Pregunta al ATS oficial si esta vacante sigue publicada HOY.

    `cache` evita repetir la llamada por cada vacante del mismo board: con 40
    vacantes de un token, la diferencia es 1 peticion contra 40.
    """
    plataforma, token = _plataforma_y_token(v)
    plantilla = LISTAS_ATS.get(plataforma)
    if not plantilla or not token:
        # No es un ATS que sepamos leer (o no consta el token): esta funcion no
        # opina. Que decida la capa HTTP, que para eso existe.
        return {}

    cache = cache if cache is not None else {}
    llave = f"{plataforma}:{token}"
    if llave not in cache:
        try:
            r = sesion().get(plantilla.format(t=token), timeout=timeout)
            cache[llave] = (r.status_code, r.json() if r.status_code == 200 else None)
        except Exception as e:
            cache[llave] = (0, None)
            log(f"    ats {llave}: no se pudo consultar ({type(e).__name__})")
    codigo, datos = cache[llave]

    base = {"metodo": "api-ats", "fecha": ahora_iso(), "http": codigo,
            "url_final": v.get("url", "")}
    if codigo != 200 or datos is None:
        # El board no contesta. NO es un cierre: es que no dejan mirar.
        return {**base, "estado": "inaccesible",
                "detalle": f"la bolsa oficial ({plataforma}) no respondio "
                           f"(HTTP {codigo})"}

    publicados = _ids_publicados(plataforma, datos)
    if not publicados:
        return {**base, "estado": "inaccesible",
                "detalle": f"la bolsa oficial ({plataforma}) respondio sin "
                           f"vacantes legibles"}

    extra = v.get("extra")
    if isinstance(extra, str):
        try:
            import json as _json
            extra = _json.loads(extra)
        except Exception:
            extra = {}
    mios = {_id_de_url(v.get("url", ""))}
    if isinstance(extra, dict):
        for clave in ("gh_id", "id", "job_id", "shortcode", "slug"):
            if extra.get(clave) not in (None, ""):
                mios.add(str(extra[clave]).strip().lower())
    mios.discard("")

    if mios & publicados:
        return {**base, "estado": "viva",
                "detalle": f"la bolsa oficial ({plataforma}) la sigue "
                           f"publicando hoy"}
    return {**base, "estado": "cerrada",
            "detalle": f"ya no figura en la bolsa oficial ({plataforma}), que "
                       f"publica {len(publicados)} vacantes ahora mismo"}
