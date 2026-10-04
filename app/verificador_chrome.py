"""
Capa 3 de verificación: Chrome real, para sitios que bloquean el HTTP anónimo.

Por qué hace falta. OCC Mundial responde **403** a cualquier petición directa
a la ficha de una vacante: tiene protección anti-bot. El listado sí se puede
leer, pero la ficha individual no. Eso dejaba 109 vacantes de la zona base
en estado `sin-verificar`.

Cómo se resuelve. Desde una pestaña ya abierta en el dominio, se lanzan
peticiones `fetch` del mismo origen. Llevan las cookies y la huella del
navegador real, así que el sitio responde con normalidad.

El método se validó con un control negativo: IDs inexistentes devuelven 404 con
una página de 29 KB, mientras que las vacantes reales devuelven 200 con ~128 KB.
La comprobación distingue de verdad, no siempre dice que sí.

Este módulo aplica al conjunto de datos los resultados obtenidos en Chrome.
El JavaScript que se ejecuta en la pestaña está en `PLANTILLA_JS`.
"""
from __future__ import annotations

import json

from nucleo import DATOS, ahora_iso, cargar_json, guardar_json, log

ARCHIVO = "verificacion_chrome.json"

# Se ejecuta en una pestaña abierta en el dominio a verificar.
# Los ids se inyectan sustituyendo __IDS__.
PLANTILLA_JS = r"""
const ids = __IDS__;
const res = {};
const uno = async (id) => {
  try {
    const r = await fetch(`/empleo/oferta/${id}/`, {credentials:'include', redirect:'follow'});
    const t = (await r.text()).toLowerCase();
    let estado = 'sin-verificar';
    if (r.status === 404 || r.status === 410) estado = 'cerrada';
    else if (/ya no est[aá] disponible|vacante no disponible|oferta expirada|no encontramos|ya fue ocupada|no existe/.test(t)) estado = 'cerrada';
    else if (/postularme|postularte|postular ahora|enviar cv|aplicar a esta/.test(t)) estado = 'viva';
    else if (r.status === 200 && t.includes('<h1')) estado = 'viva';
    res[id] = {estado, http: r.status, len: t.length};
  } catch (e) { res[id] = {estado:'inaccesible', http:0}; }
};
for (let i = 0; i < ids.length; i += 8) {
  await Promise.all(ids.slice(i, i+8).map(uno));
}
JSON.stringify(res)
"""


# Segunda cosecha del MISMO viaje. La plantilla de arriba se baja la ficha
# entera, mira si la vacante vive y tira el HTML. Pero esa ficha trae, ya
# etiquetados por la propia bolsa, los campos que deciden si se puede
# postular o no:
#
#     Educacion minima requerida: Universitario titulado   <- descarto 3
#     Contratacion: Medio tiempo                           <- el horario
#     Espacio de trabajo: Presencial                       <- descarto 4
#     EMPRESA en Ciudad, Estado                            <- la ubicacion REAL
#
# El 24-ago-2026 se abrieron doce vacantes a mano para averiguar justo esto.
# Con estos cuatro campos en la base, esas doce se filtran con SQL y no se
# abre ninguna. No cuesta ni una peticion mas: es el mismo HTML.
def plantilla_detalle(ids: list[str]) -> str:
    """El JS listo para pegar en una pestana de OCC, con los ids dentro.

    El codigo vive en `detalle_occ.js`, no en una cadena de Python. Meterlo en
    un heredoc convirtio los saltos escapados de las expresiones regulares en
    saltos de linea reales y dejo la plantilla rota sin que nada avisara.
    """
    from pathlib import Path
    js = (Path(__file__).resolve().parent / "detalle_occ.js").read_text(encoding="utf-8")
    return js.replace("__IDS__", json.dumps(ids))


