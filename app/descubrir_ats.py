"""
Descubre la bolsa de trabajo PROPIA de cada empresa objetivo.

Por que importa mas que otra bolsa mas. Los portales publicos ya se agotaron
para un perfil concreto: tras aplicar sus restricciones reales pueden quedar
unas decenas de vacantes. Pero la mayoria de las empresas grandes publican primero en su propio
sitio, dias antes de que el anuncio llegue a OCC --si es que llega--. Ahi ve la
vacante antes que nadie y con datos limpios: nada de "Nuevo Leon, Mexico" por
defecto, porque la API devuelve la ubicacion tal como la escribio la empresa.

Como funciona. Las plataformas de reclutamiento identifican a cada empresa con
un token corto en la URL de su API. `fuentes_ats.py` ya sabe LEER esas APIs;
lo que faltaba era averiguar el token. Aqui se prueban candidatos derivados del
nombre y se guarda el que responde.

Se limita a lo verificable: si la API contesta 200 con una lista de vacantes,
el token es ese. No se adivina ni se deja "probable".

Uso:
    python descubrir_ats.py --limite 40
"""
from __future__ import annotations

import argparse
import re
import unicodedata

from almacen import conexion
from nucleo import log, obtener_json, ahora_iso

# Plataformas con API publica y sin autenticacion. Workday, iCIMS y
# SuccessFactors quedan fuera: su URL depende de un subdominio propio de cada
# cliente que no se puede derivar del nombre, asi que probar seria disparar al
# aire.
PLATAFORMAS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{t}/jobs",
    "lever": "https://api.lever.co/v0/postings/{t}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{t}",
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{t}/postings",
}

# Palabras que sobran en la razon social y que ninguna empresa mete en su token.
_RUIDO = re.compile(
    r"\b(s\.?a\.?p?\.?i?\.?|de|c\.?v\.?|s\.?\s*de\s*r\.?l\.?|sa|sapi|slp|inc|"
    r"llc|ltd|corp|corporation|company|mexico|méxico|group|grupo|the)\b",
    re.I)


def _slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = _RUIDO.sub(" ", t)
    return re.sub(r"[^a-z0-9]+", "", t)


def candidatos(nombre: str) -> list[str]:
    """Los tokens plausibles para una empresa, del mas probable al menos.

    Se prueban pocos a proposito: cada intento es una peticion a un tercero y
    la lista completa de empresas son cientos. Mejor tres buenos que diez malos.
    """
    limpio = _slug(nombre)
    palabras = [p for p in re.split(r"[^a-zA-Z0-9]+", nombre or "") if p]
    primera = _slug(palabras[0]) if palabras else ""
    vistos, salida = set(), []
    for c in (limpio, primera, limpio[:20]):
        if c and len(c) >= 3 and c not in vistos:
            vistos.add(c)
            salida.append(c)
    return salida


def _cuantas(plataforma: str, datos) -> int:
    """Cuantas vacantes trae la respuesta. Cero = el token no es de nadie."""
    if not isinstance(datos, dict):
        return len(datos) if isinstance(datos, list) else 0
    for clave in ("jobs", "content", "results"):
        if isinstance(datos.get(clave), list):
            return len(datos[clave])
    return 0


# Tokens que responden 200 pero pertenecen a cualquiera. Nacen de un fallo
# real: la primera version dio por buenos `greenhouse/international` para
# "INTERNATIONAL MOTORS MEXICO" --resulto ser "UpWork International", con el
# contenido literal "TEST--"-- y `lever/capital` para "Capital Empresarial
# Horizonte", que son vacantes en Limassol, Chipre.
#
# Dos falsos de tres. Sin este filtro el sistema habria empezado a ofrecer
# vacantes de empresas que no son, con la ubicacion de otro pais.
GENERICOS = {
    "capital", "international", "global", "grupo", "servicios", "consulting",
    "solutions", "systems", "technologies", "tech", "digital", "data",
    "security", "cloud", "software", "talento", "recursos", "empresa",
    "corporativo", "industrias", "mexicana", "nacional", "central", "premier",
}


