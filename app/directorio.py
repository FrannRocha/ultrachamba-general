"""
Directorio de empresas por ATS, tomado de un proyecto abierto.

De donde sale. El repositorio `kalil0321/ats-scrapers` (MIT) mantiene listas de
empresas por plataforma de contratacion. Verificado el 2026-08-15:

    greenhouse       6.031 empresas
    ashby            3.448
    smartrecruiters  2.747
    lever            2.402
    ------------------------------
    total           14.628

Por que importa. La lista que habia aqui estaba escrita a mano: 280 nombres
adivinados, de los que solo 80 respondian. Esto es 52 veces mas cobertura y no
depende de que alguien recuerde anadir empresas.

Que NO resuelve. Su dataset hospedado tiene el campo `country_iso` sin poblar
para Mexico — se comprobo que 32 vacantes con "Monterrey, NLE, MX" en el texto
de ubicacion traian `country_iso` vacio — y `is_remote` viene nulo en algunas
fuentes. Por eso aqui solo se toma el DIRECTORIO de empresas, y las vacantes se
siguen pidiendo en vivo a cada ATS: asi se sabe que estan abiertas hoy.
"""
from __future__ import annotations

import csv
import io
import time
from pathlib import Path

import requests

BASE = "https://raw.githubusercontent.com/kalil0321/ats-scrapers/main/ats-companies/"
CACHE = Path(__file__).resolve().parent / "datos" / "directorio"
CACHE.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0"}

# Solo los ATS cuyo API publico ya sabemos leer.
SOPORTADOS = ["greenhouse", "lever", "ashby", "smartrecruiters"]

CACHE_DIAS = 7


def _descargar(ats: str) -> list[dict]:
    destino = CACHE / f"{ats}.csv"
    if destino.exists() and (time.time() - destino.stat().st_mtime) < CACHE_DIAS * 86400:
        texto = destino.read_text(encoding="utf-8", errors="replace")
    else:
        r = requests.get(BASE + f"{ats}.csv", headers=UA, timeout=90)
        if r.status_code != 200:
            return []
        texto = r.text
        destino.write_text(texto, encoding="utf-8")
    return list(csv.DictReader(io.StringIO(texto)))


def tokens(ats: str, limite: int | None = None) -> list[str]:
    """Identificadores de empresa para consultar el API de ese ATS."""
    filas = _descargar(ats)
    vistos, salida = set(), []
    for f in filas:
        slug = (f.get("slug") or "").strip()
        if slug and slug not in vistos:
            vistos.add(slug)
            salida.append(slug)
            if limite and len(salida) >= limite:
                break
    return salida


def nombres(ats: str) -> dict[str, str]:
    """slug -> nombre legible, para no mostrar identificadores en el panel."""
    return {
        (f.get("slug") or "").strip(): (f.get("name") or "").strip()
        for f in _descargar(ats)
        if f.get("slug")
    }


def resumen() -> dict:
    return {a: len(tokens(a)) for a in SOPORTADOS}


if __name__ == "__main__":
    import json
    print(json.dumps(resumen(), indent=2))