def guardar_detalle(resultados: dict[str, dict]) -> int:
    """Vuelca a la BASE los campos estructurados leidos de cada ficha.

    UPDATE de columnas concretas, nunca `guardar()`: reanalizar por la via de
    una corrida nueva es lo que envenono `avistamientos` en su dia.
    """
    from almacen import conexion

    escritas = 0
    with conexion() as con:
        for id_ext, r in resultados.items():
            # Dos formas de URL: OCC pone el id entre barras
            # (/empleo/oferta/21274505/) e Indeed lo cuelga de la query
            # (?jk=b544f1cd3d1e62d5). Los ids de Indeed son hexadecimales de
            # 16 caracteres; los de OCC, digitos.
            patron = f"%/{id_ext}/%" if id_ext.isdigit() else f"%jk={id_ext}%"

            # Una vacante cerrada no deja campos que guardar, y sin marcarla
            # volvia a salir en la siguiente tanda: 38 de las primeras 100
            # eran repeticiones de 404 ya vistos. El 404 del portal SI es
            # autoritativo (a diferencia de un 403 o un 429), asi que se cierra.
            if r.get("estado") == "cerrada":
                con.execute(
                    "UPDATE vacantes SET ver_estado='cerrada', ver_metodo='chrome-ficha', "
                    "ver_detalle='404 al leer la ficha', ver_fecha=?, detalle_fecha=? "
                    "WHERE url LIKE ?", (ahora_iso(), ahora_iso(), patron))
                escritas += 1
                continue

            if not any(r.get(k) for k in
                       ("educacion", "contratacion", "horario", "espacio", "ubicacion")):
                # Ni se sella a la primera ni se relee eternamente: se cuenta.
                #
                # Sellar a la primera costo 257 vacantes (160 de Indeed, 97 de
                # OCC) marcadas como leidas sin un solo campo, invisibles para
                # siempre porque todo lo pendiente se busca por
                # `detalle_fecha IS NULL`. Una lectura vacia casi nunca
                # significa "la ficha no trae eso": significa que Indeed
                # estrangulo o que OCC devolvio el armazon de su SPA.
                con.execute(
                    "UPDATE vacantes SET "
                    "  detalle_intentos = COALESCE(detalle_intentos, 0) + 1, "
                    "  detalle_fecha = CASE WHEN COALESCE(detalle_intentos,0) + 1 >= 3 "
                    "                       THEN ? ELSE detalle_fecha END "
                    "WHERE url LIKE ?", (ahora_iso(), patron))
                continue
            cur = con.execute(
                """UPDATE vacantes
                   SET req_educacion    = COALESCE(NULLIF(?, ''), req_educacion),
                       req_contratacion = COALESCE(NULLIF(?, ''), req_contratacion),
                       req_horario      = COALESCE(NULLIF(?, ''), req_horario),
                       req_espacio      = COALESCE(NULLIF(?, ''), req_espacio),
                       ubicacion_ficha  = COALESCE(NULLIF(?, ''), ubicacion_ficha),
                       detalle_fecha    = ?
                   WHERE url LIKE ?""",
                (r.get("educacion", ""), r.get("contratacion", ""), r.get("horario", ""),
                 r.get("espacio", ""), r.get("ubicacion", ""), ahora_iso(),
                 patron))
            escritas += cur.rowcount

            # Una lectura que trae campos pero NO la ubicacion cuenta como
            # intento. Sin esto, la relectura del segundo grupo de
            # `ids_para_detalle` no tendria tope y esas fichas volverian en
            # cada tanda para siempre, robandole el sitio a las que nadie ha
            # mirado. Con tope, se intentan tres veces y se dejan estar.
            if not r.get("ubicacion"):
                con.execute(
                    "UPDATE vacantes SET detalle_intentos = COALESCE(detalle_intentos, 0) + 1 "
                    "WHERE url LIKE ?", (patron,))
    log(f"  detalle de ficha guardado en {escritas} vacantes")
    return escritas


def ids_para_detalle(limite: int = 60) -> list[str]:
    """Las vacantes del carril a las que aun les falta el detalle de ficha.

    Se priorizan las que tienen la ubicacion en blanco o generica: son las que
    mas mienten y las que mas se abren a mano.

    DOS GRUPOS, no uno, y el segundo se anadio el 28-ago-2026 al encontrar
    esto: **una lectura PARCIAL sellaba la ficha para siempre**. Doce vacantes
    del carril se leyeron el 24-ago, trajeron educacion y contratacion pero no
    la ubicacion, y `detalle_fecha` quedo puesta. A partir de ahi eran
    invisibles para esta consulta --que buscaba solo `detalle_fecha IS NULL`--
    mientras seguian diciendo "Nuevo Leon, Mexico" sin que nadie lo hubiera
    comprobado. `salud.py` las marcaba en rojo y no habia forma de arreglarlas:
    la unica cola que podia hacerlo no las veia.

    Es el mismo error que costo 257 vacantes selladas en vacio, una vuelta de
    tuerca mas fina: alli la lectura no traia NADA y se sello; aqui trae algo,
    pero no lo que importa. `detalle_intentos` sigue poniendo el tope, asi que
    una ficha que de verdad no publica su ciudad no se relee eternamente.

    Y de paso cierra las muertas: releer una vacante que hoy da 404 hace que
    `guardar_detalle` la marque `cerrada`. De las doce, la primera comprobada
    ya no existia.
    """
    import areas
    from almacen import conexion

    with conexion() as con:
        filas = con.execute(f"""
            SELECT url FROM vacantes
            WHERE url LIKE '%occ.com.mx%'
              AND (aplicada IS NULL OR aplicada = 0)
              AND descartada_motivo IS NULL
              AND (ver_estado IS NULL OR ver_estado != 'cerrada')
              AND {areas.sql_literal_in("area", areas.valores_prioritarios())}
              AND (
                    detalle_fecha IS NULL
                    -- leida a medias: falta justo el dato que decide si se
                    -- puede postular sin mudarse
                    OR (ubicacion_ficha IS NULL
                        AND LOWER(COALESCE(ubicacion,'')) IN ('', 'nuevo leon, mexico')
                        AND COALESCE(detalle_intentos, 0) < 3)
                  )
            ORDER BY (LOWER(COALESCE(ubicacion,'')) IN ('', 'nuevo leon, mexico')) DESC,
                     score DESC
            LIMIT ?""", (limite,)).fetchall()
    import re as _re
    return [m.group(1) for f in filas
            if (m := _re.search(r"/oferta/(\d+)/", f["url"]))]


