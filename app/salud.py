"""
Salud de los datos: comprueba invariantes y grita cuando algo se desvia.

Por que existe. El 24 de agosto de 2026 se encontraron CUATRO fallos que
llevaban meses activos y ninguno lanzaba un error:

  1. El colector de OCC escribia `ubicacion or "Nuevo Leon, Mexico"`: cuando no
     leia la ciudad, AFIRMABA Nuevo Leon. De 82 fichas comprobadas, 8 lo eran.
  2. `limpiar_html` decodificaba una lista a mano sin las vocales acentuadas:
     561 descripciones guardaban "econ&oacute;mico" y los filtros no las veian.
  3. Con esas descripciones rotas, 88 vacantes ocultaban los anios de
     experiencia que exigian. Una se anunciaba "Junior" y pedia tres anios.
  4. Indeed, tras ~120 peticiones, devolvia paginas recortadas donde TODAS
     salian vivas y sin datos.

Los cuatro se encontraron por casualidad, abriendo vacantes a mano. Ese es el
argumento entero de este modulo: un fallo que no avisa cuesta meses; uno que
avisa cuesta una tarde.

La boveda ya cierra con "VERIFICACION DE LA BOVEDA: correcta" y aborta si se
rompe una de sus ocho reglas. Esto es lo mismo para los datos.

Uso:
    python salud.py          # informe en pantalla
    python salud.py --json   # solo el JSON, para encadenar
"""
from __future__ import annotations

import argparse
import json

import areas
from almacen import conexion
from nucleo import DATOS, ahora_iso

ARCHIVO = DATOS / "salud.json"


def _uno(con, nombre: str, sql: str, tope: int, explica: str,
         parametros: tuple = ()) -> dict:
    """Una comprobacion: cuenta filas malas y las compara con su tope."""
    n = con.execute(sql, parametros).fetchone()[0]
    return {"nombre": nombre, "valor": n, "tope": tope,
            "ok": n <= tope, "explica": explica}


def _desajuste_experiencia(con) -> dict:
    """Cuenta vacantes cuya columna no coincide con lo que el extractor dice HOY.

    La primera version de esta prueba buscaba "anos de experiencia" en el texto
    y exigia que la columna tuviera valor. Daba 15 fallos y **casi todos eran
    falsos**: "empresa con mas de 50 anos de experiencia en el mercado" no es un
    requisito, y el extractor acierta al ignorarlo. Una prueba que grita sin
    motivo se acaba ignorando, y entonces no sirve para nada.

    Esta compara la columna guardada contra lo que `anos_exigidos` devuelve
    ahora. Asi detecta lo unico que importa de verdad: que el codigo mejoro y
    la base se quedo atras. Es como se encontro el caso de "Al menos SIETE
    anos", escrito con letra, que el extractor no sabia leer.
    """
    import experiencia

    filas = con.execute(
        "SELECT titulo, descripcion, anios_exigidos FROM vacantes "
        "WHERE descripcion IS NOT NULL AND LENGTH(descripcion) > 150").fetchall()
    desajustes = sum(
        1 for f in filas
        if experiencia.anos_exigidos(f["titulo"] or "", f["descripcion"] or "")["minimo"]
        != f["anios_exigidos"])
    return {"nombre": "experiencia-desajustada", "valor": desajustes, "tope": 0,
            "ok": desajustes == 0,
            "explica": "la columna anios_exigidos no coincide con lo que el "
                       "extractor calcula hoy: hay que recalcular"}


