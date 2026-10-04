"""
Núcleo de ULTRA CHAMBA: utilidades HTTP, normalización y modelo de datos.

Toda vacante del sistema se representa con el mismo diccionario normalizado
para que el resto del pipeline (filtros, scoring, verificación, dashboard,
Obsidian) no tenga que saber de qué fuente vino.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
import html
from datetime import datetime, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

RAIZ = Path(__file__).resolve().parent
DATOS = RAIZ / "datos"
DATOS.mkdir(parents=True, exist_ok=True)
CACHE = DATOS / "cache"
CACHE.mkdir(parents=True, exist_ok=True)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_sesion: requests.Session | None = None


def sesion() -> requests.Session:
    """Sesión HTTP con reintentos y cabeceras de navegador real."""
    global _sesion
    if _sesion is None:
        s = requests.Session()
        reintentos = Retry(
            total=2,
            backoff_factor=0.6,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD", "POST"],
        )
        adaptador = HTTPAdapter(max_retries=reintentos, pool_maxsize=32)
        s.mount("https://", adaptador)
        s.mount("http://", adaptador)
        s.headers.update(
            {
                "User-Agent": UA,
                "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
                "Accept": "application/json, text/plain, text/html;q=0.9, */*;q=0.8",
            }
        )
        _sesion = s
    return _sesion


def obtener_json(url: str, timeout: int = 25, cache_horas: float = 6.0, **kw):
    """GET que devuelve JSON, con caché en disco para no re-golpear las APIs."""
    clave = hashlib.sha1((url + json.dumps(kw, sort_keys=True)).encode()).hexdigest()
    archivo = CACHE / f"{clave}.json"
    if archivo.exists() and cache_horas > 0:
        edad = (time.time() - archivo.stat().st_mtime) / 3600
        if edad < cache_horas:
            try:
                return json.loads(archivo.read_text(encoding="utf-8"))
            except Exception:
                pass
    try:
        r = sesion().get(url, timeout=timeout, **kw)
        if r.status_code != 200:
            return None
        datos = r.json()
        archivo.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        return datos
    except Exception:
        return None


def obtener_texto_cache(url: str, timeout: int = 25, cache_horas: float = 12.0) -> tuple[int, str]:
    """GET de texto con caché en disco.

    Lo usa el colector de LinkedIn: descargar ~160 fichas en cada corrida
    dispara su limitador de tasa y hace que el pipeline tarde minutos. Con
    caché, una segunda corrida el mismo día no vuelve a pedirlas.
    """
    clave = hashlib.sha1(("texto:" + url).encode()).hexdigest()
    archivo = CACHE / f"{clave}.txt"
    if archivo.exists() and cache_horas > 0:
        edad = (time.time() - archivo.stat().st_mtime) / 3600
        if edad < cache_horas:
            try:
                return 200, archivo.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                pass
    codigo, texto = obtener_texto(url, timeout=timeout)
    if codigo == 200 and texto:
        try:
            archivo.write_text(texto, encoding="utf-8")
        except Exception:
            pass
    return codigo, texto


def obtener_texto(url: str, timeout: int = 25, **kw) -> tuple[int, str]:
    """GET plano. Devuelve (status_code, texto). 0 = fallo de red."""
    try:
        r = sesion().get(url, timeout=timeout, allow_redirects=True, **kw)
        return r.status_code, r.text
    except Exception:
        return 0, ""


# ---------------------------------------------------------------- texto ----

_TAGS = re.compile(r"<[^>]+>")
_ESPACIOS = re.compile(r"\s+")


def limpiar_html(texto: str | None) -> str:
    """Quita etiquetas y decodifica entidades. El orden importa.

    Antes decodificaba una lista escrita a mano --&nbsp; &amp; &lt; &gt;-- que
    NO incluia las vocales acentuadas. En espanol eso es casi todo: `&oacute;`,
    `&aacute;`, `&iacute;`, `&ntilde;`. Resultado medido el 24-ago-2026: **555
    de 1.781 descripciones guardadas con entidades a medio decodificar**, y los
    filtros ciegos ante ellas.

    El caso concreto que lo destapo: una vacante decia "Apoyo
    econ&oacute;mico: No" y el filtro de "sin sueldo" no la veia, porque
    buscaba "economico" y en la base ponia "econ&oacute;mico". La vacante
    pasaba el filtro y llegaba a la cola como si pagara.

    `html.unescape` cubre todas las entidades con nombre y numericas, asi que
    no hay lista que mantener ni entidad nueva que se escape.
    """
    if not texto:
        return ""
    # Hasta 3 pasadas, parando en cuanto no cambie. Greenhouse entrega su
    # `content` DOBLEMENTE escapado --manda `&amp;nbsp;`, no `&nbsp;`-- y una
    # sola pasada lo deja en `&nbsp;`, que sigue sin decodificar.
    #
    # Como se supo: el 24-ago-2026 se repararon 281 filas con una pasada y la
    # comprobacion `html-sin-decodificar` bajo a 0; a la mañana siguiente
    # volvia a marcar 271, y eran LAS MISMAS filas, no nuevas. Eso descarto
    # que fuera la corrida y señalo al numero de pasadas.
    t = texto
    for _ in range(3):
        siguiente = html.unescape(t)
        if siguiente == t:
            break
        t = siguiente
    t = re.sub(r"<(br|/p|/div|/li)[^>]*>", "\n", t, flags=re.I)
    t = _TAGS.sub(" ", t)
    return _ESPACIOS.sub(" ", t).strip()


def sin_acentos(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalizar(texto: str) -> str:
    """Minúsculas sin acentos: la forma canónica para comparar palabras clave."""
    return sin_acentos((texto or "").lower())


_CACHE_REGEX: dict[str, re.Pattern] = {}


def tiene_termino(texto_n: str, termino: str) -> bool:
    """Busca `termino` en `texto_n` respetando límites de palabra.

    Existe porque la búsqueda por subcadena produce falsos positivos graves:
    'intern' aparece dentro de 'internal' y 'international', lo que hacía que
    'Internal Audit Senior Associate' se clasificara como vacante de prácticas.

    Convenciones:
      - 'intern'   -> palabra completa; NO casa con 'internal'.
      - 'ciber*'   -> prefijo; SÍ casa con 'ciberseguridad'. Necesario porque
                      el español compone palabras que el inglés separa.
      - 'jr.'      -> el límite derecho se omite si el término no acaba en
                      carácter de palabra.

    Ambos argumentos deben venir ya normalizados (minúsculas, sin acentos).
    """
    rx = _CACHE_REGEX.get(termino)
    if rx is None:
        t = termino.strip()
        prefijo = t.endswith("*")
        if prefijo:
            t = t[:-1]
        cuerpo = re.escape(t).replace(r"\ ", r"\s+")
        izq = r"\b" if t[:1].isalnum() else ""
        der = r"\b" if (t[-1:].isalnum() and not prefijo) else ""
        rx = re.compile(izq + cuerpo + der)
        _CACHE_REGEX[termino] = rx
    return bool(rx.search(texto_n))


def _patron(termino: str) -> str:
    """Traduce un término del vocabulario a su fragmento de regex."""
    t = termino.strip()
    prefijo = t.endswith("*")
    if prefijo:
        t = t[:-1]
    cuerpo = re.escape(t).replace(r"\ ", r"\s+")
    izq = r"\b" if t[:1].isalnum() else ""
    der = r"\b" if (t[-1:].isalnum() and not prefijo) else ""
    return izq + cuerpo + der


_CACHE_GRUPOS: dict[tuple, tuple[re.Pattern, tuple]] = {}


def _grupo(terminos: tuple) -> tuple[re.Pattern, tuple]:
    """Una sola regex con todos los términos como alternativas.

    Buscar 120 habilidades una por una sobre 10.000 vacantes son más de un
    millón de pasadas sobre textos largos, y eso dominaba el tiempo del
    pipeline. Con una alternación se recorre cada texto UNA vez.

    Cada alternativa es exactamente un grupo de captura (los patrones de
    `_patron` no contienen grupos propios), así que `lastindex` identifica
    sin ambigüedad qué término coincidió.
    """
    cacheado = _CACHE_GRUPOS.get(terminos)
    if cacheado is None:
        rx = re.compile("|".join(f"({_patron(t)})" for t in terminos))
        cacheado = (rx, terminos)
        _CACHE_GRUPOS[terminos] = cacheado
    return cacheado


def terminos_presentes(texto_n: str, terminos) -> list[str]:
    """Todos los términos de la lista que aparecen como palabra completa."""
    if not texto_n:
        return []
    rx, lista = _grupo(tuple(terminos))
    hallados = set()
    for m in rx.finditer(texto_n):
        if m.lastindex:
            hallados.add(lista[m.lastindex - 1])
    return [t for t in lista if t in hallados]


def id_vacante(empresa: str, titulo: str, url: str) -> str:
    base = normalizar(f"{empresa}|{titulo}|{url}")
    return hashlib.sha1(base.encode()).hexdigest()[:16]


def ahora_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def fecha_iso(valor) -> str:
    """Convierte cualquier fecha razonable a AAAA-MM-DD; '' si no se puede."""
    if not valor:
        return ""
    if isinstance(valor, (int, float)):
        try:
            v = float(valor)
            if v > 1e11:  # milisegundos
                v /= 1000
            return datetime.fromtimestamp(v, tz=timezone.utc).strftime("%Y-%m-%d")
        except Exception:
            return ""
    s = str(valor).strip()
    for patron in (
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%a, %d %b %Y %H:%M:%S %z",
        "%d/%m/%Y",
    ):
        try:
            return datetime.strptime(s, patron).strftime("%Y-%m-%d")
        except Exception:
            continue
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    return m.group(0) if m else ""


# ---------------------------------------------------------------- modelo ----

def vacante(
    titulo: str,
    empresa: str,
    url: str,
    fuente: str,
    ubicacion: str = "",
    descripcion: str = "",
    publicado: str = "",
    salario: str = "",
    ats: str = "",
    extra: dict | None = None,
) -> dict:
    """Construye una vacante normalizada. Único punto de creación del modelo."""
    titulo = _ESPACIOS.sub(" ", (titulo or "").strip())
    empresa = _ESPACIOS.sub(" ", (empresa or "").strip())
    return {
        "id": id_vacante(empresa, titulo, url),
        "titulo": titulo,
        "empresa": empresa,
        "url": (url or "").strip(),
        "fuente": fuente,
        "ats": ats,
        "ubicacion": _ESPACIOS.sub(" ", (ubicacion or "").strip()),
        "descripcion": limpiar_html(descripcion)[:6000],
        "publicado": fecha_iso(publicado),
        "salario": (salario or "").strip(),
        "recolectado": ahora_iso(),
        "extra": extra or {},
    }


def guardar_json(nombre: str, datos) -> Path:
    ruta = DATOS / nombre
    ruta.write_text(
        json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return ruta


def cargar_json(nombre: str, por_defecto=None):
    ruta = DATOS / nombre
    if not ruta.exists():
        return por_defecto
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:
        return por_defecto


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)
