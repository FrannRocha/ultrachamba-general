"""
Trabajos por tandas reanudables, con estado en la base de datos.

El problema que resuelve. Verificar 565 fichas de OCC en el navegador falló
tres veces seguidas: Chrome bloqueó la lectura desde la red privada, el proceso
desacoplado se estranguló al quedar la pestaña en segundo plano, y al final el
renderer se congeló por acumular peticiones. El error de fondo no fue ninguno
de esos tres: fue pedir 565 cosas de golpe y no guardar nada hasta el final,
así que cada fallo tiraba todo el trabajo.

Aquí cada elemento es una fila con estado. Se piden tandas pequeñas, se marca
lo que se completa en cuanto llega, y si algo se rompe a la mitad se reanuda
justo donde quedó. Nada se repite y nada se pierde.

Estados: pendiente -> en-curso -> hecho | fallido
"""
from __future__ import annotations

import json

from almacen import conexion
from nucleo import ahora_iso

ESQUEMA = """
CREATE TABLE IF NOT EXISTS tareas (
    trabajo   TEXT NOT NULL,      -- p.ej. 'occ_detalle'
    clave     TEXT NOT NULL,      -- el id del elemento
    estado    TEXT NOT NULL DEFAULT 'pendiente',
    intentos  INTEGER DEFAULT 0,
    resultado TEXT,
    error     TEXT,
    creada    TEXT,
    tocada    TEXT,
    PRIMARY KEY (trabajo, clave)
);
CREATE INDEX IF NOT EXISTS idx_tareas_estado ON tareas(trabajo, estado);
"""

MAX_INTENTOS = 3


def _preparar(con) -> None:
    con.executescript(ESQUEMA)


def encolar(trabajo: str, claves: list[str]) -> dict:
    """Añade elementos al trabajo. Los que ya existen NO se reinician."""
    ahora = ahora_iso()
    with conexion() as con:
        _preparar(con)
        antes = con.execute(
            "SELECT COUNT(*) n FROM tareas WHERE trabajo=?", (trabajo,)
        ).fetchone()["n"]
        con.executemany(
            "INSERT OR IGNORE INTO tareas (trabajo, clave, creada, tocada) VALUES (?,?,?,?)",
            [(trabajo, str(k), ahora, ahora) for k in claves],
        )
        despues = con.execute(
            "SELECT COUNT(*) n FROM tareas WHERE trabajo=?", (trabajo,)
        ).fetchone()["n"]
    return {"encoladas": despues - antes, "total": despues}


def siguiente_tanda(trabajo: str, tamano: int = 40) -> list[str]:
    """Reserva la próxima tanda de pendientes y las marca en curso.

    Marcarlas al entregarlas evita que dos ejecuciones simultáneas se pisen y
    hagan el mismo trabajo dos veces.
    """
    with conexion() as con:
        _preparar(con)
        filas = con.execute(
            """
            SELECT clave FROM tareas
            WHERE trabajo=? AND (estado='pendiente'
                  OR (estado='en-curso' AND intentos < ?)
                  OR (estado='fallido' AND intentos < ?))
            ORDER BY intentos ASC, clave ASC
            LIMIT ?
            """,
            (trabajo, MAX_INTENTOS, MAX_INTENTOS, tamano),
        ).fetchall()
        claves = [f["clave"] for f in filas]
        if claves:
            marcadores = ",".join("?" * len(claves))
            con.execute(
                f"""UPDATE tareas SET estado='en-curso', intentos=intentos+1, tocada=?
                    WHERE trabajo=? AND clave IN ({marcadores})""",
                [ahora_iso(), trabajo] + claves,
            )
    return claves


def completar(trabajo: str, resultados: dict[str, dict]) -> dict:
    """Marca como hechas las claves recibidas y guarda su resultado."""
    ahora = ahora_iso()
    with conexion() as con:
        _preparar(con)
        for clave, valor in resultados.items():
            estado = "hecho" if valor.get("estado") not in (None, "inaccesible") else "fallido"
            con.execute(
                """UPDATE tareas SET estado=?, resultado=?, tocada=?, error=?
                   WHERE trabajo=? AND clave=?""",
                (estado, json.dumps(valor, ensure_ascii=False), ahora,
                 valor.get("error"), trabajo, str(clave)),
            )
    return progreso(trabajo)


def progreso(trabajo: str) -> dict:
    with conexion() as con:
        _preparar(con)
        filas = con.execute(
            "SELECT estado, COUNT(*) n FROM tareas WHERE trabajo=? GROUP BY estado",
            (trabajo,),
        ).fetchall()
    conteo = {f["estado"]: f["n"] for f in filas}
    total = sum(conteo.values())
    hechas = conteo.get("hecho", 0)
    return {
        "trabajo": trabajo, "total": total, **conteo,
        "porcentaje": round(100 * hechas / total, 1) if total else 0.0,
        "terminado": total > 0 and (total - hechas - conteo.get("fallido", 0)) == 0,
    }


def resultados(trabajo: str, solo_hechas: bool = True) -> dict[str, dict]:
    cond = "AND estado='hecho'" if solo_hechas else ""
    with conexion() as con:
        _preparar(con)
        filas = con.execute(
            f"SELECT clave, resultado FROM tareas WHERE trabajo=? {cond} AND resultado IS NOT NULL",
            (trabajo,),
        ).fetchall()
    salida = {}
    for f in filas:
        try:
            salida[f["clave"]] = json.loads(f["resultado"])
        except Exception:
            pass
    return salida


def reiniciar(trabajo: str, solo_fallidas: bool = True) -> int:
    """Devuelve tareas a pendiente para volver a intentarlas."""
    cond = "AND estado IN ('fallido','en-curso')" if solo_fallidas else ""
    with conexion() as con:
        _preparar(con)
        cur = con.execute(
            f"UPDATE tareas SET estado='pendiente', intentos=0 WHERE trabajo=? {cond}",
            (trabajo,),
        )
        return cur.rowcount


if __name__ == "__main__":
    import sys
    trabajo = sys.argv[1] if len(sys.argv) > 1 else "occ_detalle"
    print(json.dumps(progreso(trabajo), ensure_ascii=False, indent=2))
