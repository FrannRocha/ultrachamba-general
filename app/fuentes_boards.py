"""
Colectores de bolsas de empleo remoto (globales) y fuentes de México.

A diferencia de los ATS, estos agregadores pueden contener vacantes ya cerradas;
por eso todo lo que sale de aquí pasa obligatoriamente por `verificador.py`
antes de llegar al dashboard.

Es el colector del camino de legado (`pipeline.py` y `analisis_mercado.py`); el
ciclo diario usa `excavadora.py`. Las categorías, las consultas y la zona salen
de la configuración activa (`areas.py`).
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from xml.etree import ElementTree as ET

import areas
from nucleo import limpiar_html, log, normalizar, obtener_json, obtener_texto, vacante


# ---------------------------------------------------------------- RemoteOK ----

def remoteok() -> list[dict]:
    datos = obtener_json("https://remoteok.com/api")
    if not isinstance(datos, list):
        return []
    salida = []
    for j in datos:
        if not isinstance(j, dict) or not j.get("position"):
            continue
        salida.append(
            vacante(
                titulo=j.get("position", ""),
                empresa=j.get("company", ""),
                url=j.get("url") or j.get("apply_url", ""),
                fuente="remoteok",
                ubicacion=j.get("location") or "Remoto",
                descripcion=j.get("description", ""),
                publicado=j.get("date"),
                salario=_salario(j.get("salary_min"), j.get("salary_max")),
                extra={"tags": j.get("tags", [])},
            )
        )
    return salida


def _salario(mn, mx) -> str:
    try:
        if mn and mx:
            return f"USD {int(mn):,} - {int(mx):,}"
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------- Remotive ----

def remotive() -> list[dict]:
    salida = []
    for cat in areas.categorias_remotive():
        datos = obtener_json(
            f"https://remotive.com/api/remote-jobs?category={cat}&limit=250"
        )
        if not isinstance(datos, dict):
            continue
        for j in datos.get("jobs", []):
            salida.append(
                vacante(
                    titulo=j.get("title", ""),
                    empresa=j.get("company_name", ""),
                    url=j.get("url", ""),
                    fuente="remotive",
                    ubicacion=j.get("candidate_required_location", "Remoto"),
                    descripcion=j.get("description", ""),
                    publicado=j.get("publication_date"),
                    salario=j.get("salary", ""),
                    extra={"tipo": j.get("job_type", "")},
                )
            )
    return salida


# --------------------------------------------------------------- Himalayas ----

def himalayas() -> list[dict]:
    salida = []
    for offset in range(0, 400, 100):
        datos = obtener_json(
            f"https://himalayas.app/jobs/api?limit=100&offset={offset}"
        )
        if not isinstance(datos, dict):
            break
        trabajos = datos.get("jobs", [])
        if not trabajos:
            break
        for j in trabajos:
            paises = j.get("locationRestrictions") or []
            salida.append(
                vacante(
                    titulo=j.get("title", ""),
                    empresa=j.get("companyName", ""),
                    url=j.get("applicationLink") or j.get("guid", ""),
                    fuente="himalayas",
                    ubicacion=", ".join(paises) if paises else "Remoto (sin restriccion)",
                    descripcion=j.get("description", ""),
                    publicado=j.get("pubDate"),
                    salario=_salario(j.get("minSalary"), j.get("maxSalary")),
                    extra={"restricciones": paises, "seniority": j.get("seniority")},
                )
            )
    return salida


# --------------------------------------------------------------- Arbeitnow ----

def arbeitnow() -> list[dict]:
    salida = []
    for pagina in range(1, 4):
        datos = obtener_json(
            f"https://www.arbeitnow.com/api/job-board-api?page={pagina}"
        )
        if not isinstance(datos, dict):
            break
        for j in datos.get("data", []):
            salida.append(
                vacante(
                    titulo=j.get("title", ""),
                    empresa=j.get("company_name", ""),
                    url=j.get("url", ""),
                    fuente="arbeitnow",
                    ubicacion=j.get("location", ""),
                    descripcion=j.get("description", ""),
                    publicado=j.get("created_at"),
                    extra={"tags": j.get("tags", []), "remoto": j.get("remote")},
                )
            )
    return salida


# ------------------------------------------------------------------ Jobicy ----

def jobicy() -> list[dict]:
    salida = []
    for etiqueta in areas.industrias_jobicy():
        datos = obtener_json(
            f"https://jobicy.com/api/v2/remote-jobs?count=50&industry={etiqueta}"
        )
        if not isinstance(datos, dict):
            continue
        for j in datos.get("jobs", []):
            salida.append(
                vacante(
                    titulo=j.get("jobTitle", ""),
                    empresa=j.get("companyName", ""),
                    url=j.get("url", ""),
                    fuente="jobicy",
                    ubicacion=j.get("jobGeo", "Remoto"),
                    descripcion=j.get("jobExcerpt", "") or j.get("jobDescription", ""),
                    publicado=j.get("pubDate"),
                    salario=_salario(j.get("annualSalaryMin"), j.get("annualSalaryMax")),
                    extra={"nivel": j.get("jobLevel"), "tipo": j.get("jobType")},
                )
            )
    return salida


# ---------------------------------------------------------- WeWorkRemotely ----

WWR_FEEDS = [
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    "https://weworkremotely.com/remote-jobs.rss",
]


def weworkremotely() -> list[dict]:
    salida = []
    for feed in WWR_FEEDS:
        codigo, texto = obtener_texto(feed)
        if codigo != 200 or not texto.strip().startswith("<"):
            continue
        try:
            raiz = ET.fromstring(texto.encode("utf-8"))
        except Exception:
            continue
        for item in raiz.iter("item"):
            titulo_full = (item.findtext("title") or "").strip()
            empresa, _, titulo = titulo_full.partition(":")
            salida.append(
                vacante(
                    titulo=(titulo or titulo_full).strip(),
                    empresa=empresa.strip(),
                    url=(item.findtext("link") or "").strip(),
                    fuente="weworkremotely",
                    ubicacion=(item.findtext("region") or "Remoto").strip(),
                    descripcion=item.findtext("description") or "",
                    publicado=item.findtext("pubDate"),
                )
            )
    return salida


# ----------------------------------------------------------- WorkingNomads ----

def workingnomads() -> list[dict]:
    datos = obtener_json("https://www.workingnomads.com/api/exposed_jobs/")
    if not isinstance(datos, list):
        return []
    salida = []
    for j in datos:
        if not isinstance(j, dict):
            continue
        salida.append(
            vacante(
                titulo=j.get("title", ""),
                empresa=j.get("company_name", ""),
                url=j.get("url", ""),
                fuente="workingnomads",
                ubicacion=j.get("location", "Remoto"),
                descripcion=j.get("description", ""),
                publicado=j.get("pub_date"),
                extra={"categorias": j.get("category_name", "")},
            )
        )
    return salida


# ------------------------------------------------------------------- OCC MX ----

# Consultas de origen, de tecnologia. Con otras areas activas se toman las
# primeras de cada una (`_consultas_legado`), para no multiplicar peticiones.
OCC_TECNOLOGIA = [
    "practicante ciberseguridad", "becario ciberseguridad",
    "practicante seguridad informatica", "analista soc junior",
    "practicante inteligencia artificial", "becario datos",
    "practicante sistemas", "seguridad de la informacion junior",
]
COMPUTRABAJO_TECNOLOGIA = [
    "practicante-de-ciberseguridad", "becario-de-ciberseguridad",
    "practicante-de-seguridad-informatica", "practicante-de-sistemas",
    "analista-de-ciberseguridad-junior", "practicante-de-datos",
]


def _consultas_legado(tecnologia: list[str], por_area: int = 2) -> list[str]:
    """Con tecnologia como unica area, las de origen tal cual; si no, las
    primeras `por_area` de cada area activa."""
    claves = areas.claves_activas()
    if claves == ["tecnologia"]:
        return list(tecnologia)
    salida: list[str] = []
    for clave in claves:
        propias = tecnologia if clave == "tecnologia" else areas.AREAS[clave].get("consultas", [])
        salida += list(propias)[:por_area]
    return salida


def _zona_legado() -> tuple[str, str, str]:
    """(parametro `l` de OCC, sufijo de Computrabajo, ubicacion por defecto).

    Solo la zona `monterrey` tiene los de origen; sin zona base se busca en
    todo Mexico.
    """
    if areas.zona_clave() == "monterrey":
        return "Nuevo%20Leon", "-en-nuevo-leon", "Nuevo Leon, Mexico"
    return "", "", "Mexico"


def occ_mundial() -> list[dict]:
    """OCC Mundial: la bolsa más grande de México. API interna de búsqueda."""
    salida = []
    consultas = _consultas_legado(OCC_TECNOLOGIA)
    lugar, _sufijo, por_defecto = _zona_legado()
    for q in consultas:
        url = (
            "https://www.occ.com.mx/api/search/vacantes"
            f"?q={q.replace(' ', '%20')}" + (f"&l={lugar}" if lugar else "") + "&page=1"
        )
        datos = obtener_json(url, cache_horas=3)
        if not isinstance(datos, dict):
            continue
        for j in datos.get("jobs", []) or datos.get("data", []) or []:
            if not isinstance(j, dict):
                continue
            enlace = j.get("link") or j.get("url") or ""
            if enlace and not enlace.startswith("http"):
                enlace = "https://www.occ.com.mx" + enlace
            salida.append(
                vacante(
                    titulo=j.get("title", "") or j.get("jobTitle", ""),
                    empresa=j.get("company", "") or j.get("companyName", ""),
                    url=enlace,
                    fuente="occ",
                    ubicacion=j.get("location", "") or por_defecto,
                    descripcion=j.get("description", ""),
                    publicado=j.get("publishDate") or j.get("date"),
                    salario=j.get("salary", ""),
                    extra={"consulta": q},
                )
            )
    return salida


# ------------------------------------------------------------- Computrabajo ----

def computrabajo() -> list[dict]:
    """Scrape ligero de Computrabajo MX (zona base, o todo México sin ella)."""
    salida = []
    # Las de otras areas llegan como frases: se pasan a slug.
    consultas = [q if " " not in q else re.sub(r"\s+", "-", normalizar(q).strip())
                 for q in _consultas_legado(COMPUTRABAJO_TECNOLOGIA)]
    _lugar, sufijo, por_defecto = _zona_legado()
    for q in consultas:
        url = f"https://mx.computrabajo.com/trabajo-de-{q}{sufijo}"
        codigo, html = obtener_texto(url)
        if codigo != 200:
            continue
        bloques = re.findall(
            r'<article[^>]*class="box_offer"[^>]*>(.*?)</article>', html, re.S
        )
        for b in bloques:
            m_url = re.search(r'href="(/ofertas-de-trabajo/[^"]+)"', b)
            m_tit = re.search(r'class="js-o-link[^"]*"[^>]*>([^<]+)<', b)
            m_emp = re.search(r'<a[^>]*class="[^"]*it-blank[^"]*"[^>]*>([^<]+)<', b)
            m_loc = re.search(r'<p class="fs16 fc_base mt5">.*?<span>([^<]+)</span>', b, re.S)
            if not (m_url and m_tit):
                continue
            salida.append(
                vacante(
                    titulo=m_tit.group(1).strip(),
                    empresa=(m_emp.group(1).strip() if m_emp else "Confidencial"),
                    url="https://mx.computrabajo.com" + m_url.group(1),
                    fuente="computrabajo",
                    ubicacion=(m_loc.group(1).strip() if m_loc else por_defecto),
                    descripcion=limpiar_html(b)[:800],
                    extra={"consulta": q},
                )
            )
    return salida


# ------------------------------------------------------------- orquestación ----

FUENTES = [
    ("remoteok", remoteok),
    ("remotive", remotive),
    ("himalayas", himalayas),
    ("arbeitnow", arbeitnow),
    ("jobicy", jobicy),
    ("weworkremotely", weworkremotely),
    ("workingnomads", workingnomads),
    ("occ", occ_mundial),
    ("computrabajo", computrabajo),
]


def recolectar_todo(hilos: int = 9) -> tuple[list[dict], dict]:
    vacantes: list[dict] = []
    informe: dict = {}
    with ThreadPoolExecutor(max_workers=hilos) as ex:
        futuros = {ex.submit(fn): nombre for nombre, fn in FUENTES}
        for fut, nombre in list(futuros.items()):
            try:
                res = fut.result(timeout=180)
            except Exception as e:
                log(f"  {nombre}: ERROR {type(e).__name__}")
                res = []
            informe[nombre] = len(res)
            log(f"  {nombre}: {len(res)} vacantes")
            vacantes.extend(res)
    return vacantes, informe


if __name__ == "__main__":
    vs, inf = recolectar_todo()
    log(f"TOTAL BOARDS: {len(vs)} vacantes crudas")
