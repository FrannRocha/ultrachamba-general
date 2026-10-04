"""
Análisis en paralelo sobre varios núcleos.

Por qué. Medido en una corrida real: de los 23 minutos que tardó la
excavadora, 13 se fueron en clasificar 15.927 vacantes. La descarga ya no era
el cuello de botella; lo era esta fase, que es puro cálculo de expresiones
regulares y no toca la red.

El clasificador no comparte estado entre vacantes: cada una se analiza sola.
Eso lo hace repartible entre procesos sin ninguna coordinación.

Se usan procesos y no hilos porque el trabajo es de CPU: con hilos, el
bloqueo global del intérprete de Python los serializaría y no se ganaría nada.
"""
from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor

from analisis import analizar
from nucleo import log

# Por debajo de este número no compensa: crear procesos y mover los datos entre
# ellos cuesta más que analizar las vacantes de una vez.
MINIMO_PARA_PARALELIZAR = 2000


def _lote(vacantes: list[dict]) -> list[dict]:
    """Se ejecuta dentro de cada proceso trabajador."""
    return [analizar(v) for v in vacantes]


def analizar_lote(vacantes: list[dict], procesos: int | None = None) -> list[dict]:
    """Igual que analisis.analizar_lote, pero repartido entre núcleos."""
    if len(vacantes) < MINIMO_PARA_PARALELIZAR:
        return [analizar(v) for v in vacantes]

    n = procesos or max(1, (os.cpu_count() or 4) - 1)
    if n <= 1:
        return [analizar(v) for v in vacantes]

    # Trozos grandes: menos viajes de ida y vuelta entre procesos.
    tamano = max(200, len(vacantes) // (n * 4))
    trozos = [vacantes[i:i + tamano] for i in range(0, len(vacantes), tamano)]
    log(f"  analizando {len(vacantes)} en {n} procesos ({len(trozos)} trozos)")

    salida: list[dict] = []
    try:
        with ProcessPoolExecutor(max_workers=n) as ex:
            for res in ex.map(_lote, trozos):
                salida.extend(res)
    except Exception as e:
        # Si el paralelismo falla por cualquier motivo del sistema, el trabajo
        # se hace igual en un solo proceso. Nunca se queda sin analizar.
        log(f"  paralelo no disponible ({type(e).__name__}), se analiza en serie")
        return [analizar(v) for v in vacantes]
    return salida


if __name__ == "__main__":
    import time

    from nucleo import cargar_json

    datos = cargar_json("vacantes.json", []) or []
    if not datos:
        print("No hay datos para medir.")
    else:
        muestra = (datos * 6)[:6000]
        t = time.time()
        [analizar(dict(v)) for v in muestra]
        serie = time.time() - t
        t = time.time()
        analizar_lote([dict(v) for v in muestra])
        paralelo = time.time() - t
        print(f"  serie:    {serie:6.1f}s")
        print(f"  paralelo: {paralelo:6.1f}s   ({serie / max(paralelo, 0.01):.1f}x mas rapido)")
