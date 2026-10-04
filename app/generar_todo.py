"""
Punto de entrada unico de los derivados: reconstruye el dashboard estatico.

    python app/generar_todo.py

Asume que ya hay vacantes en la base (`python app/dia.py` corre el ciclo
completo y llama a este modulo al final). La boveda Obsidian del sistema de
origen no forma parte de esta version: el panel en vivo
(`python app/servidor.py`) y `dashboard.html` cubren lo mismo.
"""
from __future__ import annotations

import generar_dashboard
from nucleo import cargar_json, log


def refrescar_json_desde_base() -> int:
    """Reescribe `vacantes.json` con lo que dice la base AHORA MISMO.

    Por que existe. El dashboard leia `vacantes.json`, mientras que el panel
    en vivo, el corpus y Drive leian la base. Eran dos fuentes de verdad sin
    declarar, y divergieron: el dashboard llego a mostrar 210 vacantes que la
    base ya habia descartado (guardias de seguridad, practicantes de
    rentabilidad) y a ocultar otras 447 que si valian. Un reanalisis
    actualizaba la base y no tocaba el JSON, asi que el desfase podia ser
    indefinido.

    Ahora el JSON es un derivado que se regenera justo antes de usarlo, no una
    fuente paralela. La base manda siempre.
    """
    import json
    from almacen import SQL_VIVAS_EXPORTABLES, conexion
    from nucleo import DATOS

    with conexion() as con:
        # El filtro NO se escribe aqui: es `almacen.SQL_VIVAS_EXPORTABLES`, el
        # del panel mas `elegible_mx = 1`. Tenerlo copiado era como acabaron
        # varios derivados publicando una cifra distinta de la del panel el
        # mismo dia (27-ago-2026).
        filas = con.execute(
            f"SELECT * FROM vacantes WHERE {SQL_VIVAS_EXPORTABLES} "
            "ORDER BY score DESC").fetchall()

    salida = []
    for f in filas:
        v = dict(f)
        for campo in ("motivos", "habilidades", "extra"):
            try:
                v[campo] = json.loads(v.get(campo) or ("[]" if campo != "extra" else "{}"))
            except (TypeError, ValueError):
                v[campo] = [] if campo != "extra" else {}
        v["habilidades_coincidentes"] = v.get("habilidades") or []
        v["elegible_mx"] = bool(v.get("elegible_mx"))
        v["requiere_mudanza"] = bool(v.get("requiere_mudanza"))
        v["aplicada"] = bool(v.get("aplicada"))
        v["verificacion"] = {
            "estado": v.pop("ver_estado", None), "metodo": v.pop("ver_metodo", None),
            "detalle": v.pop("ver_detalle", None), "fecha": v.pop("ver_fecha", None),
            "http": v.pop("ver_http", None),
        }
        salida.append(v)

    (DATOS / "vacantes.json").write_text(
        json.dumps(salida, ensure_ascii=False), encoding="utf-8")
    return len(salida)


def main() -> int:
    n = refrescar_json_desde_base()
    log(f"vacantes.json regenerado desde la base: {n} vacantes")
    vacantes = cargar_json("vacantes.json", [])
    if not vacantes:
        log("No hay datos. Ejecuta primero: python app/dia.py")
        return 1

    log("=" * 62)
    log("GENERANDO ENTREGABLES")
    log("=" * 62)

    log("\n[1/1] Dashboard estatico")
    generar_dashboard.generar()

    log("\n" + "=" * 62)
    log("LISTO")
    log("  Panel estatico:  dashboard.html  (doble clic)")
    log("  Panel en vivo:   python app/servidor.py")
    log("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
