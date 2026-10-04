"""
Orquestador de ULTRA CHAMBA.

Ejecuta el flujo completo:
  recolectar -> deduplicar -> analizar -> filtrar -> verificar -> guardar

Uso:
    python pipeline.py            # corrida completa
    python pipeline.py --rapido   # sin verificación HTTP (solo ATS)
"""
from __future__ import annotations

import sys
from collections import Counter

import analisis
import areas
import fuentes_ats
import fuentes_boards
import fuentes_linkedin
import fuentes_mexico
import verificador
import verificador_chrome
from nucleo import guardar_json, log

# Umbral por debajo del cual la vacante ni siquiera se verifica: no vale
# el coste de red y solo ensuciaría el dashboard.
UMBRAL_MINIMO = 40


def ejecutar(rapido: bool = False) -> dict:
    log("=" * 62)
    log("ULTRA CHAMBA — pipeline de busqueda de empleo")
    log("=" * 62)

    # --- 1. Recolección -----------------------------------------------------
    log("\n[1/5] RECOLECCION")
    log(" ATS oficiales (fuente primaria):")
    v_ats, informe_ats = fuentes_ats.recolectar_todo()

    log(" Bolsas remotas globales:")
    v_boards, informe_boards = fuentes_boards.recolectar_todo()

    log(" Bolsas de Mexico:")
    v_mx, informe_mx = fuentes_mexico.recolectar_todo()

    log(" LinkedIn (API publica de invitado, sin sesion):")
    v_li = fuentes_linkedin.recolectar_todo()
    log(f"  linkedin: {len(v_li)} vacantes con descripcion y verificacion")

    crudas = v_ats + v_boards + v_mx + v_li
    log(f" TOTAL CRUDO: {len(crudas)} vacantes")

    # --- 2. Deduplicación ---------------------------------------------------
    log("\n[2/5] DEDUPLICACION")
    unicas = analisis.deduplicar(crudas)
    log(f" {len(crudas)} -> {len(unicas)} unicas ({len(crudas) - len(unicas)} duplicadas)")

    # --- 3. Análisis y scoring ---------------------------------------------
    log("\n[3/5] ANALISIS Y SCORING contra el perfil configurado")
    analizadas = analisis.analizar_lote(unicas)
    por_veredicto = Counter(v["veredicto"] for v in analizadas)
    for veredicto in ("aplicar-ya", "buen-fit", "explorar", "descartado"):
        log(f"  {veredicto:12} {por_veredicto.get(veredicto, 0):5}")

    # --- 4. Filtrado --------------------------------------------------------
    log("\n[4/5] FILTRADO")
    relevantes = [
        v for v in analizadas
        if v["score"] >= UMBRAL_MINIMO and v["elegible_mx"] and v["area"] != "fuera"
    ]

    # Zona gris: remotas con sede en el extranjero que NO declaran ninguna
    # restricción legal. No son elegibles con certeza, pero tampoco están
    # cerradas: muchas empresas contratan contractors desde LatAm. Se incluyen
    # marcadas, para que la decisión sea de la persona y no del filtro.
    prioritarias = areas.valores_prioritarios()
    zona_gris = [
        v for v in analizadas
        if not v["elegible_mx"]
        and v["modalidad"] == "remoto"
        and v["area"] in prioritarias
        and v["nivel"] in ("practicas", "junior")
        and any("ZONA GRIS" in m for m in v["motivos"])
    ]
    for v in zona_gris:
        v["veredicto"] = "zona-gris"
        v["zona_gris"] = True

    relevantes = relevantes + zona_gris
    relevantes.sort(key=lambda v: -v["score"])
    log(
        f" {len(analizadas)} -> {len(relevantes)} relevantes "
        f"(score>={UMBRAL_MINIMO} y elegible, mas {len(zona_gris)} de zona gris)"
    )

    # --- 5. Verificación ----------------------------------------------------
    log("\n[5/5] VERIFICACION")
    if rapido:
        log(" modo rapido: se omite la capa HTTP")
        for v in relevantes:
            v.setdefault(
                "verificacion",
                {"estado": "sin-verificar", "metodo": "omitido", "detalle": "modo rapido"},
            )
    else:
        verificador.verificar_lote(relevantes)
        # Capa 3: resultados obtenidos con Chrome real para los sitios que
        # bloquean el HTTP anónimo (OCC responde 403 a la ficha de vacante).
        n_chrome = verificador_chrome.aplicar(relevantes)
        if n_chrome:
            log(f"  capa 3 (Chrome): {n_chrome} verificaciones aplicadas")

    conteo_verif = verificador.resumen(relevantes)
    for estado, n in sorted(conteo_verif.items(), key=lambda x: -x[1]):
        log(f"  {estado:15} {n:5}")

    # Las cerradas se archivan aparte: no se borran, para poder auditar.
    vivas = [v for v in relevantes if v["verificacion"]["estado"] != "cerrada"]
    cerradas = [v for v in relevantes if v["verificacion"]["estado"] == "cerrada"]

    # --- Guardado -----------------------------------------------------------
    guardar_json("vacantes.json", vivas)
    guardar_json("vacantes_cerradas.json", cerradas)

    # El volcado de auditoría guarda por qué se descartó cada vacante, pero SIN
    # las descripciones: con ellas el archivo pesaba 60 MB y tardaba más en
    # escribirse que todo el análisis. Para auditar una decisión basta el
    # veredicto y sus motivos.
    auditoria = [
        {
            k: v[k]
            for k in ("id", "titulo", "empresa", "ubicacion", "url", "fuente",
                      "nivel", "area", "modalidad", "elegible_mx", "score",
                      "veredicto", "motivos")
            if k in v
        }
        for v in analizadas
    ]
    guardar_json("auditoria_decisiones.json", auditoria)

    estadisticas = {
        "generado": __import__("nucleo").ahora_iso(),
        "crudas": len(crudas),
        "unicas": len(unicas),
        "relevantes": len(relevantes),
        "vivas": len(vivas),
        "cerradas": len(cerradas),
        "por_veredicto": dict(por_veredicto),
        "por_verificacion": conteo_verif,
        "por_area": dict(Counter(v["area"] for v in vivas)),
        "por_nivel": dict(Counter(v["nivel"] for v in vivas)),
        "por_modalidad": dict(Counter(v["modalidad"] for v in vivas)),
        "por_fuente": dict(Counter(v["fuente"].split(":")[0] for v in vivas)),
        "bolsas_ats_vivas": {
            k: len(v) for k, v in informe_ats["validos"].items()
        },
        "informe_boards": informe_boards,
        "informe_mexico": informe_mx,
    }
    guardar_json("estadisticas.json", estadisticas)

    log("\n" + "=" * 62)
    log(f"RESULTADO: {len(vivas)} vacantes vivas y relevantes")
    log("=" * 62)
    log("\nTOP 20:")
    for v in vivas[:20]:
        marca = {"viva": "OK ", "sin-verificar": "?  ", "inaccesible": "!  "}.get(
            v["verificacion"]["estado"], "   "
        )
        log(
            f" {marca}{v['score']:5.1f} | {v['titulo'][:44]:44} | "
            f"{v['empresa'][:22]:22} | {v['modalidad'][:10]:10} | {v['ubicacion'][:26]}"
        )
    return estadisticas


if __name__ == "__main__":
    ejecutar(rapido="--rapido" in sys.argv)
