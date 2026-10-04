"""
Mide la TASA DE ERROR REAL de la verificacion: de las vacantes que el panel
presenta como vivas, cuantas siguen de verdad abiertas.

Por que hace falta. El sistema marca 1.671 vacantes como "vivas", pero esa
marca se puso el dia que se recolectaron. Una vacante se cierra cuando el
empleador quiere, no cuando nosotros miramos. Sin medir esto, "verificada" es
una palabra sin respaldo, y mandar a alguien a postular a una vacante
cerrada le quema tiempo y confianza.

Principio que gobierna todo el modulo: **ante la duda, NO se marca como
cerrada**. Un 403 o un 429 significan "el sitio no me deja mirar", no "la
vacante no existe". Confundirlos quitaria una oportunidad
real, que es un error mucho mas caro que dejar una vacante muerta en la lista.

Uso:
    python medir_verificacion.py            # muestra de 30
    python medir_verificacion.py --n 60
    python medir_verificacion.py --metodo api-ats
"""
from __future__ import annotations

import argparse
import asyncio
import random
import re
from collections import Counter

import httpx

from almacen import conexion

PANEL = ("score>=40 AND elegible_mx=1 AND area!='fuera' "
         "AND (nivel IS NULL OR nivel!='excluido') AND ver_estado='viva'")

# Frases que un portal muestra cuando la vacante ya no admite candidaturas.
# Se buscan solo si la respuesta fue 200: si hubo error HTTP, manda el codigo.
CERRADA = re.compile(
    r"(no longer accepting|no longer available|position (has been )?(closed|filled)|"
    r"this job (is|has been) (closed|expired|no longer)|posting (is )?closed|"
    r"vacante (cerrada|no disponible|expirada)|esta oferta ya no|"
    r"la oferta no est[aá] disponible|oferta expirada|ya no acepta)", re.I)

# Señales de que SI hay una ficha de vacante servida.
VIVA = re.compile(
    r"(apply|postul|solicitar|aplicar ahora|job description|descripci[oó]n del puesto|"
    r"responsibilities|requisitos|responsabilidades)", re.I)

CABECERAS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
}


def _muestra(n: int, metodo: str | None) -> list[dict]:
    condiciones = PANEL + (" AND ver_metodo=?" if metodo else "")
    args = (metodo,) if metodo else ()
    with conexion() as con:
        filas = con.execute(
            f"SELECT id, titulo, empresa, url, fuente, ver_metodo, ver_http "
            f"FROM vacantes WHERE {condiciones} AND url LIKE 'http%'", args).fetchall()
    filas = [dict(f) for f in filas]
    random.seed(20260817)          # muestra reproducible: se puede reauditar
    return random.sample(filas, min(n, len(filas)))


def _juzgar(estado: int | None, texto: str, url_final: str, url_pedida: str) -> tuple[str, str]:
    if estado is None:
        return "indeterminado", "no hubo respuesta (red o tiempo agotado)"
    if estado in (403, 429):
        return "indeterminado", f"el sitio bloqueo la lectura ({estado}), no dice nada de la vacante"
    if estado in (404, 410):
        return "cerrada", f"la ficha ya no existe ({estado})"
    if estado >= 500:
        return "indeterminado", f"error del servidor ({estado})"
    if estado != 200:
        return "indeterminado", f"respuesta inesperada ({estado})"

    if CERRADA.search(texto[:60000]):
        return "cerrada", "la propia pagina dice que ya no acepta candidaturas"
    # Redirigida al listado general: la ficha concreta desaparecio.
    if url_final.rstrip("/") != url_pedida.rstrip("/") and len(url_final) < len(url_pedida) - 12:
        return "cerrada", f"redirige al listado general ({url_final[:70]})"
    if VIVA.search(texto[:60000]):
        return "viva", "la ficha sigue publicada y admite candidatura"
    if len(texto) < 2000:
        return "indeterminado", f"respuesta demasiado corta para juzgar ({len(texto)} bytes)"
    return "indeterminado", "200 pero sin señales claras en ninguno de los dos sentidos"


# --------------------------------------------------------------------------
# Revalidacion por la MISMA via con la que se verifico la primera vez.
#
# Leer el HTML publico de un ATS no sirve: Greenhouse y Lever pintan la ficha
# con JavaScript, asi que el HTML inicial no trae ni "apply" ni el titulo, e
# iCIMS responde 405 a un GET directo. Medidos sobre 120 vacantes, esos dos
# casos eran el 60% de los "indeterminados" — y ninguno significaba que la
# vacante estuviera cerrada.
#
# La API del ATS si es autoritativa: devuelve 404 cuando la vacante se retira.
# --------------------------------------------------------------------------
API_ATS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{tablero}/jobs/{ident}",
    "lever": "https://api.lever.co/v0/postings/{tablero}/{ident}",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{tablero}/job/{ident}",
}


def _url_api(v: dict) -> str | None:
    fuente = (v.get("fuente") or "")
    if ":" not in fuente:
        return None
    plataforma, tablero = fuente.split(":", 1)
    plantilla = API_ATS.get(plataforma)
    if not plantilla:
        return None
    # El identificador de la vacante es el ultimo tramo de la URL publica.
    tramos = [t for t in (v.get("url") or "").split("?")[0].rstrip("/").split("/") if t]
    if not tramos:
        return None
    return plantilla.format(tablero=tablero, ident=tramos[-1])