# Cada entrada nace de un fallo real. El tope no es una opinion: es el numero
# por encima del cual ese fallo ya costo tiempo antes.
def revisar() -> dict:
    # "El carril": las areas prioritarias activas (ver `areas.py`).
    en_areas = areas.sql_literal_in("area", areas.valores_prioritarios())
    with conexion() as con:
        vivas = ("(ver_estado IS NULL OR ver_estado != 'cerrada') "
                 "AND (aplicada IS NULL OR aplicada = 0)")

        pruebas = [
            _uno(con, "html-sin-decodificar",
                 "SELECT COUNT(*) FROM vacantes WHERE descripcion LIKE '%&oacute;%' "
                 "OR descripcion LIKE '%&aacute;%' OR descripcion LIKE '%&nbsp;%' "
                 "OR descripcion LIKE '%&iacute;%' OR descripcion LIKE '%&ntilde;%'",
                 0,
                 "descripciones con entidades HTML a medias: los filtros no las leen"),

            _desajuste_experiencia(con),

            # Las que ya se descartaron A MANO no cuentan: llevan motivo
            # escrito ("el anuncio dice otra ciudad"), o sea que la geografia
            # SI estaba comprobada, solo que por ojo humano y no por la ficha.
            # `SQL_VIABLE` ya las excluye de la cola y del ranking: no le
            # cuestan un gesto a nadie.
            #
            # El motivo de fondo es que un indicador que NO PUEDE llegar a
            # verde deja de ser un indicador. Si el rojo incluye casos ya
            # resueltos, se aprende a ignorarlo, y el dia que marque algo real
            # tampoco se mirara. Marcar solo lo accionable es lo que hace que
            # valga la pena mirarlo.
            _uno(con, "ubicacion-inventada",
                 f"SELECT COUNT(*) FROM vacantes WHERE {vivas} "
                 "AND LOWER(COALESCE(ubicacion,'')) = 'nuevo leon, mexico' "
                 "AND ubicacion_ficha IS NULL "
                 "AND (descartada_motivo IS NULL OR descartada_motivo = '') "
                 f"AND {en_areas}",
                 0,
                 "vacantes del carril que dicen Nuevo Leon sin que nadie lo haya comprobado"),

            _uno(con, "envio-sin-prueba",
                 "SELECT COUNT(*) FROM candidaturas "
                 "WHERE estado = 'pendiente-acuse' AND enviada IS NOT NULL "
                 "AND julianday('now') - julianday(enviada) > 5",
                 0,
                 "postulaciones por portal que llevan 5 dias sin acuse: puede que "
                 "el envio fallara en silencio, como los cuatro del 24-ago-2026"),

            _uno(con, "candidatura-sin-ancla",
                 "SELECT COUNT(*) FROM candidaturas WHERE estado = 'enviada' "
                 "AND via NOT LIKE 'portal-%' AND hilo_gmail IS NULL "
                 "AND enviada IS NOT NULL AND julianday('now') - julianday(enviada) > 2",
                 0,
                 "correos enviados hace mas de 2 dias que el seguimiento no logro anclar"),

            _uno(con, "contacto-rebotado-en-uso",
                 "SELECT COUNT(*) FROM contactos WHERE confianza = 'rebotado' "
                 "AND correo IS NOT NULL "
                 "AND id IN (SELECT contacto_id FROM candidaturas "
                 "           WHERE estado IN ('borrador','propuesta'))",
                 0,
                 "hay un borrador dirigido a una direccion que ya reboto"),

            _uno(con, "detalle-a-medias",
                 "SELECT COUNT(*) FROM vacantes WHERE detalle_fecha IS NOT NULL "
                 "AND ubicacion_ficha IS NULL AND req_contratacion IS NULL "
                 "AND (ver_estado IS NULL OR ver_estado != 'cerrada')",
                 20,
                 "fichas selladas como leidas que no trajeron ni un campo: posible recorte del portal"),

            _uno(con, "sin-verificar-viejas",
                 f"SELECT COUNT(*) FROM vacantes WHERE {vivas} AND ver_estado IS NULL "
                 f"AND {en_areas} "
                 "AND nivel IN ('practicas','junior')",
                 40,
                 "vacantes del carril que nadie ha comprobado si siguen vivas"),
        ]

        # Contexto: no son fallos, son cifras para leer el informe.
        contexto = {
            "vacantes": con.execute("SELECT COUNT(*) FROM vacantes").fetchone()[0],
            "en_carril": con.execute(
                f"SELECT COUNT(*) FROM vacantes WHERE {vivas} "
                f"AND {en_areas} "
                "AND nivel IN ('practicas','junior')").fetchone()[0],
            "candidaturas_vivas": con.execute(
                "SELECT COUNT(*) FROM candidaturas "
                "WHERE estado NOT IN ('borrador','descartada')").fetchone()[0],
            "con_ficha_leida": con.execute(
                "SELECT COUNT(*) FROM vacantes WHERE detalle_fecha IS NOT NULL").fetchone()[0],
            # Cuantas mentia la tarjeta. Es CONTEXTO, no una prueba: sube
            # cuando el sistema mejora, porque cada ficha nueva puede destapar
            # otra. Estuvo un rato como prueba con tope 250 y se puso roja al
            # pasar de 149 a 285 --es decir, al descubrir 136 mentiras mas--.
            # Una comprobacion que se enciende cuando las cosas van mejor es
            # una comprobacion mal planteada.
            # Solo con la zona base de Monterrey, que es donde se midio:
            # tarjetas que decian Nuevo Leon y cuya ficha dice otra cosa.
            "ubicacion_desmentida": (con.execute(
                "SELECT COUNT(*) FROM vacantes WHERE ubicacion_ficha IS NOT NULL "
                "AND LOWER(COALESCE(ubicacion,'')) LIKE '%nuevo le%' "
                "AND LOWER(ubicacion_ficha) NOT LIKE '%nuevo le%' "
                "AND LOWER(ubicacion_ficha) NOT LIKE '%monterrey%'").fetchone()[0]
                if areas.zona_clave() == "monterrey" else None),
        }

    fallos = [p for p in pruebas if not p["ok"]]
    informe = {"fecha": ahora_iso(), "correcta": not fallos,
               "pruebas": pruebas, "fallos": [f["nombre"] for f in fallos],
               "contexto": contexto}
    ARCHIVO.write_text(json.dumps(informe, ensure_ascii=False, indent=1),
                       encoding="utf-8")
    return informe


def imprimir(informe: dict) -> None:
    c = informe["contexto"]
    print(f"  {c['vacantes']} vacantes | {c['en_carril']} en el carril | "
          f"{c['con_ficha_leida']} con ficha leida | "
          f"{c['candidaturas_vivas']} candidaturas vivas")
    if c["ubicacion_desmentida"] is not None:
        print(f"  {c['ubicacion_desmentida']} vacantes decian Nuevo Leon y la ficha "
              f"dice otra cosa (cuanto mas alto, mas mentiras descubiertas)")
    print()
    for p in informe["pruebas"]:
        marca = "ok  " if p["ok"] else "MAL "
        print(f"  [{marca}] {p['nombre']:26} {p['valor']:5} (tope {p['tope']})")
        if not p["ok"]:
            print(f"           -> {p['explica']}")
    print()
    if informe["correcta"]:
        print("  SALUD DE LOS DATOS: correcta")
    else:
        print(f"  SALUD DE LOS DATOS: HAY {len(informe['fallos'])} PROBLEMAS -> "
              + ", ".join(informe["fallos"]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Invariantes de los datos")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    inf = revisar()
    if a.json:
        print(json.dumps(inf, ensure_ascii=False))
    else:
        imprimir(inf)
