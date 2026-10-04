"""Carga los contactos investigados y los enlaza con la tabla de empresas."""
from __future__ import annotations

import hashlib

from almacen import conexion
from datos_contactos import CONTACTOS, PUERTAS
from nucleo import ahora_iso, normalizar


def _buscar_empresa(nombre: str) -> str | None:
    """Enlaza por nombre normalizado. Si no encuentra, devuelve None y se
    reporta: es preferible una fila sin enlazar que una union inventada."""
    n = normalizar(nombre)
    with conexion() as con:
        fila = con.execute(
            "SELECT id FROM empresas WHERE LOWER(nombre)=? OR LOWER(nombre_limpio)=? "
            "ORDER BY score DESC LIMIT 1", (n, n)).fetchone()
        if fila:
            return fila["id"]
        fila = con.execute(
            "SELECT id FROM empresas WHERE LOWER(nombre) LIKE ? "
            "ORDER BY score DESC LIMIT 1", (f"%{n}%",)).fetchone()
    return fila["id"] if fila else None


def cargar() -> dict:
    ahora = ahora_iso()
    enlazados, sueltos = 0, []
    with conexion() as con:
        for c in CONTACTOS + PUERTAS:
            eid = _buscar_empresa(c["empresa"])
            if not eid:
                sueltos.append(f"{c['nombre']} ({c['empresa']})")
            ident = hashlib.sha1(
                normalizar(c["empresa"] + "|" + c["nombre"]).encode("utf-8")
            ).hexdigest()[:16]
            con.execute("""
                INSERT INTO contactos (id, empresa_id, nombre, puesto, correo,
                                       correo_origen, confianza, fuente, notas, primera_vez)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    empresa_id=excluded.empresa_id, puesto=excluded.puesto,
                    correo=excluded.correo, correo_origen=excluded.correo_origen,
                    confianza=excluded.confianza, fuente=excluded.fuente,
                    notas=excluded.notas""",
                (ident, eid, c["nombre"], c["puesto"], c.get("correo") or None,
                 c.get("correo_origen") or None, c["confianza"], c["fuente"],
                 c.get("notas"), ahora))
            enlazados += bool(eid)
    return {"cargados": len(CONTACTOS) + len(PUERTAS),
            "enlazados_con_empresa": enlazados, "sin_enlazar": sueltos}


if __name__ == "__main__":
    print(cargar())
    with conexion() as con:
        print("\nCONTACTOS EN LA BASE:\n")
        for r in con.execute("""
            SELECT c.nombre, c.puesto, c.correo, c.confianza, e.nombre_limpio
            FROM contactos c LEFT JOIN empresas e ON e.id = c.empresa_id
            ORDER BY CASE c.confianza WHEN 'verificado' THEN 0
                     WHEN 'probable-caduco' THEN 2 ELSE 1 END"""):
            correo = r["correo"] or "(sin correo)"
            print(f"  [{r['confianza']:16}] {(r['nombre'] or '')[:26]:26} "
                  f"| {(r['puesto'] or '')[:38]:38}")
            print(f"   {'':18}  {correo:42} | {r['nombre_limpio'] or 'SIN ENLAZAR'}")
