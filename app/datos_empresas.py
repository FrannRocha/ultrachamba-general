"""
Correcciones y altas manuales al mapa de empresas, con su evidencia.

Por que existe este archivo. El mapa de `empresas.py` se construye desde las
vacantes recolectadas, y eso tiene dos puntos ciegos:

  1. **El volumen de anuncios miente sobre la presencia local.** Una empresa
     puede publicar muchas vacantes etiquetadas en la zona base y tener su
     operacion real en otro estado, o ser 100% remota y sin oficina a la que
     llegar. Un `AJUSTE` corrige su puntuacion con la nota que lo justifica.
  2. **Las mejores puertas no publican vacantes.** Una empresa sin anuncios en
     las fuentes no aparece en el mapa, justo las del mercado oculto. Un alta
     `MANUAL` la anade.

Todo lo que se escriba aqui tiene que salir de una fuente comprobable y citarla
en `notas`. Solo informacion corporativa: nada de datos personales de nadie.

LOS VALORES DE ABAJO SON EJEMPLOS FICTICIOS, e inertes a proposito: puntuacion
0 (no aparecen como objetivo ni en el panel ni en la cola diaria), dominio
reservado `example.com` (RFC 2606) y nombres que no casan con ninguna empresa
real. Sustituyelos por los tuyos o dejalos: no afectan a nada.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Altas manuales: objetivos que no publican vacantes en las fuentes y por eso
# el mapa no los ve. `score` es manual porque no hay anuncios que contar; se
# anota el porque en `notas`.
# ---------------------------------------------------------------------------
MANUALES = [
    {
        "nombre": "EJEMPLO — Empresa Ficticia S.A.",
        "nombre_limpio": "EJEMPLO — Empresa Ficticia",
        "dominio": "example.com", "sitio": "https://www.example.com",
        "sector": "ejemplo", "en_monterrey": 0, "score": 0,
        "via": "espontanea",
        "notas": "EJEMPLO FICTICIO. Aqui va por que es un buen objetivo y la "
                 "fuente publica que lo respalda (URL y fecha).",
        "motivos": ["EJEMPLO FICTICIO: un motivo, con su evidencia"],
    },
]

# ---------------------------------------------------------------------------
# Ajustes a empresas que el mapa SI ve, pero mal. La clave casa contra el
# nombre normalizado; `factor` multiplica el score y `nota` explica por que,
# para que el ajuste sea auditable y no un numero magico.
# ---------------------------------------------------------------------------
AJUSTES = {
    "ejemplo empresa ficticia para ajuste": {
        "factor": 1.0,
        "nota": "EJEMPLO FICTICIO: por que se corrige la puntuacion de esta "
                "empresa y con que fuente.",
    },
}
