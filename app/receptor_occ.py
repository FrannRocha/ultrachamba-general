"""
Receptor local para el enriquecimiento de OCC desde Chrome.

Por qué existe. OCC responde 403 a cualquier petición HTTP directa a la ficha
de una vacante, así que la única forma de leerla es desde una pestaña real del
navegador. Pero el volumen (104 fichas con su descripción completa) no cabe en
el canal de respuesta de la herramienta de automatización.

La solución: este servidor escucha en localhost, la pestaña de OCC hace fetch
del mismo origen para leer cada ficha y luego un POST aquí con el resultado.
Chrome trata 127.0.0.1 como origen seguro, así que una página HTTPS puede
enviarle datos sin que se bloquee por contenido mixto.

Uso:
    python receptor_occ.py          # levanta el receptor en el puerto 8899
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

DESTINO = Path(__file__).resolve().parent / "datos" / "occ_detalle.json"
PUERTO = 8899


class Receptor(BaseHTTPRequestHandler):
    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        # Sin esta cabecera Chrome bloquea la petición y se queda colgada:
        # su política de acceso a red privada (Private Network Access) impide
        # que una página pública hable con 127.0.0.1 salvo que el servidor
        # local lo autorice de forma explícita en el preflight.
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):  # noqa: N802
        """Sirve la lista de ids a verificar.

        Así la página no necesita llevar 565 identificadores incrustados en el
        código: los pide aquí y trabaja sobre lo que reciba.
        """
        ruta = DESTINO.parent / "ids_occ.json"
        cuerpo = ruta.read_bytes() if ruta.exists() else b"[]"
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_POST(self):  # noqa: N802
        largo = int(self.headers.get("Content-Length", 0))
        crudo = self.rfile.read(largo).decode("utf-8", errors="replace")
        try:
            lote = json.loads(crudo)
        except Exception as e:
            self.send_response(400)
            self._cors()
            self.end_headers()
            self.wfile.write(str(e).encode())
            return

        acumulado = {}
        if DESTINO.exists():
            try:
                acumulado = json.loads(DESTINO.read_text(encoding="utf-8"))
            except Exception:
                acumulado = {}
        acumulado.update(lote)
        DESTINO.parent.mkdir(parents=True, exist_ok=True)
        DESTINO.write_text(
            json.dumps(acumulado, ensure_ascii=False, indent=1), encoding="utf-8"
        )

        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            json.dumps({"recibidas": len(lote), "total": len(acumulado)}).encode()
        )
        print(f"recibidas {len(lote)}, acumuladas {len(acumulado)}", flush=True)

    def log_message(self, *a):  # silencia el log por petición
        pass


if __name__ == "__main__":
    print(f"Receptor escuchando en http://127.0.0.1:{PUERTO}  ->  {DESTINO}", flush=True)
    HTTPServer(("127.0.0.1", PUERTO), Receptor).serve_forever()
