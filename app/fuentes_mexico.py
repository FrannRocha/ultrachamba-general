"""
Fuentes de empleo de México: OCC Mundial y Computrabajo.

Son las dos bolsas que concentran las vacantes presenciales en México.
Ambas renderizan resultados en el servidor, así que se leen por HTTP directo.
Los selectores se obtuvieron inspeccionando el DOM real con Chrome, no de
suposiciones: OCC usa `id="jobcard-{id}"` y Computrabajo `<article class="box_offer ...">`.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from bs4 import BeautifulSoup

import areas
from nucleo import limpiar_html, log, obtener_texto, vacante


# Consultas y zonas: NO se escriben aqui. Salen de las areas activas y de la
# zona base (ver `areas.py`): las frases con guion valen igual para OCC y para
# Computrabajo, y la zona vacia es la busqueda nacional (hibrido y remoto).
def consultas_mx() -> list[str]:
    return areas.consultas_occ()


def zonas_occ() -> list[str]:
    return areas.zonas_occ()


# -------------------------------------------------------------- OCC Mundial ----

# Los 32 estados, para leer la ubicacion sin presuponer que todo es Monterrey.
# OJO: este patron se escribio primero desde un heredoc de bash y el limite de
# palabra del principio llego al archivo como un BACKSPACE literal (\b). La
# expresion compilaba sin quejarse y no casaba con NADA, ni siquiera con
# "Nuevo Leon". La regla que sale de ahi: nunca escribir regex con limites de
# palabra desde un heredoc de bash.
# Si hay que tocar este patron, se edita el archivo directamente.
_ESTADOS = re.compile(
    r"(?i)\b("
    r"aguascalientes|baja california|baja california sur|campeche|chiapas|"
    r"chihuahua|coahuila|colima|ciudad de m[ée]xico|cdmx|distrito federal|"
    r"durango|guanajuato|guerrero|hidalgo|jalisco|estado de m[ée]xico|"
    r"edo\.? de m[ée]xico|michoac[áa]n|morelos|nayarit|nuevo le[óo]n|oaxaca|"
    r"puebla|quer[ée]taro|quintana roo|san luis potos[íi]|sinaloa|sonora|"
    r"tabasco|tamaulipas|tlaxcala|veracruz|yucat[áa]n|zacatecas"
    r")\b"
)


def _occ_una(consulta: str, zona: str, pagina: int = 1) -> list[dict]:
    base = f"https://www.occ.com.mx/empleos/de-{consulta}/"
    if zona:
        base += f"{zona}/"
    if pagina > 1:
        base += f"?page={pagina}"
    codigo, html = obtener_texto(base)
    if codigo != 200 or "jobcard-" not in html:
        return []

    sopa = BeautifulSoup(html, "lxml")
    salida = []
    for tarjeta in sopa.select('div[id^="jobcard-"]'):
        id_occ = tarjeta.get("data-id") or tarjeta.get("id", "").replace("jobcard-", "")
        h2 = tarjeta.find("h2")
        titulo = h2.get_text(strip=True) if h2 else ""
        if not titulo or not id_occ:
            continue

        textos = [
            e.get_text(strip=True)
            for e in tarjeta.find_all(["span", "p", "h3"])
            if e.get_text(strip=True)
        ]
        salario = next((t for t in textos if re.search(r"\$\s?[\d,]+", t)), "")
        ubicacion = next(
            (t for t in textos if re.search(r",\s*(Nuevo Le|Ciudad de M|Jalisco|Estado de M|Quer)", t)),
            "",
        )
        # La empresa es el enlace a su bolsa de trabajo; si es confidencial no hay enlace.
        enlace_emp = tarjeta.find("a", href=re.compile(r"/bolsa-de-trabajo-"))
        empresa = enlace_emp.get_text(strip=True) if enlace_emp else ""
        if not empresa:
            empresa = next(
                (
                    t
                    for t in textos
                    if t not in (titulo, salario, ubicacion)
                    and not re.match(r"^(Hoy|Ayer|Hace|Vista|Ya est|Nuevo|Publicado)", t)
                    and 2 < len(t) < 60
                ),
                "Confidencial",
            )
        recencia = next(
            (t for t in textos if re.match(r"^(Hoy|Ayer|Hace \d+)", t)), ""
        )

        salida.append(
            vacante(
                titulo=titulo,
                empresa=empresa,
                url=f"https://www.occ.com.mx/empleo/oferta/{id_occ}/",
                fuente="occ",
                # NO inventar la ubicacion. Esta linea decia
                # `ubicacion or "Nuevo Leon, Mexico"`, y ese "or" convirtio
                # 443 de 776 vacantes de OCC (57%) en falsos monterreyanos:
                # cuando la tarjeta no traia ciudad, el codigo AFIRMABA que
                # estaba en Nuevo Leon. Tres que se abrieron con esa etiqueta
                # estaban en CDMX, Guadalajara y Aguascalientes.
                #
                # Vacio significa "no lo sabemos", que es la verdad y ademas
                # es accionable: `enriquecer` va a buscarlo a la ficha.
                ubicacion=ubicacion,
                descripcion=limpiar_html(str(tarjeta))[:1200],
                salario=salario,
                extra={"consulta": consulta, "id_occ": id_occ, "recencia": recencia},
            )
        )
    return salida


# Paginas por consulta. Antes solo se leia la primera, que son ~20 resultados:
# eso dejaba fuera la mayor parte de la bolsa de Monterrey.
PAGINAS_OCC = 8

# Terminos SUELTOS, sin guiones. Todas las consultas de `CONSULTAS_MX` son
# frases ("practicante-ciberseguridad"), y OCC las trata como un Y logico: solo
# devuelve lo que lleva las dos palabras. Medido en Nuevo Leon:
#
#   practicante-ciberseguridad  ->   24 vacantes
#   ciberseguridad              ->  107 vacantes (79 afines al perfil)
#   practicante                 -> 1.024 vacantes segun OCC
#
# El termino suelto rinde entre 4 y 16 veces mas. Van aparte porque merecen
# mas profundidad: son pocos y son los que traen volumen de verdad. Tambien
# salen de las areas activas (ver `areas.py`).
def consultas_amplias() -> list[str]:
    return areas.consultas_amplias_occ()

# Con 1.024 resultados para "practicante", cortar en la pagina 8 deja fuera el
# 80%. Se comprobo que la pagina 20 sigue devolviendo tarjetas nuevas.
PAGINAS_OCC_AMPLIAS = 20


def occ_mundial(hilos: int = 16) -> list[dict]:
    tareas = []
    zonas = zonas_occ()
    with ThreadPoolExecutor(max_workers=hilos) as ex:
        for consulta in consultas_mx():
            for zona in zonas:
                for pagina in range(1, PAGINAS_OCC + 1):
                    tareas.append(ex.submit(_occ_una, consulta, zona, pagina))
        resultados = []
        for f in tareas:
            try:
                resultados.extend(f.result())
            except Exception:
                pass
    return resultados


# ------------------------------------------------------------- Computrabajo ----

def zonas_ct() -> list[str]:
    return areas.zonas_computrabajo()


def _ct_una(consulta: str, zona: str, pagina: int = 1) -> list[dict]:
    url = f"https://mx.computrabajo.com/trabajo-de-{consulta}"
    if zona:
        url += f"-{zona}"
    if pagina > 1:
        url += f"?p={pagina}"
    codigo, html = obtener_texto(url)
    if codigo != 200 or "box_offer" not in html:
        return []

    sopa = BeautifulSoup(html, "lxml")
    salida = []
    for art in sopa.select("article.box_offer"):
        enlace = art.find("a", class_=re.compile("js-o-link"))
        if not enlace:
            continue
        titulo = enlace.get_text(strip=True)
        href = enlace.get("href", "").split("#")[0]
        if not href.startswith("http"):
            href = "https://mx.computrabajo.com" + href

        parrafos = [p.get_text(" ", strip=True) for p in art.find_all("p")]
        empresa = ""
        enlace_emp = art.find("a", href=re.compile(r"/empresas/"))
        if enlace_emp:
            empresa = enlace_emp.get_text(strip=True)
        if not empresa and parrafos:
            empresa = parrafos[0].split("\n")[0][:60] or "Confidencial"

        # El mismo fallo que tenia OCC, y aqui peor: el patron anterior solo
        # buscaba topónimos de Nuevo Leon y, si no encontraba ninguno, ponia
        # "Nuevo Leon, Mexico" por defecto. Una vacante de Guadalajara no
        # casaba con nada y quedaba registrada como monterreyana.
        #
        # Medido el 24-ago-2026: **221 de 230 vacantes de Computrabajo (96%)**
        # decian Nuevo Leon. El colector no podia representar otra cosa.
        #
        # Ahora se busca contra los estados del pais, sin presuponer ninguno, y
        # si no aparece se deja VACIO. No saber es un dato; inventar, no.
        ubicacion = next((p for p in parrafos if _ESTADOS.search(p)), "")
        salario = next((p for p in parrafos if re.search(r"\$\s?[\d,]+", p)), "")

        salida.append(
            vacante(
                titulo=titulo,
                empresa=empresa or "Confidencial",
                url=href,
                fuente="computrabajo",
                ubicacion=ubicacion,
                descripcion=limpiar_html(str(art))[:1200],
                salario=salario,
                extra={"consulta": consulta, "id_ct": art.get("data-id", "")},
            )
        )
    return salida


PAGINAS_CT = 6


def computrabajo(hilos: int = 16) -> list[dict]:
    tareas = []
    zonas = zonas_ct()
    with ThreadPoolExecutor(max_workers=hilos) as ex:
        for consulta in consultas_mx():
            for zona in zonas:
                for pagina in range(1, PAGINAS_CT + 1):
                    tareas.append(ex.submit(_ct_una, consulta, zona, pagina))
        resultados = []
        for f in tareas:
            try:
                resultados.extend(f.result())
            except Exception:
                pass
    return resultados


def recolectar_todo() -> tuple[list[dict], dict]:
    v_occ = occ_mundial()
    log(f"  occ: {len(v_occ)} vacantes")
    v_ct = computrabajo()
    log(f"  computrabajo: {len(v_ct)} vacantes")
    return v_occ + v_ct, {"occ": len(v_occ), "computrabajo": len(v_ct)}


if __name__ == "__main__":
    vs, _ = recolectar_todo()
    log(f"TOTAL MEXICO: {len(vs)} vacantes crudas")
    vistos = set()
    for v in vs[:25]:
        if v["titulo"] in vistos:
            continue
        vistos.add(v["titulo"])
        print(f"  - {v['titulo'][:55]:55} | {v['empresa'][:28]:28} | {v['ubicacion'][:28]}")
