"""
Aplica al conjunto de datos las fichas de OCC extraídas con Chrome.

Qué aporta cada ficha frente a la tarjeta del listado:

  - **Modalidad real.** La tarjeta no la trae; la ficha sí. Medido sobre 157
    fichas: 91 presencial, 54 híbrido, 11 desde casa. Es decir, el 42% de lo
    que el panel mostraba como presencial no lo era.
  - **Descripción completa.** La tarjeta solo daba un recorte, y sin texto el
    clasificador no puede ver ni las habilidades ni los años exigidos.
  - **Escolaridad mínima y tipo de contrato.**
  - **Verificación real**: 200 = viva, 404 = cerrada.

Las respuestas 429 (demasiadas peticiones) NO se tratan como fallo definitivo:
quedan pendientes para reintentar más tarde, que es de lo que se encarga
[[sistema/trabajos-por-tandas]].
"""
from __future__ import annotations

import json
from collections import Counter

import analisis
import tandas
from nucleo import ahora_iso, cargar_json, guardar_json, log

TRABAJO = "occ_detalle"

# El campo de OCC se traduce a la modalidad que usa el resto del sistema.
MODALIDADES = {
    "presencial": "presencial",
    "hibrido": "hibrido",
    "híbrido": "hibrido",
    "desde casa": "remoto",
    "remoto": "remoto",
}


def cargar_detalle() -> dict:
    ruta = cargar_json("occ_detalle.json", {}) or {}
    return {k: v for k, v in ruta.items() if isinstance(v, dict) and "http" in v}


def sincronizar_tandas(detalle: dict) -> dict:
    """Vuelca lo obtenido al registro de tandas para poder reanudar."""
    ids = cargar_json("ids_occ.json", []) or []
    tandas.encolar(TRABAJO, ids)
    # Un 429 significa "vuelve luego", no "esto falló": se deja pendiente.
    hechas = {k: v for k, v in detalle.items() if v.get("http") in (200, 404, 410)}
    tandas.completar(TRABAJO, hechas)
    reintentar = [k for k, v in detalle.items() if v.get("http") == 429]
    return {"aplicadas": len(hechas), "para_reintentar": len(reintentar)}


def aplicar(vacantes: list[dict], detalle: dict) -> dict:
    cambios = Counter()
    for v in vacantes:
        if v.get("fuente", "").split(":")[0] != "occ":
            continue
        d = detalle.get(v.get("extra", {}).get("id_occ", ""))
        if not d:
            continue

        if d.get("http") == 404:
            v["verificacion"] = {
                "estado": "cerrada", "metodo": "chrome-ficha-occ", "http": 404,
                "fecha": ahora_iso(), "detalle": "la ficha ya no existe",
            }
            cambios["cerradas"] += 1
            continue
        if d.get("http") != 200:
            continue

        nueva_mod = MODALIDADES.get((d.get("modalidad") or "").strip().lower())
        if nueva_mod and nueva_mod != v.get("modalidad"):
            v["modalidad_tarjeta"] = v.get("modalidad")
            v["modalidad"] = nueva_mod
            cambios[f"modalidad->{nueva_mod}"] += 1

        if len(d.get("descripcion") or "") > len(v.get("descripcion") or ""):
            v["descripcion"] = d["descripcion"]
            cambios["descripcion_completa"] += 1

        if d.get("educacion"):
            v.setdefault("extra", {})["educacion_minima"] = d["educacion"]
        if d.get("contratacion"):
            v.setdefault("extra", {})["contratacion"] = d["contratacion"]

        v["verificacion"] = {
            "estado": "viva", "metodo": "chrome-ficha-occ", "http": 200,
            "fecha": ahora_iso(),
            "detalle": "ficha leida desde una pestana real; los ids inexistentes dan 404",
        }
        cambios["verificadas_vivas"] += 1
    return dict(cambios)


def main() -> int:
    detalle = cargar_detalle()
    if not detalle:
        log("No hay datos/occ_detalle.json — extrae primero las fichas con Chrome")
        return 1
    log(f"fichas disponibles: {len(detalle)}")
    log(f"tandas: {sincronizar_tandas(detalle)}")

    vacantes = cargar_json("vacantes.json", []) or []

    # ORDEN IMPORTANTE. Primero se vuelca la descripción completa y se
    # re-analiza; solo DESPUÉS se impone la modalidad de la ficha.
    # Al revés, el clasificador deduce la modalidad del texto y pisa el dato
    # bueno: en una prueba, de 54 híbridas aplicadas solo sobrevivieron 6.
    # La ficha trae un campo estructurado de la propia fuente; deducirlo del
    # texto es peor información y no debe ganar.
    for v in vacantes:
        d = detalle.get(v.get("extra", {}).get("id_occ", ""))
        if d and d.get("http") == 200 and len(d.get("descripcion") or "") > len(v.get("descripcion") or ""):
            v["descripcion"] = d["descripcion"]

    log("re-analizando con las descripciones completas...")
    vacantes = analisis.analizar_lote(vacantes)

    cambios = aplicar(vacantes, detalle)
    log(f"cambios aplicados: {json.dumps(cambios, ensure_ascii=False)}")
    vivas = [v for v in vacantes
             if v["verificacion"].get("estado") != "cerrada"
             and v["area"] != "fuera" and v["score"] >= 40
             and (v["elegible_mx"] or v.get("veredicto") == "zona-gris")]
    vivas.sort(key=lambda v: -v["score"])
    guardar_json("vacantes.json", vivas)

    est = cargar_json("estadisticas.json", {}) or {}
    est.update({"vivas": len(vivas), "generado": ahora_iso(),
                "occ_fichas_aplicadas": len(detalle)})
    guardar_json("estadisticas.json", est)

    log(f"panel: {len(vivas)} vacantes")
    log(f"  modalidad: {dict(Counter(v['modalidad'] for v in vivas))}")
    log(f"  verificacion: {dict(Counter(v['verificacion']['estado'] for v in vivas))}")
    log(f"  progreso OCC: {tandas.progreso(TRABAJO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