def ids_pendientes(fuente: str = "occ") -> list[str]:
    """IDs de una fuente que siguen sin verificación concluyente."""
    vacantes = cargar_json("vacantes.json", []) or []
    return [
        v["extra"].get("id_occ")
        for v in vacantes
        if v.get("fuente", "").split(":")[0] == fuente
        and v.get("verificacion", {}).get("estado") != "viva"
        and v.get("extra", {}).get("id_occ")
    ]


def registrar(resultados: dict[str, dict], fuente: str = "occ") -> None:
    """Guarda los resultados obtenidos en Chrome para aplicarlos al dataset."""
    previo = cargar_json(ARCHIVO, {}) or {}
    previo.setdefault(fuente, {})
    for id_ext, r in resultados.items():
        previo[fuente][id_ext] = {
            "estado": r.get("estado", "sin-verificar"),
            "http": r.get("http", 0),
            "fecha": ahora_iso(),
            "metodo": "chrome-fetch-mismo-origen",
            "detalle": (
                f"HTTP {r.get('http')} desde una pestana real de {fuente}; "
                "los IDs inexistentes devuelven 404 en este mismo control"
            ),
        }
    guardar_json(ARCHIVO, previo)
    log(f"  registradas {len(resultados)} verificaciones de Chrome para '{fuente}'")


def aplicar(vacantes: list[dict]) -> int:
    """Sobrescribe la verificación de las vacantes que Chrome sí pudo comprobar."""
    datos = cargar_json(ARCHIVO, {}) or {}
    aplicadas = 0
    for v in vacantes:
        fuente = v.get("fuente", "").split(":")[0]
        tabla = datos.get(fuente)
        if not tabla:
            continue
        id_ext = v.get("extra", {}).get(f"id_{fuente}")
        if id_ext and id_ext in tabla:
            v["verificacion"] = dict(tabla[id_ext])
            aplicadas += 1
    return aplicadas


if __name__ == "__main__":
    pend = ids_pendientes()
    print(f"{len(pend)} ids pendientes de verificar en Chrome")
    print("Ejecuta este JavaScript en una pestana abierta en www.occ.com.mx:\n")
    print(PLANTILLA_JS.replace("__IDS__", json.dumps(pend)))

def plantilla_indeed(ids: list[str]) -> str:
    """El JS para leer fichas de Indeed, con los jk inyectados."""
    from pathlib import Path
    js = (Path(__file__).resolve().parent / "detalle_indeed.js").read_text(encoding="utf-8")
    return js.replace("__IDS__", json.dumps(ids))


def jks_para_detalle(limite: int = 200) -> list[str]:
    """Vacantes de Indeed a las que falta leerles la ficha.

    Se piden TODAS las vivas, no solo las del carril: la bandera
    `isJobExpired` es lo unico que distingue una vacante muerta de una viva en
    Indeed, y arrastrar muertas ensucia cualquier conteo posterior.
    """
    import json as _json
    from almacen import conexion

    with conexion() as con:
        filas = con.execute("""
            SELECT extra FROM vacantes
            WHERE url LIKE '%indeed%'
              AND ubicacion_ficha IS NULL
              AND (aplicada IS NULL OR aplicada = 0)
              AND (ver_estado IS NULL OR ver_estado != 'cerrada')
            ORDER BY score DESC
            LIMIT ?""", (limite,)).fetchall()
    jks = []
    for f in filas:
        try:
            jk = (_json.loads(f["extra"] or "{}") or {}).get("jk")
        except Exception:
            jk = None
        if jk:
            jks.append(jk)
    return jks
