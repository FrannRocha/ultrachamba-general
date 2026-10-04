"""
Configuracion del proyecto en un unico punto.

Lee las variables del entorno y, si existe, el archivo `.env` de la raiz del
proyecto (formato CLAVE=valor, una por linea, `#` para comentarios). Lo que ya
este definido en el entorno manda sobre el `.env`. No necesita ninguna
libreria: es texto plano.

Ningun otro modulo lee `os.environ` para estas claves; todos llaman a las
funciones de aqui. Se leen EN CADA LLAMADA y no al importar, para que una
prueba pueda fijar un valor sin reiniciar el interprete.

La explicacion de cada variable esta en `.env.example`.
"""
from __future__ import annotations

import os
from pathlib import Path

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
ARCHIVO_ENV = RAIZ_PROYECTO / ".env"


def _cargar_env(ruta: Path = ARCHIVO_ENV) -> None:
    """Carga `.env` sin pisar lo que ya esta definido en el entorno."""
    try:
        lineas = ruta.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for linea in lineas:
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        clave, valor = clave.strip(), valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "'\"":
            valor = valor[1:-1]
        if clave:
            os.environ.setdefault(clave, valor)


_cargar_env()


def _texto(nombre: str, por_defecto: str = "") -> str:
    return (os.environ.get(nombre) or por_defecto).strip()


def areas_texto() -> str:
    """Areas profesionales activas: claves de `areas.AREAS` separadas por
    comas, o `todas`. Ver `areas.py`."""
    return _texto("ULTRACHAMBA_AREAS", "todas")


def zona_texto() -> str:
    """Zona base: una clave de `areas.ZONAS` (`monterrey` o `nacional`)."""
    return _texto("ULTRACHAMBA_ZONA", "monterrey")


def indeed_api_key() -> str:
    """Clave de la API movil de Indeed. Vacia = fuente Indeed desactivada."""
    return _texto("INDEED_API_KEY", "")
