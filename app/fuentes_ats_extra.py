"""
Colectores de Workday, Oracle, iCIMS y SuccessFactors.

Por qué hacían falta. Son las cuatro plataformas de contratación que usan los
corporativos grandes, y el sistema no tocaba ninguna. Se detectó al revisar un
dataset abierto: allí apareció **MSCI con oficina en Monterrey**, con puestos
de analista de datos, riesgo y prácticas, publicados en iCIMS. Era un empleador
completamente invisible para este buscador.

Volumen que suman, según el conteo del dataset abierto:

    workday          839.633 vacantes    3.530 empresas
    successfactors   320.799             1.392
    oracle           296.978             1.279
    icims            220.170             2.498
    --------------------------------------------------
    total          ~1.677.000            8.699 empresas

Endpoints, todos verificados el 2026-08-15 con peticiones reales:

  - **Workday**: POST a `/wday/cxs/{tenant}/{sitio}/jobs` con el filtro en el
    cuerpo. Devuelve JSON con `total` y `jobPostings`. Es el único que no
    admite GET, y por eso la capa de red aprendió a hacer POST.
  - **Oracle**: GET al API REST `recruitingCEJobRequisitions`, JSON limpio con
    `TotalJobsCount` y `requisitionList`.
  - **iCIMS**: HTML en `/jobs/search`. Sin API pública.
  - **SuccessFactors**: HTML en `{empresa}.jobs2web.com/search`.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

import directorio
from nucleo import limpiar_html, vacante
from red import Peticion, Respuesta

# Cuántas empresas se consultan por plataforma. El directorio trae miles; pedir
# todas en cada corrida multiplicaría el tiempo sin aportar mucho, porque la
# mayoría no contrata en México ni en remoto abierto. Se puede subir cuando la
# corrida completa sea lo bastante rápida.
TOPE = {"workday": 900, "oracle": 500, "icims": 700, "successfactors": 500}

PAGINAS_WORKDAY = 2   # 20 vacantes por página


# ------------------------------------------------------------------ Workday --

def _partes_workday(url: str) -> tuple[str, str, str] | None:
    """De la URL saca (tenant, host, sitio), que es lo que pide el endpoint."""
    try:
        p = urlsplit(url)
        tenant = p.netloc.split(".")[0]
        sitio = p.path.strip("/").split("/")[0]
        if not tenant or not sitio:
            return None
        return tenant, p.netloc, sitio
    except Exception:
        return None


# Identificador de Mexico dentro de Workday. Es el MISMO en todos los tenants
# (comprobado sobre 58 que respondieron): lo que cambia entre unos y otros es
# como se llama el parametro, unos usan `locationCountry` y otros
# `Location_Country`.
#
# Van en peticiones SEPARADAS, no juntas en la misma. Se probo a mandar las dos
# a la vez y el tenant responde 400: no ignora la que no conoce, rechaza la
# peticion entera. Con el nombre correcto, Jabil pasa de 0 vacantes de Mexico
# visibles a 296.
#
# Por que importa. Antes se pedian las 40 primeras vacantes de cada tenant sin
# filtrar, y en una muestra de 60 tenants esas 40 primeras contenian 16
# vacantes de Mexico EN TOTAL. Con el filtro aparecen las que estaban tapadas:
# Jabil 296, Santander 171, Accenture 153, Kyndryl 142, ABB 77. Ninguna se veia.
MEXICO_WORKDAY = "e2adff9272454660ac4fdb56fc70bb51"
FACETAS_PAIS = ("locationCountry", "Location_Country")


def peticiones_workday() -> list[Peticion]:
    ps = []
    for fila in _filas("workday")[: TOPE["workday"]]:
        partes = _partes_workday(fila.get("url", ""))
        if not partes:
            continue
        tenant, host, sitio = partes
        for faceta in FACETAS_PAIS:
            for pagina in range(PAGINAS_WORKDAY):
                ps.append(Peticion(
                    f"https://{host}/wday/cxs/{tenant}/{sitio}/jobs",
                    "workday", {"empresa": fila.get("name", tenant), "host": host,
                                "sitio": sitio, "filtro": faceta},
                    json=True,
                    cuerpo={"appliedFacets": {faceta: [MEXICO_WORKDAY]},
                            "limit": 20, "offset": pagina * 20, "searchText": ""},
                ))
        # Respaldo por texto para los tenants que no exponen faceta de pais
        # (Genpact responde 400 al filtro). Cuesta una peticion mas por tenant.
        ps.append(Peticion(
            f"https://{host}/wday/cxs/{tenant}/{sitio}/jobs",
            "workday", {"empresa": fila.get("name", tenant), "host": host,
                        "sitio": sitio, "filtro": "texto"},
            json=True,
            cuerpo={"appliedFacets": {}, "limit": 20, "offset": 0,
                    "searchText": "Mexico"},
        ))
    return ps


def parse_workday(r: Respuesta) -> list[dict]:
    if not r.ok or not isinstance(r.datos, dict):
        return []
    m = r.peticion.meta
    salida = []
    for j in r.datos.get("jobPostings", []) or []:
        ruta = j.get("externalPath") or ""
        salida.append(vacante(
            titulo=j.get("title", ""), empresa=m.get("empresa", ""),
            url=f"https://{m['host']}/{m['sitio']}{ruta}",
            fuente="workday", ats="workday",
            ubicacion=j.get("locationsText", ""),
            publicado=_fecha_relativa(j.get("postedOn", "")),
            extra={"host": m["host"], "sitio": m["sitio"]},
        ))
    return salida


def _fecha_relativa(texto: str) -> str:
    """Workday publica 'Posted 12 Days Ago' en vez de una fecha."""
    from datetime import date, timedelta
    m = re.search(r"(\d+)\+?\s*(day|días|dias|month|mes)", texto or "", re.I)
    if not m:
        return date.today().isoformat() if "today" in (texto or "").lower() else ""
    n = int(m.group(1))
    dias = n * 30 if m.group(2).lower().startswith(("month", "mes")) else n
    return (date.today() - timedelta(days=dias)).isoformat()


# ------------------------------------------------------------------- Oracle --

def peticiones_oracle() -> list[Peticion]:
    ps = []
    for fila in _filas("oracle")[: TOPE["oracle"]]:
        url = fila.get("url", "")
        m = re.search(r"https://([^/]+)/hcmUI/CandidateExperience/[^/]+/sites/([^/?#]+)", url)
        if not m:
            continue
        host, sitio = m.group(1), m.group(2)
        ps.append(Peticion(
            f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
            f"?onlyData=true&expand=requisitionList.secondaryLocations"
            f"&finder=findReqs;siteNumber={sitio},limit=200",
            "oracle", {"empresa": fila.get("name", host), "host": host, "sitio": sitio},
            json=True,
        ))
    return ps


def parse_oracle(r: Respuesta) -> list[dict]:
    if not r.ok or not isinstance(r.datos, dict):
        return []
    m = r.peticion.meta
    salida = []
    for it in r.datos.get("items", []) or []:
        for j in it.get("requisitionList", []) or []:
            ubic = j.get("PrimaryLocation") or j.get("PrimaryLocationCountry") or ""
            salida.append(vacante(
                titulo=j.get("Title", ""), empresa=m.get("empresa", ""),
                url=f"https://{m['host']}/hcmUI/CandidateExperience/en/sites/"
                    f"{m['sitio']}/job/{j.get('Id', '')}",
                fuente="oracle", ats="oracle", ubicacion=ubic,
                publicado=j.get("PostedDate", ""),
                extra={"id": j.get("Id"), "pais": j.get("PrimaryLocationCountry")},
            ))
    return salida


# -------------------------------------------------------------------- iCIMS --

def peticiones_icims() -> list[Peticion]:
    ps = []
    for fila in _filas("icims")[: TOPE["icims"]]:
        url = (fila.get("url") or "").rstrip("/")
        if not url.startswith("http"):
            continue
        ps.append(Peticion(
            f"{url}/jobs/search?ss=1&in_iframe=1",
            "icims", {"empresa": fila.get("company_name") or fila.get("name", ""), "base": url},
        ))
    return ps


def parse_icims(r: Respuesta) -> list[dict]:
    if not r.ok or "icims" not in r.texto[:6000].lower():
        return []
    m = r.peticion.meta
    sopa = BeautifulSoup(r.texto, "lxml")
    salida = []
    # Solo los enlaces cuya ruta lleva un identificador numérico de vacante.
    # Sin esto entraban los enlaces de navegación de la propia plataforma
    # ("Welcome page", "Log back in!"), que no son ofertas de empleo.
    rx_vacante = re.compile(r"/jobs/\d{3,}/")
    basura = re.compile(
        r"^(welcome|log ?back|log ?in|sign ?in|search|home|apply|back|next|"
        r"previous|view all|careers?|job (search|alerts?)|privacy|cookie|"
        r"share|email|返回|refer)", re.I)
    vistos = set()
    for a in sopa.select("a[href]"):
        titulo = a.get_text(" ", strip=True)
        href = a.get("href", "")
        if not titulo or len(titulo) < 6 or not rx_vacante.search(href):
            continue
        if basura.match(titulo) or href in vistos:
            continue
        vistos.add(href)
        if not href.startswith("http"):
            href = m["base"] + href
        cont = a.find_parent(["div", "li", "tr"])
        ubic = ""
        if cont:
            t = cont.get_text(" ", strip=True)
            mu = re.search(r"([A-Z][\w\s\.]+,\s*[A-Z]{2}[A-Z\s,]*)", t)
            ubic = mu.group(1)[:60] if mu else ""
        # iCIMS antepone la etiqueta del campo al texto del enlace.
        titulo = re.sub(r"^(Title|Job Title|Puesto)\s+", "", titulo).strip()
        salida.append(vacante(
            titulo=titulo[:140], empresa=m.get("empresa", ""), url=href.split("?")[0],
            fuente="icims", ats="icims", ubicacion=ubic,
            descripcion=limpiar_html(str(cont))[:600] if cont else "",
        ))
    return salida


# ----------------------------------------------------------- SuccessFactors --

def peticiones_successfactors() -> list[Peticion]:
    ps = []
    for fila in _filas("successfactors")[: TOPE["successfactors"]]:
        url = (fila.get("url") or "").rstrip("/")
        if not url.startswith("http"):
            continue
        ps.append(Peticion(
            f"{url}/search/?q=&sortColumn=referencedate&sortDirection=desc",
            "successfactors", {"empresa": fila.get("name", ""), "base": url},
        ))
    return ps


def parse_successfactors(r: Respuesta) -> list[dict]:
    if not r.ok:
        return []
    m = r.peticion.meta
    sopa = BeautifulSoup(r.texto, "lxml")
    salida = []
    for a in sopa.select("a.jobTitle-link, a[href*='/job/']"):
        titulo = a.get_text(" ", strip=True)
        href = a.get("href", "")
        if not titulo or len(titulo) < 4:
            continue
        if not href.startswith("http"):
            href = m["base"] + href
        fila_tr = a.find_parent("tr")
        ubic = ""
        if fila_tr:
            celda = fila_tr.select_one("span.jobLocation, td.colLocation")
            ubic = celda.get_text(" ", strip=True)[:60] if celda else ""
        salida.append(vacante(
            titulo=titulo[:140], empresa=m.get("empresa", ""), url=href.split("?")[0],
            fuente="successfactors", ats="successfactors", ubicacion=ubic,
        ))
    return salida


# ------------------------------------------------------------------ comunes --

# Corporativos con operacion real en Monterrey o en Mexico. Se usan para
# ordenar el directorio antes de cortarlo por TOPE.
#
# Por que hace falta. El directorio trae 3.530 empresas de Workday y solo se
# consultan las primeras 900, pero el archivo NO viene ordenado: el corte era
# arbitrario. Se comprobo que Jabil (indice 1755), Santander (2352) y Kyndryl
# (1487) quedaban fuera y por tanto NUNCA se consultaban — y entre las tres
# tienen 609 vacantes en Mexico. Mientras tanto si entraban cientos de empresas
# sin ninguna operacion aqui.
PRIORITARIAS_MX = (
    "jabil", "santander", "kyndryl", "femsa", "cemex", "banorte", "ternium",
    "nemak", "gruma", "arca continental", "deacero", "sigma", "axtel", "alfa",
    "xignux", "metalsa", "banregio", "oxxo", "heineken", "lala", "bimbo",
    "accenture", "ibm", "dell", "hp", "hewlett", "kpmg", "deloitte", "pwc",
    "ey ", "ernst", "capgemini", "infosys", "wipro", "tcs", "cognizant",
    "general motors", "gm ", "nissan", "kia", "toyota", "ford", "stellantis",
    "caterpillar", "john deere", "whirlpool", "schneider", "siemens", "abb",
    "bosch", "continental", "valeo", "denso", "flex", "foxconn", "sanmina",
    "citi", "banamex", "bbva", "hsbc", "scotiabank", "3m", "ge ", "honeywell",
    "danaher", "emerson", "rockwell", "eaton", "cummins", "navistar", "mabe",
    "msci",   # el hallazgo que motivo añadir iCIMS: publica vacantes de Monterrey
)


def _relevancia_mx(fila: dict) -> tuple:
    """Menor es mejor. Ordena el directorio por probabilidad de tener vacantes
    en Mexico, para que el corte por TOPE deje fuera lo irrelevante y no lo
    contrario."""
    nombre = (fila.get("name") or "").lower()
    url = (fila.get("url") or "").lower()
    for i, clave in enumerate(PRIORITARIAS_MX):
        if clave in nombre:
            return (0, i)                      # corporativo conocido
    if ".mx" in url or "mexico" in nombre or "méxico" in nombre:
        return (1, 0)                          # pista de dominio mexicano
    return (2, 0)


def _filas(ats: str) -> list[dict]:
    try:
        return sorted(directorio._descargar(ats), key=_relevancia_mx)
    except Exception:
        return []


COLECTORES = {
    "workday": (peticiones_workday, parse_workday),
    "oracle": (peticiones_oracle, parse_oracle),
    "icims": (peticiones_icims, parse_icims),
    "successfactors": (peticiones_successfactors, parse_successfactors),
}


if __name__ == "__main__":
    from red import descargar_todo
    for nombre, (pet, par) in COLECTORES.items():
        ps = pet()[:60]
        rs = descargar_todo(ps)
        vs = [v for r in rs for v in par(r)]
        ok = sum(1 for r in rs if r.ok)
        mx = sum(1 for v in vs if re.search(
            r"mexic|méxic|monterrey|nuevo le", (v["ubicacion"] or ""), re.I))
        print(f"{nombre:16} {len(ps):4} peticiones | {ok:4} ok | {len(vs):5} vacantes | Mexico {mx}")
        for v in vs[:2]:
            print(f"     {v['titulo'][:50]:50} | {v['empresa'][:22]:22} | {v['ubicacion'][:28]}")