async def _revisar_api(cliente: httpx.AsyncClient, v: dict, url: str) -> dict | None:
    try:
        r = await cliente.get(url, headers=CABECERAS, timeout=25)
    except Exception:
        return None
    if r.status_code in (404, 410):
        return {**v, "ahora": "cerrada", "http_ahora": r.status_code,
                "motivo": f"la API del ATS ya no la publica ({r.status_code})"}
    if r.status_code == 200 and len(r.text) > 200:
        return {**v, "ahora": "viva", "http_ahora": 200,
                "motivo": "la API del ATS la sigue publicando"}
    return None


async def _revisar(cliente: httpx.AsyncClient, v: dict, freno: asyncio.Semaphore) -> dict:
    async with freno:
        await asyncio.sleep(0.4)          # ritmo cortes, no ráfagas
        # Primero la API del ATS, que es la fuente autoritativa. Solo si no
        # hay API conocida se cae al HTML, que es la via menos fiable.
        if (api := _url_api(v)):
            if (r := await _revisar_api(cliente, v, api)):
                return r
        try:
            r = await cliente.get(v["url"], headers=CABECERAS,
                                  follow_redirects=True, timeout=25)
            veredicto, motivo = _juzgar(r.status_code, r.text, str(r.url), v["url"])
            http = r.status_code
        except Exception as e:
            veredicto, motivo, http = "indeterminado", f"fallo la peticion: {type(e).__name__}", None
    return {**v, "ahora": veredicto, "motivo": motivo, "http_ahora": http}


async def medir(n: int, metodo: str | None) -> list[dict]:
    muestra = _muestra(n, metodo)
    if not muestra:
        return []
    freno = asyncio.Semaphore(4)
    async with httpx.AsyncClient() as cliente:
        return await asyncio.gather(*(_revisar(cliente, v, freno) for v in muestra))


def informe(resultados: list[dict]) -> None:
    cuenta = Counter(r["ahora"] for r in resultados)
    total = len(resultados)
    print(f"\nMUESTRA DE {total} VACANTES QUE EL PANEL PRESENTA COMO VIVAS\n")
    for estado in ("viva", "cerrada", "indeterminado"):
        n = cuenta.get(estado, 0)
        print(f"  {estado:15} {n:4}  {100*n/total:5.1f}%")

    concluyentes = cuenta.get("viva", 0) + cuenta.get("cerrada", 0)
    if concluyentes:
        error = 100 * cuenta.get("cerrada", 0) / concluyentes
        print(f"\n  TASA DE ERROR sobre las {concluyentes} concluyentes: {error:.1f}%")
        print("  (los indeterminados se excluyen a proposito: un bloqueo del sitio")
        print("   no es prueba de que la vacante este cerrada)")

    print("\nPOR METODO DE VERIFICACION ORIGINAL:")
    metodos: dict[str, Counter] = {}
    for r in resultados:
        metodos.setdefault(r["ver_metodo"] or "-", Counter())[r["ahora"]] += 1
    for m, c in sorted(metodos.items(), key=lambda x: -sum(x[1].values())):
        tot = sum(c.values())
        print(f"  {m:24} n={tot:3}  viva {c['viva']:3}  cerrada {c['cerrada']:3}  "
              f"indet {c['indeterminado']:3}")

    cerradas = [r for r in resultados if r["ahora"] == "cerrada"]
    if cerradas:
        print("\nLAS QUE YA NO ESTAN (habria mandado a alguien a una puerta cerrada):")
        for r in cerradas:
            print(f"  {(r['titulo'] or '')[:46]:46} | {(r['empresa'] or '')[:20]:20} | {r['motivo']}")


def aplicar(resultados: list[dict]) -> int:
    """Marca como cerradas SOLO las que la API del ATS confirmo que ya no existen.

    Nunca se marca por un 403, un 429 ni por una lectura de HTML ambigua: solo
    vale el 404 o el 410 de la API autoritativa. El panel deja de mostrarlas,
    pero la fila se conserva para poder auditar la decision.
    """
    cerradas = [r for r in resultados
                if r["ahora"] == "cerrada" and "API del ATS" in r["motivo"]]
    if not cerradas:
        return 0
    with conexion() as con:
        con.executemany(
            "UPDATE vacantes SET ver_estado='cerrada', ver_metodo='api-ats-revalidada', "
            "ver_detalle=?, ver_http=? WHERE id=?",
            [(r["motivo"], r["http_ahora"], r["id"]) for r in cerradas])
    return len(cerradas)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--n", type=int, default=30)
    p.add_argument("--metodo", default=None, help="filtra por ver_metodo")
    p.add_argument("--aplicar", action="store_true",
                   help="marca en la base las que la API confirmo cerradas")
    args = p.parse_args()
    res = asyncio.run(medir(args.n, args.metodo))
    informe(res)
    if args.aplicar:
        print(f"\nmarcadas como cerradas en la base: {aplicar(res)}")
