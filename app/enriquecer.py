"""
Enriquecimiento por HTTP directo: fuentes que no bloquean al robot.

Por que existe aparte. OCC responde 403 a Python e Indeed estrangula tras cien
peticiones, asi que sus fichas hay que leerlas desde una pestana del navegador
(`detalle_occ.js`, `detalle_indeed.js`). Computrabajo NO: responde 200 a una
peticion normal y trae JSON-LD. Eso lo hace la unica fuente que se puede
enriquecer sin que nadie abra Chrome, y por tanto la unica que encaja entera
dentro del ciclo diario automatico.

Que se arregla con esto. El colector de Computrabajo tenia el mismo defecto que
el de OCC, y peor: su patron de ubicacion solo buscaba toponimos de Nuevo Leon
y, al no encontrarlos, escribia "Nuevo Leon, Mexico" por defecto. Medido el
24-ago-2026: **221 de 230 vacantes (96%) decian Nuevo Leon**. El colector ya no
inventa, pero las que estan en la base necesitan que alguien vaya a mirar.

Uso:
    python enriquecer.py --computrabajo 60
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re

from almacen import conexion
from nucleo import log, obtener_texto

# Computrabajo intercambia los campos respecto a schema.org: pone el ESTADO en
# `addressLocality` y la CIUDAD en `addressRegion`. Comprobado en cinco fichas
# de estados distintos, siempre igual. Se leen en ese orden invertido a
# proposito; corregirlo "hacia el estandar" produciria "Nuevo Leon, San Pedro".
_RX = {
    "estado": re.compile(r'"addressLocality"\s*:\s*"([^"]{0,60})"'),
    "ciudad": re.compile(r'"addressRegion"\s*:\s*"([^"]{0,60})"'),
    "tipo": re.compile(r'"employmentType"\s*:\s*"([^"]{0,30})"'),
    "caduca": re.compile(r'"validThrough"\s*:\s*"(\d{4}-\d{2}-\d{2})'),
}

# El JSON-LD llega con los acentos escapados ("Nuevo León").
def _texto(valor: str) -> str:
    try:
        return json.loads(f'"{valor}"')
    except Exception:
        return valor


CONTRATO = {"FULL_TIME": "Tiempo completo", "PART_TIME": "Medio tiempo",
            "INTERN": "Practicas", "TEMPORARY": "Temporal",
            "CONTRACTOR": "Honorarios"}


def _ciudad_de_url(url: str) -> str:
    """Respaldo cuando la ficha no trae direccion: la URL lleva el slug.

    Las de Computrabajo terminan en "...-en-cuautitlan-izcalli-B2A3224B...".
    No es tan bueno como el JSON-LD --no dice el estado-- pero es infinitamente
    mejor que dar por hecho que esta en la zona de busqueda.
    """
    # El `.*` inicial es deliberado: obliga a quedarse con el ULTIMO "-en-".
    # Sin el, una vacante titulada "Especialista en seguridad de la
    # informacion" hacia que el respaldo devolviera "Seguridad De La
    # Informacion" como ciudad, porque casaba con el primer "-en-" del titulo.
    m = re.search(r".*-en-([a-z-]+?)-[0-9A-F]{8,}", url or "")
    if not m:
        return ""
    ciudad = m.group(1).replace("-", " ").title()
    # Y una ciudad no tiene seis palabras: si sale algo asi, es el titulo otra
    # vez y es mejor no saber que afirmar una tonteria.
    return ciudad if len(ciudad.split()) <= 4 else ""


def computrabajo(limite: int = 60) -> dict:
    """Lee las fichas de Computrabajo pendientes y guarda lo que dicen."""
    import verificador_chrome as vc

    with conexion() as con:
        filas = con.execute("""
            SELECT id, url FROM vacantes
            WHERE fuente = 'computrabajo'
              AND ubicacion_ficha IS NULL
              AND (aplicada IS NULL OR aplicada = 0)
              AND (ver_estado IS NULL OR ver_estado != 'cerrada')
            ORDER BY score DESC
            LIMIT ?""", (limite,)).fetchall()

    hoy = dt.date.today()
    resultados, cerradas, sin_datos = {}, 0, 0

    for f in filas:
        codigo, html = obtener_texto(f["url"], timeout=20)
        clave = f["id"]

        # 404/410 del portal: eso SI cierra. Un 403 o un 429 significan
        # "no me dejan mirar" y no se tocan.
        if codigo in (404, 410):
            resultados[clave] = {"estado": "cerrada"}
            cerradas += 1
            continue
        if codigo != 200 or not html:
            continue

        caduca = _RX["caduca"].search(html)
        if caduca and dt.date.fromisoformat(caduca.group(1)) < hoy:
            resultados[clave] = {"estado": "cerrada"}
            cerradas += 1
            continue

        estado = _texto((_RX["estado"].search(html) or [None, ""])[1])
        ciudad = _texto((_RX["ciudad"].search(html) or [None, ""])[1])
        tipo = (_RX["tipo"].search(html) or [None, ""])[1]

        ubicacion = ", ".join(x for x in (ciudad, estado) if x) or _ciudad_de_url(f["url"])
        if not ubicacion and not tipo:
            sin_datos += 1
            continue

        resultados[clave] = {
            "estado": "viva",
            "ubicacion": ubicacion,
            "contratacion": CONTRATO.get(tipo, ""),
            "educacion": "", "horario": "", "espacio": "",
        }

    # `guardar_detalle` empareja por URL, asi que se le pasan las claves que
    # entiende: aqui son ids internos, no numeros de oferta.
    escritas = _guardar(resultados)
    log(f"  computrabajo: {len(filas)} leidas, {escritas} escritas, "
        f"{cerradas} cerradas, {sin_datos} sin datos")
    return {"leidas": len(filas), "escritas": escritas, "cerradas": cerradas}


def _guardar(resultados: dict[str, dict]) -> int:
    """Escribe por id interno. UPDATE de columnas concretas, nunca guardar()."""
    from nucleo import ahora_iso

    n = 0
    with conexion() as con:
        for ident, r in resultados.items():
            if r.get("estado") == "cerrada":
                con.execute(
                    "UPDATE vacantes SET ver_estado='cerrada', ver_metodo='ficha-http', "
                    "ver_detalle='la ficha dice que caduco o devolvio 404', "
                    "ver_fecha=?, detalle_fecha=? WHERE id=?",
                    (ahora_iso(), ahora_iso(), ident))
                n += 1
                continue
            con.execute(
                "UPDATE vacantes SET "
                " ubicacion_ficha  = COALESCE(NULLIF(?,''), ubicacion_ficha),"
                " req_contratacion = COALESCE(NULLIF(?,''), req_contratacion),"
                " detalle_fecha    = ? WHERE id=?",
                (r.get("ubicacion", ""), r.get("contratacion", ""), ahora_iso(), ident))
            n += 1
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--computrabajo", type=int, default=60,
                    help="cuantas fichas leer en esta tanda")
    a = ap.parse_args()
    print(computrabajo(a.computrabajo))
