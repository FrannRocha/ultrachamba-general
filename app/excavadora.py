"""
La excavadora: orquestador declarativo de recolección.

Cambio de enfoque respecto al pipeline anterior. Antes cada fuente se
descargaba y se parseaba a la vez, en su propio bucle de hilos, una detrás de
otra. Aquí se hace al revés:

  1. Cada fuente declara QUÉ URLs quiere, sin pedir nada todavía.
  2. Se juntan todas — miles — y salen en UNA sola oleada concurrente.
  3. Cada respuesta se entrega al parser de su fuente.

Añadir una fuente nueva es escribir una entrada en `FUENTES`: una función que
genera peticiones y otra que convierte la respuesta en vacantes. No hay que
tocar el orquestador.

Uso:
    python excavadora.py            # corrida completa
    python excavadora.py --rapido   # sin la segunda oleada de LinkedIn
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from typing import Callable
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

import almacen
import analisis
import analisis_paralelo
import areas
import directorio
import fuentes_ats as cat
import fuentes_ats_extra as extra
import fuentes_indeed as indeed
import fuentes_linkedin as li
import fuentes_mexico as mx
from nucleo import ahora_iso, limpiar_html, log, normalizar, vacante
from red import Peticion, Respuesta, descargar_todo


@dataclass
class Fuente:
    nombre: str
    peticiones: Callable[[], list[Peticion]]
    parsear: Callable[[Respuesta], list[dict]]


# ------------------------------------------------------------------- ATS ----

# El directorio abierto sustituye a la lista escrita a mano.
# Medido sobre una muestra de 300 empresas nuevas: 86% de bolsas vivas, frente
# al 29% que acertaba la lista adivinada. Si el directorio no esta disponible,
# se cae a la lista local para que el sistema siga funcionando.
def _tokens(ats: str, respaldo: list[str]) -> list[str]:
    try:
        t = directorio.tokens(ats)
        return t if len(t) > len(respaldo) else respaldo
    except Exception:
        return respaldo


def _p_greenhouse() -> list[Peticion]:
    return [
        Peticion(
            f"https://boards-api.greenhouse.io/v1/boards/{t}/jobs?content=true",
            "greenhouse", {"token": t}, json=True,
        )
        for t in _tokens("greenhouse", cat.GREENHOUSE)
    ]


def _parse_greenhouse(r: Respuesta) -> list[dict]:
    if not r.ok or not isinstance(r.datos, dict):
        return []
    tok = r.peticion.meta["token"]
    salida = []
    for j in r.datos.get("jobs", []):
        salida.append(vacante(
            titulo=j.get("title", ""),
            empresa=j.get("company_name") or tok.replace("-", " ").title(),
            url=j.get("absolute_url", ""), fuente=f"greenhouse:{tok}", ats="greenhouse",
            ubicacion=(j.get("location") or {}).get("name", ""),
            descripcion=j.get("content", ""),
            publicado=j.get("updated_at") or j.get("first_published"),
            extra={"token": tok},
        ))
    return salida


def _p_lever() -> list[Peticion]:
    return [
        Peticion(f"https://api.lever.co/v0/postings/{t}?mode=json", "lever",
                 {"token": t}, json=True)
        for t in _tokens("lever", cat.LEVER)
    ]


def _parse_lever(r: Respuesta) -> list[dict]:
    if not r.ok or not isinstance(r.datos, list):
        return []
    tok = r.peticion.meta["token"]
    salida = []
    for j in r.datos:
        cats = j.get("categories") or {}
        desc = j.get("descriptionPlain") or j.get("description") or ""
        for b in (j.get("lists") or []):
            desc += " " + limpiar_html(b.get("content", ""))
        salida.append(vacante(
            titulo=j.get("text", ""), empresa=tok.replace("-", " ").title(),
            url=j.get("hostedUrl") or j.get("applyUrl", ""),
            fuente=f"lever:{tok}", ats="lever", ubicacion=cats.get("location", "") or "",
            descripcion=desc, publicado=j.get("createdAt"), extra={"token": tok},
        ))
    return salida


def _p_ashby() -> list[Peticion]:
    return [
        Peticion(f"https://api.ashbyhq.com/posting-api/job-board/{t}?includeCompensation=true",
                 "ashby", {"token": t}, json=True)
        for t in _tokens("ashby", cat.ASHBY)
    ]


def _parse_ashby(r: Respuesta) -> list[dict]:
    if not r.ok or not isinstance(r.datos, dict):
        return []
    tok = r.peticion.meta["token"]
    salida = []
    for j in r.datos.get("jobs", []):
        salida.append(vacante(
            titulo=j.get("title", ""), empresa=tok.replace("-", " ").title(),
            url=j.get("jobUrl") or j.get("applyUrl", ""),
            fuente=f"ashby:{tok}", ats="ashby",
            ubicacion=j.get("location", "") or ", ".join(j.get("secondaryLocations", []) or []),
            descripcion=j.get("descriptionPlain") or j.get("descriptionHtml", ""),
            publicado=j.get("publishedAt"),
            salario=(j.get("compensation") or {}).get("compensationTierSummary") or "",
            extra={"token": tok, "remoto_flag": j.get("isRemote")},
        ))
    return salida


def _p_smart() -> list[Peticion]:
    return [
        Peticion(f"https://api.smartrecruiters.com/v1/companies/{t}/postings?limit=100",
                 "smartrecruiters", {"token": t}, json=True)
        for t in _tokens("smartrecruiters", cat.SMARTRECRUITERS)
    ]


def _parse_smart(r: Respuesta) -> list[dict]:
    if not r.ok or not isinstance(r.datos, dict):
        return []
    tok = r.peticion.meta["token"]
    salida = []
    for j in r.datos.get("content", []):
        loc = j.get("location") or {}
        salida.append(vacante(
            titulo=j.get("name", ""),
            empresa=(j.get("company") or {}).get("name") or tok,
            url=f"https://jobs.smartrecruiters.com/{tok}/{j.get('id','')}",
            fuente=f"smartrecruiters:{tok}", ats="smartrecruiters",
            ubicacion=", ".join(x for x in [loc.get("city"), loc.get("region"), loc.get("country")] if x),
            publicado=j.get("releasedDate"), extra={"token": tok},
        ))
    return salida


# --------------------------------------------------------- boards remotos ----

def _p_boards() -> list[Peticion]:
    ps = [
        Peticion("https://remoteok.com/api", "remoteok", json=True),
        Peticion("https://www.workingnomads.com/api/exposed_jobs/", "workingnomads", json=True),
    ]
    for c in areas.categorias_remotive():
        ps.append(Peticion(f"https://remotive.com/api/remote-jobs?category={c}&limit=250",
                           "remotive", json=True))
    for off in range(0, 1000, 100):
        ps.append(Peticion(f"https://himalayas.app/jobs/api?limit=100&offset={off}",
                           "himalayas", json=True))
    for pag in range(1, 8):
        ps.append(Peticion(f"https://www.arbeitnow.com/api/job-board-api?page={pag}",
                           "arbeitnow", json=True))
    for ind in areas.industrias_jobicy():
        ps.append(Peticion(f"https://jobicy.com/api/v2/remote-jobs?count=50&industry={ind}",
                           "jobicy", json=True))
    for feed in mx_feeds():
        ps.append(Peticion(feed, "weworkremotely"))
    return ps


def mx_feeds() -> list[str]:
    return [
        "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
        "https://weworkremotely.com/remote-jobs.rss",
    ]


def _parse_boards(r: Respuesta) -> list[dict]:
    e = r.peticion.etiqueta
    if e == "weworkremotely":
        return _parse_wwr(r)
    if not r.ok or r.datos is None:
        return []
    d, salida = r.datos, []

    if e == "remoteok" and isinstance(d, list):
        for j in d:
            if isinstance(j, dict) and j.get("position"):
                salida.append(vacante(
                    titulo=j.get("position", ""), empresa=j.get("company", ""),
                    url=j.get("url") or j.get("apply_url", ""), fuente="remoteok",
                    ubicacion=j.get("location") or "Remoto",
                    descripcion=j.get("description", ""), publicado=j.get("date"),
                ))
    elif e == "remotive" and isinstance(d, dict):
        for j in d.get("jobs", []):
            salida.append(vacante(
                titulo=j.get("title", ""), empresa=j.get("company_name", ""),
                url=j.get("url", ""), fuente="remotive",
                ubicacion=j.get("candidate_required_location", "Remoto"),
                descripcion=j.get("description", ""), publicado=j.get("publication_date"),
                salario=j.get("salary", ""),
            ))
    elif e == "himalayas" and isinstance(d, dict):
        for j in d.get("jobs", []):
            paises = j.get("locationRestrictions") or []
            salida.append(vacante(
                titulo=j.get("title", ""), empresa=j.get("companyName", ""),
                url=j.get("applicationLink") or j.get("guid", ""), fuente="himalayas",
                ubicacion=", ".join(paises) if paises else "Remoto (sin restriccion)",
                descripcion=j.get("description", ""), publicado=j.get("pubDate"),
            ))
    elif e == "arbeitnow" and isinstance(d, dict):
        for j in d.get("data", []):
            salida.append(vacante(
                titulo=j.get("title", ""), empresa=j.get("company_name", ""),
                url=j.get("url", ""), fuente="arbeitnow", ubicacion=j.get("location", ""),
                descripcion=j.get("description", ""), publicado=j.get("created_at"),
                extra={"remoto_flag": j.get("remote")},
            ))
    elif e == "jobicy" and isinstance(d, dict):
        for j in d.get("jobs", []):
            salida.append(vacante(
                titulo=j.get("jobTitle", ""), empresa=j.get("companyName", ""),
                url=j.get("url", ""), fuente="jobicy", ubicacion=j.get("jobGeo", "Remoto"),
                descripcion=j.get("jobExcerpt", "") or j.get("jobDescription", ""),
                publicado=j.get("pubDate"),
            ))
    elif e == "workingnomads" and isinstance(d, list):
        for j in d:
            if isinstance(j, dict):
                salida.append(vacante(
                    titulo=j.get("title", ""), empresa=j.get("company_name", ""),
                    url=j.get("url", ""), fuente="workingnomads",
                    ubicacion=j.get("location", "Remoto"),
                    descripcion=j.get("description", ""), publicado=j.get("pub_date"),
                ))
    return salida


def _parse_wwr(r: Respuesta) -> list[dict]:
    if not r.ok or not r.texto.strip().startswith("<"):
        return []
    try:
        raiz = ET.fromstring(r.texto.encode("utf-8"))
    except Exception:
        return []
    salida = []
    for item in raiz.iter("item"):
        full = (item.findtext("title") or "").strip()
        emp, _, tit = full.partition(":")
        salida.append(vacante(
            titulo=(tit or full).strip(), empresa=emp.strip(),
            url=(item.findtext("link") or "").strip(), fuente="weworkremotely",
            ubicacion=(item.findtext("region") or "Remoto").strip(),
            descripcion=item.findtext("description") or "",
            publicado=item.findtext("pubDate"),
        ))
    return salida


# ---------------------------------------------------------------- Mexico ----

def _incidencia(mensaje: str) -> None:
    """Deja constancia EN DISCO de algo que fallo en silencio.

    El proyecto no tenia ningun archivo de registro: todo iba a una consola
    que se cierra. Los fallos que no rompen la corrida —una sincronizacion que
    no sube, un documento huerfano— desaparecian sin dejar rastro.
    """
    from nucleo import DATOS, ahora_iso
    try:
        with open(DATOS / "incidencias.log", "a", encoding="utf-8") as f:
            f.write(ahora_iso() + " | " + mensaje + "\n")
    except Exception:
        pass          # registrar nunca debe tumbar una corrida


def _p_occ() -> list[Peticion]:
    # Dos profundidades distintas a proposito: los terminos sueltos traen
    # cientos de resultados y merecen 20 paginas; las frases con guion se
    # agotan en pocas. Ver el porque en `fuentes_mexico.CONSULTAS_AMPLIAS`.
    planes = ([(c, mx.PAGINAS_OCC_AMPLIAS) for c in mx.consultas_amplias()]
              + [(c, mx.PAGINAS_OCC) for c in mx.consultas_mx()])
    ps, vistas = [], set()
    zonas = mx.zonas_occ()
    for c, paginas in planes:
        for z in zonas:
            for pag in range(1, paginas + 1):
                u = f"https://www.occ.com.mx/empleos/de-{c}/"
                if z:
                    u += f"{z}/"
                if pag > 1:
                    u += f"?page={pag}"
                if u in vistas:      # una consulta repetida en ambas listas
                    continue
                vistas.add(u)
                ps.append(Peticion(u, "occ", {"consulta": c}, cache_horas=3))
    return ps


def _parse_occ(r: Respuesta) -> list[dict]:
    if not r.ok or "jobcard-" not in r.texto:
        return []
    sopa = BeautifulSoup(r.texto, "lxml")
    salida = []
    for t in sopa.select('div[id^="jobcard-"]'):
        id_occ = t.get("data-id") or t.get("id", "").replace("jobcard-", "")
        h2 = t.find("h2")
        titulo = h2.get_text(strip=True) if h2 else ""
        if not titulo or not id_occ:
            continue
        textos = [e.get_text(strip=True) for e in t.find_all(["span", "p", "h3"])
                  if e.get_text(strip=True)]
        salario = next((x for x in textos if re.search(r"\$\s?[\d,]+", x)), "")
        # Cualquier estado del pais, no solo los de una zona: las consultas de
        # otras areas y la zona `nacional` traen vacantes de toda la republica.
        ubic = next((x for x in textos if "," in x and mx._ESTADOS.search(x)), "")
        enl = t.find("a", href=re.compile(r"/bolsa-de-trabajo-"))
        empresa = enl.get_text(strip=True) if enl else next(
            (x for x in textos if x not in (titulo, salario, ubic)
             and not re.match(r"^(Hoy|Ayer|Hace|Vista|Ya est|Nuevo|Publicado)", x)
             and 2 < len(x) < 60), "Confidencial")
        salida.append(vacante(
            titulo=titulo, empresa=empresa,
            url=f"https://www.occ.com.mx/empleo/oferta/{id_occ}/", fuente="occ",
            # Vacia si la tarjeta no trae ciudad: "no se sabe" es verdad, y un
            # valor por defecto convertia en locales vacantes de otros estados.
            ubicacion=ubic,
            descripcion=limpiar_html(str(t))[:1200], salario=salario,
            extra={"id_occ": id_occ, "consulta": r.peticion.meta.get("consulta", "")},
        ))
    return salida


def _p_ct() -> list[Peticion]:
    ps = []
    zonas = mx.zonas_ct()
    for c in mx.consultas_mx():
        for z in zonas:
            for pag in range(1, mx.PAGINAS_CT + 1):
                u = f"https://mx.computrabajo.com/trabajo-de-{c}"
                if z:
                    u += f"-{z}"
                if pag > 1:
                    u += f"?p={pag}"
                ps.append(Peticion(u, "computrabajo", {"consulta": c}, cache_horas=3))
    return ps


def _parse_ct(r: Respuesta) -> list[dict]:
    if not r.ok or "box_offer" not in r.texto:
        return []
    sopa = BeautifulSoup(r.texto, "lxml")
    salida = []
    for art in sopa.select("article.box_offer"):
        enl = art.find("a", class_=re.compile("js-o-link"))
        if not enl:
            continue
        href = enl.get("href", "").split("#")[0]
        if not href.startswith("http"):
            href = "https://mx.computrabajo.com" + href
        parrafos = [p.get_text(" ", strip=True) for p in art.find_all("p")]
        emp = art.find("a", href=re.compile(r"/empresas/"))
        salida.append(vacante(
            titulo=enl.get_text(strip=True),
            empresa=(emp.get_text(strip=True) if emp else
                     (parrafos[0][:60] if parrafos else "Confidencial")),
            url=href, fuente="computrabajo",
            # Contra los 32 estados y vacia si no aparece ninguno: el patron
            # anterior solo conocia Nuevo Leon y lo ponia por defecto.
            ubicacion=next((p for p in parrafos if mx._ESTADOS.search(p)), ""),
            descripcion=limpiar_html(str(art))[:1200],
            salario=next((p for p in parrafos if re.search(r"\$\s?[\d,]+", p)), ""),
            extra={"consulta": r.peticion.meta.get("consulta", "")},
        ))
    return salida


# -------------------------------------------------------------- LinkedIn ----

def _p_linkedin() -> list[Peticion]:
    ps = []
    for kw, loc, extra, paginas in li.busquedas():
        for pag in range(paginas):
            u = (f"{li.BASE}?keywords={kw.replace(' ', '%20')}"
                 f"&location={loc.replace(' ', '%20').replace(',', '%2C')}"
                 f"&start={pag * 25}{extra}")
            ps.append(Peticion(u, "linkedin", cache_horas=3))
    return ps


def _parse_linkedin(r: Respuesta) -> list[dict]:
    if not r.ok or "base-card" not in r.texto:
        return []
    sopa = BeautifulSoup(r.texto, "lxml")
    salida = []
    for c in sopa.select("div.base-card, li div.base-search-card"):
        t = c.select_one("h3.base-search-card__title")
        if not t:
            continue
        urn = c.get("data-entity-urn", "")
        jid = urn.split(":")[-1] if urn else ""
        e = c.select_one("h4.base-search-card__subtitle")
        u = c.select_one("span.job-search-card__location")
        a = c.select_one("a.base-card__full-link") or c.select_one("a")
        f = c.select_one("time")
        salida.append(vacante(
            titulo=t.get_text(strip=True), empresa=e.get_text(strip=True) if e else "",
            url=(a.get("href", "").split("?")[0] if a else
                 (f"https://www.linkedin.com/jobs/view/{jid}/" if jid else "")),
            fuente="linkedin", ubicacion=u.get_text(strip=True) if u else "",
            publicado=(f.get("datetime") if f else ""),
            extra={"id_linkedin": jid},
        ))
    return salida


# ------------------------------------------------------------- registro -----

FUENTES = [
    Fuente("greenhouse", _p_greenhouse, _parse_greenhouse),
    Fuente("lever", _p_lever, _parse_lever),
    Fuente("ashby", _p_ashby, _parse_ashby),
    Fuente("smartrecruiters", _p_smart, _parse_smart),
    # Las cuatro plataformas de los corporativos grandes. Se anadieron al
    # descubrir que MSCI publica sus vacantes de Monterrey en iCIMS y este
    # sistema no las veia.
    Fuente("workday", extra.peticiones_workday, extra.parse_workday),
    Fuente("oracle", extra.peticiones_oracle, extra.parse_oracle),
    Fuente("icims", extra.peticiones_icims, extra.parse_icims),
    Fuente("successfactors", extra.peticiones_successfactors, extra.parse_successfactors),
    Fuente("boards", _p_boards, _parse_boards),
    Fuente("occ", _p_occ, _parse_occ),
    Fuente("computrabajo", _p_ct, _parse_ct),
    Fuente("linkedin", _p_linkedin, _parse_linkedin),
    # Indeed Mexico. El colector llevaba escrito desde el principio pero
    # devolvia lista vacia a proposito, porque su API exige una clave en la
    # cabecera y `red.py` no sabia mandar cabeceras por peticion. Resuelto eso,
    # 8 peticiones dieron 364 vacantes unicas, 159 de ellas en Monterrey.
    Fuente("indeed", indeed.peticiones, indeed.parsear),
]

PARSERS = {
    "greenhouse": _parse_greenhouse, "lever": _parse_lever, "ashby": _parse_ashby,
    "smartrecruiters": _parse_smart, "occ": _parse_occ, "computrabajo": _parse_ct,
    "linkedin": _parse_linkedin,
    "workday": extra.parse_workday, "oracle": extra.parse_oracle,
    "icims": extra.parse_icims, "successfactors": extra.parse_successfactors,
    "indeed": indeed.parsear,
    **{e: _parse_boards for e in
       ("remoteok", "remotive", "himalayas", "arbeitnow", "jobicy",
        "workingnomads", "weworkremotely")},
}


# --------------------------------------------------------------- corrida ----

def _progreso(hechas: int, total: int) -> None:
    log(f"    {hechas}/{total} descargas")


# Prefiltro barato: una sola pasada de expresion regular sobre el titulo y la
# ubicacion. Existe porque el directorio abierto multiplico por seis el corpus
# (de ~35.000 a ~200.000 vacantes) y el analisis completo, que es lo caro,
# tardaria mas de media hora sobre todas.
#
# Esta deliberadamente escrito para NO perder nada relevante: si hay duda, pasa.
# El filtrado fino lo hace despues el clasificador, que si mira la descripcion.
# El vocabulario de titulos ya no se escribe aqui: sale de las areas activas
# (`areas.regex_prefiltro_titulo()`). Tecnologia conserva el patron de origen.
RX_UBICACION = re.compile(
    r"mexic|méxic|monterrey|nuevo le|apodaca|san pedro|guadalajar|"
    r"latam|latin ?america|america latina|remote|remoto|anywhere|worldwide|global",
    re.I,
)


def prefiltrar(vacantes: list[dict]) -> list[dict]:
    """Deja pasar lo que podria interesar; descarta lo que seguro no."""
    rx_titulo = areas.regex_prefiltro_titulo()
    salida = []
    for v in vacantes:
        titulo = v.get("titulo") or ""
        if (rx_titulo.search(titulo) or rx_titulo.search(normalizar(titulo))
                or RX_UBICACION.search(v.get("ubicacion") or "")):
            salida.append(v)
    return salida


def ejecutar(rapido: bool = False) -> dict:
    import time
    t0 = time.time()
    log("=" * 66)
    log("EXCAVADORA — recoleccion concurrente")
    log("=" * 66)

    # --- Oleada 1: todo lo que se puede pedir sin depender de nada ---------
    peticiones: list[Peticion] = []
    for f in FUENTES:
        p = f.peticiones()
        peticiones += p
        log(f"  {f.nombre:16} {len(p):5} URLs en cola")
    # Por que en lotes y no en una sola oleada. Medido el 24-ago-2026:
    # `descargar_todo()` devuelve TODAS las respuestas en una lista y cada una
    # lleva la pagina entera dentro. Con 25.236 URLs son ~10 GB. En esta
    # maquina, de 15,4 GB, la RAM libre bajo a 0,8 GB, el sistema empezo a
    # paginar a disco y la corrida paso seis minutos sin avanzar una sola
    # descarga. La corrida anterior murio ahi sin escribir NADA, porque el
    # guardado ocurre al final: se perdieron 9.400 descargas ya hechas.
    #
    # No cambia que se descarga ni como se parsea. Descarga un lote, lo parsea
    # en el acto y suelta el crudo; lo que sobrevive es `crudas`, que son
    # diccionarios pequeños. 1500 deja el pico por debajo de ~1 GB sin tocar
    # la concurrencia dentro de cada lote.
    LOTE = 1500
    log("")
    log(f"[1/5] DESCARGA + PARSEO — {len(peticiones)} URLs en lotes de {LOTE}")

    crudas: list[dict] = []
    hechas = descartadas = 0
    for k in range(0, len(peticiones), LOTE):
        lote = peticiones[k:k + LOTE]
        respuestas = descargar_todo(lote)
        hechas += len(lote)
        for r in respuestas:
            parser = PARSERS.get(r.peticion.etiqueta)
            if parser:
                try:
                    salidas = parser(r)
                except Exception:
                    continue
                # El prefiltro va AQUI y no al final: ver la cabecera. Es lo
                # que impide que `crudas` crezca hasta no caber en memoria.
                utiles = prefiltrar(salidas)
                descartadas += len(salidas) - len(utiles)
                crudas += utiles
        del respuestas
        log(f"    {hechas}/{len(peticiones)} descargas — {len(crudas)} crudas "
            f"({descartadas} descartadas por el prefiltro)")

    log(f"  descargadas y parseadas en {time.time() - t0:.0f}s")
    log(f"  {len(crudas)} vacantes crudas")


    # --- Oleada 2: fichas de LinkedIn, que dependen de la oleada 1 ---------
    if not rapido:
        ids = {v["extra"].get("id_linkedin") for v in crudas
               if v["fuente"] == "linkedin" and v["extra"].get("id_linkedin")}
        if ids:
            log(f"\n[2b] SEGUNDA OLEADA — {len(ids)} fichas de LinkedIn")
            det = [Peticion(li.DETALLE.format(i), "li_detalle", {"id": i}, cache_horas=12)
                   for i in ids]
            por_id = {}
            for r in descargar_todo(det, progreso=_progreso):
                if r.ok:
                    por_id[r.peticion.meta["id"]] = limpiar_html(r.texto)
            cerradas = 0
            for v in crudas:
                texto = por_id.get(v["extra"].get("id_linkedin"))
                if not texto:
                    continue
                v["descripcion"] = texto[:6000]
                es_cerrada = "no longer accepting applications" in texto.lower()
                cerradas += es_cerrada
                v["verificacion"] = {
                    "estado": "cerrada" if es_cerrada else "viva",
                    "metodo": "linkedin-guest", "http": 200, "fecha": ahora_iso(),
                    "detalle": "ficha publica de LinkedIn",
                }
            log(f"  {len(por_id)} fichas con descripcion, {cerradas} ya cerradas")

    log("\n[3/5] DEDUPLICACION Y ANALISIS")
    unicas = analisis.deduplicar(crudas)
    log(f"  {len(crudas)} -> {len(unicas)} unicas")

    # Ya se prefiltro lote a lote durante la descarga; esto solo lo confirma.
    candidatas = prefiltrar(unicas)
    log(f"  prefiltro: {descartadas} descartadas durante la descarga; "
        f"{len(candidatas)} candidatas al analisis")

    analizadas = analisis_paralelo.analizar_lote(candidatas)

    # El nivel es una restriccion binaria, igual que la geografia: un puesto
    # de director o senior no es "menos alcanzable", es inalcanzable para
    # alguien que busca su primer puesto. Con solo restar puntos, 71 vacantes
    # de nivel senior seguian colandose al panel porque el area y la ubicacion
    # las empujaban por encima del umbral.
    prioritarias = areas.valores_prioritarios()
    relevantes = [v for v in analizadas
                  if v["score"] >= 40 and v["elegible_mx"]
                  and v["area"] != "fuera" and v["nivel"] != "excluido"]
    gris = [v for v in analizadas
            if not v["elegible_mx"] and v["modalidad"] == "remoto"
            and v["area"] in prioritarias
            and v["nivel"] in ("practicas", "junior")
            and any("ZONA GRIS" in m for m in v["motivos"])]
    for v in gris:
        v["veredicto"] = "zona-gris"
    relevantes += gris
    relevantes.sort(key=lambda v: -v["score"])
    log(f"  {len(analizadas)} -> {len(relevantes)} relevantes ({len(gris)} zona gris)")

    log("\n[4/5] VERIFICACION")
    import verificador
    import verificador_chrome
    verificador.verificar_lote(relevantes, hilos=24)
    n_ch = verificador_chrome.aplicar(relevantes)
    if n_ch:
        log(f"  capa Chrome: {n_ch} aplicadas")
    vivas = [v for v in relevantes if v["verificacion"]["estado"] != "cerrada"]

    log("\n[5/5] ALMACEN")
    corrida = almacen.abrir_corrida(f"excavadora {'rapida' if rapido else 'completa'}")
    res = almacen.guardar(vivas, corrida)
    nuevas = almacen.nuevas_de_la_corrida(corrida)
    ausentes = almacen.desaparecidas(corrida)
    log(f"  guardadas {res['guardadas']}, nuevas {res['nuevas']}, "
        f"ya no aparecen {len(ausentes)}")

    # Compatibilidad: el dashboard y Obsidian siguen leyendo estos JSON.
    from nucleo import guardar_json
    guardar_json("vacantes.json", vivas)
    estad = {
        "generado": ahora_iso(), "crudas": len(crudas), "unicas": len(unicas),
        "relevantes": len(relevantes), "vivas": len(vivas),
        "urls_descargadas": len(peticiones), "segundos": round(time.time() - t0),
        "corrida": corrida, "nuevas": res["nuevas"], "desaparecidas": len(ausentes),
    }
    guardar_json("estadisticas.json", estad)

    # Riesgo de vacante fantasma: necesita la base ya escrita, porque se
    # calcula sobre el historial de avistamientos de todas las corridas.
    try:
        import fantasma
        fantasma.analizar_base()
    except Exception as e:
        log(f"aviso: no se pudo calcular el riesgo de vacantes fantasma ({e})")

    # Sincronizacion con Drive para que NotebookLM se entere solo. Es opcional
    # a proposito: si no hay credenciales, la corrida NO debe fallar por eso.
    try:
        import sincronizar_drive
        if sincronizar_drive.CREDENCIALES.exists():
            r = sincronizar_drive.sincronizar(minimo_nuevas=5)
            if r.get("omitido"):
                log(f"Drive: {r['motivo']}")
            else:
                log(f"Drive: {len(r['documentos'])} documentos actualizados; "
                    "NotebookLM los releera solo")
                if r.get("huerfanos"):
                    _incidencia(f"quedan {len(r['huerfanos'])} documentos huerfanos en "
                                f"Drive, posiblemente aun enlazados en NotebookLM: "
                                f"{', '.join(r['huerfanos'])}")
    except Exception as e:
        # Antes esto solo escribia una linea en una consola que ya habia
        # escupido dos horas de registro, y la corrida terminaba con "LISTO" y
        # codigo de salida 0. Nadie se enteraba nunca de que NotebookLM se
        # habia quedado con el corpus de anteayer. Ahora queda por escrito.
        _incidencia(f"NO se pudo sincronizar con Drive: {e}. NotebookLM sigue "
                    "sirviendo el corpus anterior.")
        log(f"aviso: no se pudo sincronizar con Drive ({e}) — anotado en incidencias.log")

    log("\n" + "=" * 66)
    log(f"LISTO en {time.time() - t0:.0f}s — {len(vivas)} vacantes vivas, "
        f"{res['nuevas']} nuevas")
    log("=" * 66)
    if nuevas:
        log("\nNUEVAS DESDE LA CORRIDA ANTERIOR:")
        for v in nuevas[:20]:
            log(f"  {v['score']:5.1f} | {v['titulo'][:48]:48} | {(v['empresa'] or '')[:24]}")
    return estad


if __name__ == "__main__":
    ejecutar(rapido="--rapido" in sys.argv)
