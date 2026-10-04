"""
Empresas objetivo: el cambio de unidad de analisis.

El diagnostico que lo motivo. Con miles de vacantes recomendadas, las
postulaciones enviadas eran CERO. El sistema optimizaba la entrada (encontrar
anuncios) cuando el atasco estaba en la salida. Y al mirar quien publicaba en
la zona base, las dos "empresas" con mas anuncios resultaron ser "Recomendada"
(67) e "Importante empresa del sector" (49): anuncios anonimos, contra los que
no se puede escribir a nadie.

El giro. La unidad util no es la vacante, es la EMPRESA. Una empresa con
operacion real de tus areas en la zona base sigue siendo un objetivo aunque
hoy no publique nada, porque la mayoria de las practicas se dan sin anuncio de
por medio: alguien pregunta, alguien conoce a alguien. Ese es el mercado
oculto, y es donde un candidato sin experiencia tiene mas opciones que
compitiendo contra cientos de curriculums en una bolsa publica.

Dos vias, y el sistema distingue cual toca:
    vacante-publicada -> hay anuncio abierto: se postula por el canal normal
    espontanea        -> no hay anuncio: se escribe a una persona concreta

Uso:
    python empresas.py            # construye el mapa desde las vacantes
    python empresas.py --top 25   # los mejores objetivos
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter

import areas
from almacen import conexion
from nucleo import ahora_iso, normalizar, tiene_termino

# Nombres que NO son una empresa: son la forma que tiene una bolsa de ocultar
# al empleador. Se detectan para descartarlos como objetivo de contacto — no
# se puede escribir a "Importante empresa del sector".
ANONIMA = re.compile(
    r"^(recomendada|confidencial|empresa confidencial|importante empresa|"
    r"empresa del sector|importante grupo|nuestro cliente|cliente confidencial|"
    r"empresa l[ií]der|sueldo no mostrado|no mostrado|empresa reconocida|"
    r"reclutadora|consultora|bolsa de trabajo|empresa importante)",
    re.I)

# Agencias e intermediarios: existen de verdad, pero contratan PARA otros. El
# correo espontaneo ahi vale poco porque no deciden nada.
def _patron(terminos: list[str]) -> "re.Pattern":
    """Construye el regex poniendo los limites de palabra por su cuenta.

    Por que no se escriben los patrones a mano. Al hacerlo, un `\b` mal
    escapado se convirtio en un caracter de retroceso literal y los terminos
    afectados dejaron de coincidir con nada — en silencio, aparentando que todo
    iba bien porque tampoco producian falsos positivos. Escribir la lista y
    dejar que el codigo ponga los limites elimina esa clase entera de fallo.
    """
    limite = chr(92) + "b"    # el \b de las expresiones regulares
    return re.compile(
        "|".join(limite + re.escape(t) + limite for t in terminos),
        re.I)


# Agencias e intermediarios: existen, pero contratan PARA otros y no deciden.
# Los tres ultimos se confirmaron mirando sus propias vacantes: "Sociedad
# Nacional Promotora de Becarios" llego al puesto 4 del ranking con 25 vacantes
# de practicas, publicando en Tijuana, Alvaro Obregon y Col. Napoles.
INTERMEDIARIO = _patron([
    "manpower", "adecco", "randstad", "kelly services", "staffing", "headhunt",
    "reclutamiento", "outsourcing", "human capital", "talent solutions",
    "consultores en recursos", "capital humano", "talento startup",
    "promotora de becarios", "capital becarios", "rh", "recursos humanos",
    "bolsa universitaria", "vinculacion laboral", "servicios de personal",
    "administradora de personal",
])

# Empresas con programa FORMAL de becarios y convocatoria propia.
#
# Corrige una intuicion del sistema: no siempre conviene escribirle al
# responsable tecnico. Donde hay un programa con fechas y proceso, el correo en
# frio NO salta la fila y puede irritar a quien decide; ahi la via es el portal.
# El correo directo es la via principal justo donde NO hay programa, porque
# entonces no compite contra un proceso: es que no hay otro camino.
CON_PROGRAMA_FORMAL = _patron([
    "cemex", "scotiabank", "deloitte", "accenture", "kpmg", "pwc", "ey",
    "ernst", "banorte", "femsa", "bimbo", "heineken", "nestle", "procter",
    "ibm", "microsoft", "dell", "hp", "john deere", "caterpillar",
    "whirlpool", "schneider", "siemens", "bosch", "ternium",
])

# Herramientas que, si aparecen en sus anuncios, dicen que la empresa TIENE
# operacion de verdad en el area y no solo un puesto suelto. Salen de las areas
# activas (`herramientas` en `areas.py`).
def stack() -> list[str]:
    return areas.herramientas()


def _id(nombre: str) -> str:
    return hashlib.sha1(normalizar(nombre).encode("utf-8")).hexdigest()[:16]


def _limpiar(nombre: str) -> str:
    """Quita el ruido societario para poder buscar la empresa por su nombre."""
    n = (nombre or "").strip()
    n = re.sub(r"[,.]?\s*(s\.?\s?a\.?\s?p\.?\s?i\.?|s\.?\s?a\.?\s?de\s?c\.?\s?v\.?"
               r"|s\.?\s?de\s?r\.?\s?l\.?|s\.?\s?a\.?|inc\.?|corp\.?|llc|ltd\.?"
               r"|gmbh|b\.?v\.?)\s*(de\s?c\.?v\.?)?\.?$", "", n, flags=re.I)
    n = re.sub(r"\s{2,}", " ", n).strip(" .,-")
    return n or nombre


def puntuar(e: dict) -> dict:
    """Que tan buen objetivo es esta empresa para la busqueda configurada.

    Ojo con la trampa: la empresa que MAS vacantes publica no es la mejor
    objetivo. Suele ser una agencia publicando para terceros. Lo que cuenta es
    que tenga operacion propia de tus areas en la zona base y que ya haya
    demostrado que contrata gente sin experiencia.
    """
    puntos = 0.0
    motivos: list[str] = []

    if e.get("anonima"):
        return {**e, "score": 0.0, "via": "descartada",
                "motivos": ["no dice que empresa es: no hay nadie a quien escribir"]}

    # `vacantes_ciber` cuenta las vacantes de las areas PRIORITARIAS activas;
    # el nombre de la columna viene de la version de ciberseguridad.
    if e.get("vacantes_ciber", 0):
        puntos += min(30, e["vacantes_ciber"] * 10)
        motivos.append(f"publica {e['vacantes_ciber']} vacantes de tus areas: "
                       "tiene operacion propia en ellas")
    if e.get("vacantes_ia", 0):
        puntos += min(22, e["vacantes_ia"] * 7)
        motivos.append(f"publica {e['vacantes_ia']} vacantes de IA o datos")

    # La señal mas valiosa de todas: ya contrata gente sin experiencia. Una
    # empresa con programa de becarios tiene el camino abierto; una que solo
    # busca senior no va a hacer una excepcion.
    if e.get("vacantes_prac", 0):
        puntos += min(28, 12 + e["vacantes_prac"] * 4)
        motivos.append(f"YA contrata practicantes ({e['vacantes_prac']} vacantes): "
                       "la puerta existe y esta abierta")

    if e.get("en_monterrey"):
        puntos += 18
        motivos.append(f"tiene operacion en {areas.zona()['corta']}: presencial sin mudarse")

    stack = (e.get("stack") or "").split(",") if e.get("stack") else []
    stack = [s for s in stack if s]
    if stack:
        puntos += min(12, len(stack) * 2)
        motivos.append(f"sus anuncios nombran herramientas concretas ({', '.join(stack[:4])}): "
                       "el trabajo es especializado de verdad")

    if e.get("ats"):
        puntos += 5
        motivos.append(f"usa {e['ats']}: sus vacantes se pueden seguir automaticamente")

    if INTERMEDIARIO.search(e.get("nombre") or ""):
        puntos -= 25
        motivos.append("es agencia o intermediario: contrata para terceros y no decide")

    # La via correcta depende de si la empresa tiene proceso formal, no solo de
    # si hay vacante publicada.
    formal = bool(CON_PROGRAMA_FORMAL.search(e.get("nombre") or ""))
    if formal:
        via = "programa-formal"
        motivos.append("tiene programa de becarios con convocatoria: se postula por "
                       "su portal, escribir en frio no salta la fila")
    elif e.get("vacantes_total", 0):
        via = "vacante-publicada"
    else:
        via = "espontanea"
        puntos += 10
        motivos.append("sin programa ni anuncio: el correo directo es la unica via, "
                       "y ahi compites contra casi nadie")
    return {**e, "score": round(max(0.0, min(100.0, puntos)), 1),
            "motivos": motivos, "via": via}


def construir() -> dict:
    """Levanta el mapa de empresas a partir de las vacantes ya recolectadas."""
    prioritarias = set(areas.valores_prioritarios())
    herramientas = stack()
    with conexion() as con:
        filas = con.execute(f"""
            SELECT empresa, ats, area, nivel, ubicacion, descripcion, titulo,
                   CASE WHEN {areas.sql_literal_en_zona('ubicacion')} THEN 1 ELSE 0 END en_mty
            FROM vacantes
            WHERE empresa IS NOT NULL AND empresa != '' AND area != 'fuera'
        """).fetchall()

    agrupadas: dict[str, dict] = {}
    for f in filas:
        nombre = (f["empresa"] or "").strip()
        clave = _id(nombre)
        e = agrupadas.setdefault(clave, {
            "id": clave, "nombre": nombre, "nombre_limpio": _limpiar(nombre),
            "anonima": 1 if ANONIMA.match(nombre) else 0,
            "vacantes_total": 0, "vacantes_ciber": 0, "vacantes_ia": 0,
            "vacantes_prac": 0, "en_monterrey": 0, "ats": f["ats"],
            "_stack": Counter(),
        })
        e["vacantes_total"] += 1
        e["vacantes_ciber"] += f["area"] in prioritarias
        e["vacantes_ia"] += f["area"] == "ia"
        e["vacantes_prac"] += f["nivel"] == "practicas"
        e["en_monterrey"] = max(e["en_monterrey"], f["en_mty"])
        texto = normalizar((f["titulo"] or "") + " " + (f["descripcion"] or "")[:2500])
        for t in herramientas:
            if tiene_termino(texto, t):
                e["_stack"][t.rstrip("*")] += 1

    ahora = ahora_iso()
    campos = ["id", "nombre", "nombre_limpio", "anonima", "vacantes_total",
              "vacantes_ciber", "vacantes_ia", "vacantes_prac", "en_monterrey",
              "ats", "stack", "score", "motivos", "via", "notas"]
    guardadas = 0

    # Lo corregido a mano, con su evidencia: ver `datos_empresas.py`.
    from datos_empresas import AJUSTES, MANUALES

    with conexion() as con:
        for e in agrupadas.values():
            e["stack"] = ",".join(t for t, _ in e.pop("_stack").most_common(8))
            e = puntuar(e)
            nombre_n = normalizar(e.get("nombre_limpio") or e.get("nombre") or "")
            for clave, ajuste in AJUSTES.items():
                if clave in nombre_n:
                    e["score"] = round(e["score"] * ajuste["factor"], 1)
                    e["motivos"].append(ajuste["nota"])
                    e["notas"] = ajuste["nota"]
                    break
            e["motivos"] = json.dumps(e["motivos"], ensure_ascii=False)
            valores = [e.get(k) for k in campos]
            marcas = ",".join("?" * len(campos))
            act = ",".join(f"{k}=excluded.{k}" for k in campos if k != "id")
            con.execute(
                f"""INSERT INTO empresas ({",".join(campos)}, estado, primera_vez, ultima_vez)
                    VALUES ({marcas}, 'sin-contactar', ?, ?)
                    ON CONFLICT(id) DO UPDATE SET {act}, ultima_vez=excluded.ultima_vez""",
                valores + [ahora, ahora])
            guardadas += 1

        # Altas manuales: los objetivos que un mapa hecho de anuncios no puede
        # ver, porque justo no publican anuncios. Son el mercado oculto.
        for m in MANUALES:
            ident = _id(m["nombre"])
            con.execute(
                """INSERT INTO empresas (id, nombre, nombre_limpio, dominio, sitio,
                       sector, en_monterrey, score, motivos, via, notas, anonima,
                       vacantes_total, estado, primera_vez, ultima_vez)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,0,0,'sin-contactar',?,?)
                   ON CONFLICT(id) DO UPDATE SET
                       dominio=excluded.dominio, sitio=excluded.sitio,
                       sector=excluded.sector, score=excluded.score,
                       motivos=excluded.motivos, via=excluded.via,
                       notas=excluded.notas, ultima_vez=excluded.ultima_vez""",
                (ident, m["nombre"], m["nombre_limpio"], m.get("dominio"),
                 m.get("sitio"), m.get("sector"), m.get("en_monterrey", 0),
                 m["score"], json.dumps(m.get("motivos") or [], ensure_ascii=False),
                 m.get("via", "espontanea"), m.get("notas"), ahora, ahora))
            guardadas += 1

    with conexion() as con:
        anon = con.execute("SELECT COUNT(*) c FROM empresas WHERE anonima=1").fetchone()["c"]
        mty = con.execute("SELECT COUNT(*) c FROM empresas WHERE en_monterrey=1 "
                          "AND anonima=0").fetchone()["c"]
    return {"empresas": guardadas, "anonimas": anon, "objetivos_en_monterrey": mty}


def objetivos(limite: int = 30, solo_zona: bool = True) -> list[dict]:
    cond = ["anonima = 0", "score > 0"]
    # `en_monterrey` guarda "tiene operacion en la zona base" (el nombre de la
    # columna es de origen). Sin zona base no hay nada que filtrar.
    if solo_zona and areas.zona()["sql_like"]:
        cond.append("en_monterrey = 1")
    with conexion() as con:
        filas = con.execute(
            f"SELECT * FROM empresas WHERE {' AND '.join(cond)} "
            "ORDER BY score DESC LIMIT ?", (limite,)).fetchall()
    salida = []
    for f in filas:
        e = dict(f)
        try:
            e["motivos"] = json.loads(e.get("motivos") or "[]")
        except (TypeError, ValueError):
            e["motivos"] = []
        salida.append(e)
    return salida


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--top", type=int, default=25)
    p.add_argument("--todas", action="store_true", help="no limitar a la zona base")
    args = p.parse_args()

    print("construyendo el mapa de empresas...")
    print(construir())
    print()
    lista = objetivos(args.top, solo_zona=not args.todas)
    print(f"MEJORES {len(lista)} OBJETIVOS"
          f"{' EN ' + areas.zona()['corta'].upper() if not args.todas else ''}:\n")
    for e in lista:
        # Tres vias, no dos. Confundir "programa-formal" con "espontanea" daria
        # justo el consejo contrario al bueno: escribirle en frio al
        # responsable tecnico de una empresa que tiene convocatoria con fechas
        # no salta la fila, y puede irritar a quien decide.
        via = {"vacante-publicada": "postular",
               "programa-formal": "portal de becarios",
               "espontanea": "ESCRIBIR EN FRIO"}.get(e["via"], e["via"])
        print(f"  {e['score']:5.1f} | {via:16} | {e['nombre_limpio'][:34]:34} "
              f"| area {e['vacantes_ciber']:2} ia {e['vacantes_ia']:2} "
              f"prac {e['vacantes_prac']:2}")