def _parece_suya(plataforma: str, token: str, datos, nombre_empresa: str) -> bool:
    """¿La bolsa es de ESTA empresa, o solo comparte una palabra comun?

    Cada plataforma da una pista distinta:
      - Greenhouse publica el nombre del tablero: se compara con el de la
        empresa y tiene que compartir una palabra de verdad.
      - Lever y Ashby no dicen de quien son. Ahi se exige otra cosa: que al
        menos una vacante este en Mexico. Una bolsa sin presencia en Mexico no
        sirve aunque el token fuera correcto, asi que el filtro
        no pierde nada util.
    """
    esperado = set(_slug(p) for p in re.split(r"[^\w]+", nombre_empresa or "")
                   if len(p) > 3) - GENERICOS

    if plataforma == "greenhouse":
        tablero = obtener_json(
            f"https://boards-api.greenhouse.io/v1/boards/{token}", timeout=12,
            cache_horas=72) or {}
        suyo = set(_slug(p) for p in re.split(r"[^\w]+", tablero.get("name") or "")
                   if len(p) > 3) - GENERICOS
        return bool(esperado & suyo)

    texto = str(datos)[:200000].lower()
    return any(p in texto for p in ("mexico", "méxico", "monterrey", "cdmx"))


def probar(token: str, nombre_empresa: str = "") -> tuple[str, int] | None:
    """Prueba un token contra las plataformas y COMPRUEBA que sea suyo."""
    if token in GENERICOS or len(token) < 5:
        return None
    for nombre, plantilla in PLATAFORMAS.items():
        datos = obtener_json(plantilla.format(t=token), timeout=12, cache_horas=72)
        n = _cuantas(nombre, datos)
        if n and _parece_suya(nombre, token, datos, nombre_empresa):
            return nombre, n
    return None


def descubrir(limite: int = 30, solo_zona: bool = True) -> dict:
    """Busca el token de las empresas objetivo que aun no lo tienen.

    Con `solo_zona`, solo las que operan en la zona base. La columna se llama
    `en_monterrey` por el sistema de origen y guarda "opera en la zona base";
    en la zona `nacional` no hay zona que filtrar y se prueban todas.
    """
    import areas
    filtrar = solo_zona and bool(areas.zona()["sql_like"])
    with conexion() as con:
        filas = con.execute(f"""
            SELECT id, nombre, nombre_limpio, score FROM empresas
            WHERE ats_token IS NULL AND ats_probado IS NULL
              {'AND en_monterrey = 1' if filtrar else ''}
            ORDER BY score DESC
            LIMIT ?""", (limite,)).fetchall()

    hallados, probadas = [], 0
    for f in filas:
        probadas += 1
        encontrado = None
        nombre = f["nombre_limpio"] or f["nombre"]
        for token in candidatos(nombre):
            r = probar(token, nombre)
            if r:
                encontrado = (token, *r)
                break

        with conexion() as con:
            if encontrado:
                token, plataforma, n = encontrado
                con.execute(
                    "UPDATE empresas SET ats=?, ats_token=?, ats_probado=? WHERE id=?",
                    (plataforma, token, ahora_iso(), f["id"]))
                hallados.append({"empresa": f["nombre_limpio"], "plataforma": plataforma,
                                 "token": token, "vacantes": n})
            else:
                # Se marca aunque no se encuentre: si no, la misma empresa se
                # vuelve a probar cada dia y se gastan peticiones para nada.
                con.execute("UPDATE empresas SET ats_probado=? WHERE id=?",
                            (ahora_iso(), f["id"]))

    for h in hallados:
        log(f"    {h['empresa']}: {h['plataforma']}/{h['token']} ({h['vacantes']} vacantes)")
    log(f"  ats: {probadas} empresas probadas, {len(hallados)} bolsas encontradas")
    return {"probadas": probadas, "hallados": hallados}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limite", type=int, default=30)
    ap.add_argument("--todas", action="store_true",
                    help="no limitarse a las de tu zona base")
    a = ap.parse_args()
    descubrir(a.limite, solo_zona=not a.todas)
