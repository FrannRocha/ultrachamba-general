"""
Capa de red asíncrona: el motor de la excavadora.

Por qué existe. La versión anterior usaba hilos con 16 trabajadores y una
petición bloqueante por hilo. Barrer OCC, Computrabajo y LinkedIn a fondo son
más de 3.500 peticiones; a ese ritmo la recolección tardaba horas y el cuello
de botella no era el ancho de banda sino la espera.

Aquí las peticiones salen concurrentes de verdad sobre un solo bucle de
eventos, con tres controles que hacen falta para no romper nada:

  - Un límite global de concurrencia, para no saturar la máquina.
  - Un límite POR HOST, porque el problema real no es el total: es golpear
    demasiado rápido a un mismo sitio y que te bloquee.
  - Caché en disco con vencimiento, para que una segunda corrida el mismo día
    no vuelva a pedir lo que ya trajo.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import httpx

RAIZ = Path(__file__).resolve().parent
CACHE = RAIZ / "datos" / "cache_red"
CACHE.mkdir(parents=True, exist_ok=True)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


@dataclass
class Peticion:
    """Una descarga pendiente, con el contexto que su parser necesitará."""

    url: str
    etiqueta: str = ""            # de qué fuente viene
    meta: dict = field(default_factory=dict)  # lo que el parser quiera recordar
    json: bool = False
    cache_horas: float = 6.0
    # Workday solo responde a POST con el filtro en el cuerpo; el resto de
    # fuentes usan GET. Si `cuerpo` no es None, la petición se envía como POST.
    cuerpo: dict | None = None
    # Cabeceras propias de esta petición. Indeed exige una clave de API en la
    # cabecera y sin esto su colector no podía usarse: estaba escrito entero y
    # devolviendo lista vacía a propósito, porque no había forma de mandarla.
    cabeceras: dict | None = None


@dataclass
class Respuesta:
    peticion: Peticion
    codigo: int
    texto: str = ""
    datos: object = None          # el JSON ya decodificado, si aplica
    desde_cache: bool = False

    @property
    def ok(self) -> bool:
        return self.codigo == 200


def _archivo_cache(url: str) -> Path:
    return CACHE / f"{hashlib.sha1(url.encode()).hexdigest()}.bin"


def _leer_cache(url: str, horas: float) -> str | None:
    if horas <= 0:
        return None
    f = _archivo_cache(url)
    if not f.exists():
        return None
    if (time.time() - f.stat().st_mtime) / 3600 >= horas:
        return None
    try:
        return f.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _escribir_cache(url: str, texto: str) -> None:
    try:
        _archivo_cache(url).write_text(texto, encoding="utf-8")
    except Exception:
        pass


# Ritmo por sitio: (peticiones simultáneas, pausa mínima entre peticiones).
# No todos los sitios aguantan lo mismo y tratarlos igual es lo que provoca
# los bloqueos. LinkedIn limita la tasa en cuanto se pagina a fondo — en una
# corrida solo devolvió 237 fichas de 510 búsquedas — así que va despacio y de
# una en una. OCC aguanta bien pero se le deja margen porque es la fuente de la
# que más se pide. Los ATS son APIs pensadas para consultarse: van sueltas.
RITMO = {
    "www.linkedin.com":   (2, 0.60),
    "www.occ.com.mx":     (8, 0.10),
    "mx.computrabajo.com": (6, 0.15),
    "remoteok.com":       (3, 0.20),
    "weworkremotely.com": (3, 0.20),
    "himalayas.app":      (4, 0.15),
}
RITMO_POR_DEFECTO = (12, 0.0)


class Excavadora:
    """Descarga masiva concurrente con límites y ritmo por host."""

    def __init__(
        self,
        concurrencia_global: int = 120,
        timeout: float = 25.0,
        reintentos: int = 2,
    ) -> None:
        self.global_sem = asyncio.Semaphore(concurrencia_global)
        self.por_host: dict[str, asyncio.Semaphore] = {}
        self.ultimo: dict[str, float] = {}
        self.candados: dict[str, asyncio.Lock] = {}
        self.timeout = timeout
        self.reintentos = reintentos
        self.estadisticas = defaultdict(int)

    def _sem(self, host: str) -> asyncio.Semaphore:
        if host not in self.por_host:
            self.por_host[host] = asyncio.Semaphore(RITMO.get(host, RITMO_POR_DEFECTO)[0])
        return self.por_host[host]

    async def _esperar_turno(self, host: str) -> None:
        """Respeta la pausa mínima entre dos peticiones al mismo sitio."""
        pausa = RITMO.get(host, RITMO_POR_DEFECTO)[1]
        if pausa <= 0:
            return
        if host not in self.candados:
            self.candados[host] = asyncio.Lock()
        async with self.candados[host]:
            ahora = asyncio.get_event_loop().time()
            resta = self.ultimo.get(host, 0.0) + pausa - ahora
            if resta > 0:
                await asyncio.sleep(resta)
            self.ultimo[host] = asyncio.get_event_loop().time()

    async def _una(self, cliente: httpx.AsyncClient, p: Peticion) -> Respuesta:
        # La clave de caché incluye el cuerpo: dos POST a la misma URL con
        # distinto filtro son peticiones distintas.
        clave_cache = p.url if p.cuerpo is None else p.url + "|" + repr(sorted(p.cuerpo.items()))
        cacheado = _leer_cache(clave_cache, p.cache_horas)
        if cacheado is not None:
            self.estadisticas["cache"] += 1
            r = Respuesta(p, 200, cacheado, desde_cache=True)
            if p.json:
                r.datos = _json_seguro(cacheado)
            return r

        host = urlsplit(p.url).netloc
        async with self.global_sem, self._sem(host):
            for intento in range(self.reintentos + 1):
                try:
                    await self._esperar_turno(host)
                    if p.cuerpo is None:
                        resp = await cliente.get(
                            p.url, timeout=self.timeout,
                            headers=p.cabeceras or None)
                    else:
                        # Las claves van en minusculas ANTES de fusionar. En un
                        # dict de Python 'Content-Type' y 'content-type' son
                        # claves distintas, asi que sin esto se enviaban las dos
                        # y la API de Indeed rechazaba la peticion por CSRF.
                        cab = {"content-type": "application/json",
                               "accept": "application/json"}
                        cab.update({k.lower(): v for k, v in (p.cabeceras or {}).items()})
                        resp = await cliente.post(
                            p.url, json=p.cuerpo, timeout=self.timeout,
                            headers=cab,
                        )
                    if resp.status_code == 429 or resp.status_code >= 500:
                        # El sitio pide calma: se espera de forma creciente.
                        if intento < self.reintentos:
                            await asyncio.sleep(1.5 * (intento + 1))
                            continue
                    texto = resp.text
                    if resp.status_code == 200:
                        _escribir_cache(clave_cache, texto)
                        self.estadisticas["ok"] += 1
                    else:
                        self.estadisticas[f"http_{resp.status_code}"] += 1
                    r = Respuesta(p, resp.status_code, texto)
                    if p.json and resp.status_code == 200:
                        r.datos = _json_seguro(texto)
                    return r
                except Exception:
                    if intento < self.reintentos:
                        await asyncio.sleep(1.0 * (intento + 1))
                        continue
                    self.estadisticas["error_red"] += 1
                    return Respuesta(p, 0)
        return Respuesta(p, 0)

    async def descargar(self, peticiones: list[Peticion], progreso=None) -> list[Respuesta]:
        limites = httpx.Limits(max_connections=200, max_keepalive_connections=60)
        cabeceras = {
            "User-Agent": UA,
            "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
            "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
        }
        async with httpx.AsyncClient(
            headers=cabeceras, limits=limites, follow_redirects=True, http2=False
        ) as cliente:
            tareas = [asyncio.create_task(self._una(cliente, p)) for p in peticiones]
            salida: list[Respuesta] = []
            hechas = 0
            for fut in asyncio.as_completed(tareas):
                salida.append(await fut)
                hechas += 1
                if progreso and hechas % 200 == 0:
                    progreso(hechas, len(peticiones))
            return salida


def _json_seguro(texto: str):
    import json
    try:
        return json.loads(texto)
    except Exception:
        return None


def descargar_todo(peticiones: list[Peticion], progreso=None, **kw) -> list[Respuesta]:
    """Punto de entrada síncrono: se usa desde el resto del sistema."""
    exc = Excavadora(**kw)
    resultados = asyncio.run(exc.descargar(peticiones, progreso))
    return resultados
