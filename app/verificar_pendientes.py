"""
Verifica lo que quedó sin confirmar tras la recolección.

Cada fuente necesita su propio método:

  - **LinkedIn**: su ficha pública de invitado responde sin sesión. Si trae
    "no longer accepting applications", la vacante está cerrada.
  - **OCC**: responde 403 al HTTP directo y 429 si se le piden muchas seguidas
    desde el navegador. Va aparte, por tandas, con [[sistema/trabajos-por-tandas]].
  - **Resto**: HTTP normal con las huellas de cierre habituales.
"""
from __future__ import annotations

import re
from collections import Counter

from nucleo import ahora_iso, cargar_json, guardar_json, log
from red import Peticion, descargar_todo

CERRADA_LI = re.compile(
    r"no longer accepting applications|ya no acepta solicitudes|"
    r"esta oferta ya no|no longer available",
    re.I,
)


def verificar_linkedin(vacantes: list[dict]) -> dict:
    pendientes = [
        v for v in vacantes
        if v["fuente"] == "linkedin"
        and v["verificacion"]["estado"] != "viva"
        and v.get("extra", {}).get("id_linkedin")
    ]
    if not pendientes:
        return {}
    log(f"  LinkedIn: {len(pendientes)} fichas por comprobar")

    peticiones = [
        Peticion(
            f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/"
            f"{v['extra']['id_linkedin']}",
            "li", {"id": v["id"]}, cache_horas=0,
        )
        for v in pendientes
    ]
    por_id = {}
    for r in descargar_todo(peticiones):
        por_id[r.peticion.meta["id"]] = r

    conteo: Counter = Counter()
    for v in pendientes:
        r = por_id.get(v["id"])
        if r is None or not r.ok:
            estado, detalle = "sin-verificar", f"la ficha respondio HTTP {r.codigo if r else 0}"
        elif CERRADA_LI.search(r.texto):
            estado, detalle = "cerrada", "la ficha dice que ya no acepta candidaturas"
        else:
            estado, detalle = "viva", "la ficha publica sigue mostrando la vacante"
        v["verificacion"] = {
            "estado": estado, "metodo": "linkedin-guest",
            "detalle": detalle, "fecha": ahora_iso(),
            "http": r.codigo if r else 0, "url_final": v["url"],
        }
        conteo[estado] += 1
    return dict(conteo)


def verificar_resto(vacantes: list[dict]) -> dict:
    """Agregadores sueltos: HTTP normal."""
    import verificador
    pendientes = [
        v for v in vacantes
        if v["verificacion"]["estado"] != "viva"
        and v["fuente"].split(":")[0] not in ("occ", "linkedin")
    ]
    if not pendientes:
        return {}
    log(f"  Resto: {len(pendientes)} por comprobar")
    conteo: Counter = Counter()
    for v in pendientes:
        v["verificacion"] = verificador.verificar_http(v)
        conteo[v["verificacion"]["estado"]] += 1
    return dict(conteo)


def main() -> int:
    vacantes = cargar_json("vacantes.json", []) or []
    antes = Counter(v["verificacion"]["estado"] for v in vacantes)
    log(f"estado inicial: {dict(antes)}")

    log("\nVERIFICANDO")
    log(f"  linkedin -> {verificar_linkedin(vacantes)}")
    log(f"  resto    -> {verificar_resto(vacantes)}")

    # Las cerradas salen del panel, pero quedan archivadas para poder auditar.
    cerradas = [v for v in vacantes if v["verificacion"]["estado"] == "cerrada"]
    vivas = [v for v in vacantes if v["verificacion"]["estado"] != "cerrada"]
    if cerradas:
        previas = cargar_json("vacantes_cerradas.json", []) or []
        guardar_json("vacantes_cerradas.json", previas + cerradas)
    guardar_json("vacantes.json", vivas)

    despues = Counter(v["verificacion"]["estado"] for v in vivas)
    log(f"\nestado final: {dict(despues)}")
    log(f"retiradas por estar cerradas: {len(cerradas)}")
    if cerradas:
        log("  ejemplos:")
        for v in sorted(cerradas, key=lambda x: -x["score"])[:8]:
            log(f"    {v['score']:5.1f} | {v['titulo'][:52]:52} | {v['empresa'][:24]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
