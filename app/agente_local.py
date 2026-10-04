"""
El agente de casa: ejecuta lo que la persona aprueba desde donde sea.

EL PROBLEMA QUE RESUELVE. Quien busca empleo casi nunca esta frente al
ordenador. Puede dar un si desde el telefono en diez segundos, pero lo que ese
si necesita despues --mandar el correo, abrir la pestana del portal-- pasa en
SU maquina, con SU sesion. Sin algo que escuche en casa, un si desde la calle
se queda esperando a que llegue a casa, y entonces el si desde la calle no
servia de nada.

Este proceso es ese algo. Vive en la maquina de casa, mira la cola cada pocos
minutos y hace lo aprobado. No decide nada: lo que ejecuta ya lleva un si
suyo, uno por uno (ver `aprobaciones.py`).

QUE HACE EN CADA VUELTA

  1. Saca las candidaturas en estado 'aprobada' -> manda el correo (si el
     envio esta autorizado) o deja el borrador listo con su enlace.
  2. Abre en Chrome las URLs encoladas: cuando hace falta el navegador, lo
     abre el agente.
  3. Deja un latido en `datos/agente_local.json` con la hora y lo que hizo.

POR QUE EL LATIDO IMPORTA. Un agente caido no da error: simplemente deja de
hacer cosas, y las aprobaciones se acumulan sin que nadie se entere. Es el
fallo silencioso favorito de este proyecto -- el catalogo estuvo SIETE DIAS
congelado sin que nada se pusiera rojo. Con el latido, `arranque.py` puede
decir en la primera linea de la sesion: "hay 3 aprobadas y el agente lleva dos
dias sin pasar".

LO QUE NO HACE, y no es un hueco:

  - **No aprueba.** Ni una. Si la cola esta vacia, se queda quieto.
  - **No teclea contrasenas, no crea cuentas, no resuelve CAPTCHAs.** Para un
    portal, abre la pestana y para. Esa es la linea entre una herramienta y un
    bot, y no se cruza aunque seria comodo.
  - **No recolecta ni clasifica.** Eso es `dia.py` y su tarea programada.

Uso:
    python app/agente_local.py              # se queda escuchando (Ctrl+C para salir)
    python app/agente_local.py --una-vez    # una pasada y sale
    python app/agente_local.py --cada 60    # cambia el intervalo (segundos)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from nucleo import DATOS                       # noqa: E402

LATIDO = DATOS / "agente_local.json"
INTERVALO = 180          # tres minutos: rapido para un si desde el movil, y
                         # suave para una maquina que ademas se usa

# Donde suele estar Chrome en Windows. Se prueban en orden y se cae a
# `webbrowser`, que abre el navegador por defecto: peor, pero nunca falla.
CHROMES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


def abrir_en_chrome(url: str) -> str:
    """Abre la URL en Chrome. Devuelve como lo consiguio, o el error.

    Se prefiere Chrome explicitamente --y no el navegador por defecto-- porque
    la sesion del usuario (OCC, LinkedIn, Gmail) suele estar EN Chrome. Abrir la
    misma URL en otro navegador da una pantalla de inicio de sesion, que es
    justo el gesto que este sistema existe para ahorrar.
    """
    for ruta in CHROMES:
        if ruta and Path(ruta).exists():
            try:
                subprocess.Popen([ruta, url],
                                 creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
                return "chrome"
            except OSError as ex:
                return f"error al lanzar Chrome: {ex}"
    import webbrowser
    return "navegador por defecto" if webbrowser.open(url) else "no se pudo abrir"


def _latir(resumen: dict) -> None:
    """Deja constancia de que este proceso paso por aqui y que hizo."""
    try:
        LATIDO.parent.mkdir(parents=True, exist_ok=True)
        LATIDO.write_text(json.dumps(
            {"cuando": datetime.now().isoformat(timespec="seconds"),
             "pid": os.getpid(), **resumen},
            ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def una_vuelta(abrir_navegador: bool = True) -> dict:
    """Una pasada completa. Es la unidad de trabajo; el bucle solo la repite."""
    import aprobaciones

    hechas = aprobaciones.ejecutar_pendientes()
    abiertas = []
    if abrir_navegador:
        import tandas
        for url in aprobaciones.navegaciones_pendientes():
            como = abrir_en_chrome(url)
            ok = como in ("chrome", "navegador por defecto")
            abiertas.append({"url": url, "como": como})
            # Se da por hecha aunque haya caido al navegador por defecto: la
            # pestana esta abierta, que es lo que se pedia. Si fallo del todo,
            # el resultado va sin estado y `tandas` la reintenta (hasta 3).
            tandas.completar(aprobaciones.TRABAJO_NAVEGADOR, {url: {
                "estado": "abierta" if ok else None,
                "como": como,
                "error": None if ok else como}})

    resumen = {"ejecutadas": hechas, "navegador": abiertas}
    _latir({"ok": True, "ejecutadas": len(hechas), "abiertas": len(abiertas),
            "detalle": hechas[:5]})
    return resumen


def bucle(cada: int = INTERVALO) -> None:
    print(f"Agente local en marcha. Revisa cada {cada}s. Ctrl+C para salir.")
    print(f"Latido en {LATIDO}")
    while True:
        try:
            r = una_vuelta()
            if r["ejecutadas"] or r["navegador"]:
                print(f"[{datetime.now():%H:%M}] "
                      f"{len(r['ejecutadas'])} ejecutadas, "
                      f"{len(r['navegador'])} pestanas")
                for x in r["ejecutadas"]:
                    print("   ", json.dumps(x, ensure_ascii=False)[:160])
        except KeyboardInterrupt:
            raise
        except Exception as ex:
            # Una vuelta que revienta no puede matar al agente: manana habra
            # otra aprobacion esperando. Se anota y se sigue.
            print(f"[{datetime.now():%H:%M}] vuelta fallida: {type(ex).__name__}: {ex}")
            # `ok: False`, y quien lea el latido tiene que mirarlo. El `jefe`
            # senalo el 28-ago-2026 que un agente que revienta cada 180 s
            # reescribia el archivo igual, asi que se reportaba "vivo, hace 0
            # min" mientras no hacia nada: la senal medía "el proceso corrio",
            # no "el trabajo se hizo", que es justo el fallo silencioso que
            # este latido existe para evitar.
            _latir({"ok": False, "error": f"{type(ex).__name__}: {ex}"})
        time.sleep(cada)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--una-vez", action="store_true")
    ap.add_argument("--cada", type=int, default=INTERVALO)
    ap.add_argument("--sin-navegador", action="store_true",
                    help="no abre pestanas (util al probar por consola)")
    ap.add_argument("--abrir", metavar="URL",
                    help="abre esa URL en Chrome AHORA, en esta maquina")
    ap.add_argument("--pedir", metavar="URL",
                    help="encola la URL para que la abra el agente de casa")
    args = ap.parse_args()

    # Los dos atajos del caso "estoy fuera y hace falta el navegador".
    #
    # `--abrir` sirve cuando la sesion de Claude ya se ejecuta en esta maquina
    # (control remoto desde el movil): abre la pestana al instante. `--pedir`
    # sirve cuando quien lo pide esta en otro sitio: deja la URL en la cola y
    # el agente la abrira en su siguiente vuelta. La diferencia es donde corre
    # el comando, no quien lo escribe.
    if args.abrir:
        print(abrir_en_chrome(args.abrir))
        return
    if args.pedir:
        import tandas
        from aprobaciones import TRABAJO_NAVEGADOR
        print(tandas.encolar(TRABAJO_NAVEGADOR, [args.pedir]))
        return

    if args.una_vez:
        r = una_vuelta(abrir_navegador=not args.sin_navegador)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return
    try:
        bucle(args.cada)
    except KeyboardInterrupt:
        print("\nAgente detenido.")


if __name__ == "__main__":
    main()
