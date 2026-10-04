"""
Tramites: becas, cursos y convocatorias que tienes en marcha.

POR QUE EXISTE, y por que no bastaba con `seguimiento.py`. Ese modulo sigue
CANDIDATURAS: hilos que nacieron de pedir un puesto. Pero buena parte de lo que
se tiene abierto no es una candidatura -- es un programa de formacion, un curso
con admision, una convocatoria de beca, una inscripcion a un examen. Esos
hilos vivian solo en la cabeza y en la bandeja: si nadie se acordaba de mirar,
un plazo se vencia y nadie avisaba. Ya paso: una convocatoria se perdio por
seis semanas.

Una vacante perdida vuelve la semana siguiente con otro identificador. Una
convocatoria cerrada no vuelve hasta el ano que viene. Por eso los tramites
merecen su propia tabla y su linea en el arranque de cada sesion.

QUE HACE, en tres pasos, con la misma forma que `seguimiento.py`:

  1. DESCUBRIR. Busca en Gmail los hilos que hablan de becas, cursos,
     convocatorias e inscripciones, con las consultas de `CONSULTAS`.
  2. CLASIFICAR. Le pone una clase (beca | curso | convocatoria | proceso) por
     lo que DICE el asunto o el remitente. Si nada encaja, la clase es
     'otro': no se inventa una categoria para que quede bonito.
  3. COMPARAR. Si el ultimo mensaje del hilo no salio de esta cuenta y es mas
     nuevo que la ultima novedad registrada, se marca `novedad_sin_leer`. Eso
     es lo que sale en el arranque, y solo eso: el ruido de una bandeja entera
     no cabe en un informe de veinte lineas.

LO QUE NO HACE, y son decisiones, no huecos:

  - **No toca `candidaturas`.** Si un hilo ya esta anclado a una candidatura,
    lo salta: contarlo aqui tambien lo publicaria dos veces con nombres
    distintos, que es exactamente como este proyecto se creyo tres cifras
    falsas. Una cosa, un sitio.
  - **No cierra ni descarta nada por su cuenta.** El estado 'cerrado' y
    'descartado' los pones tu. Un tramite que lleva un mes callado puede
    seguir vivo: quien lo sabe eres tu.
  - **No lee el cuerpo de los correos salvo que se le pida** (`--con-cuerpo`).
    El resumen de Gmail basta para saber que hay novedad, y pedir el cuerpo de
    cada hilo multiplica las llamadas a la API por nada.
  - **No manda nada.** Ni respuestas ni acuses.

Uso:
    python tramites.py --revisar            # mira Gmail y actualiza la tabla
    python tramites.py                      # lo que hay, sin tocar la red
    python tramites.py --leidos             # marca todas las novedades vistas
    python tramites.py --leido ID           # una sola
    python tramites.py --accion ID "texto"  # anota que toca hacer
    python tramites.py --cerrar ID          # el tramite termino
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from almacen import conexion            # noqa: E402
from nucleo import ahora_iso            # noqa: E402

ESQUEMA = """
CREATE TABLE IF NOT EXISTS tramites (
    id               TEXT PRIMARY KEY,
    titulo           TEXT NOT NULL,
    clase            TEXT,      -- beca | curso | convocatoria | proceso | otro
    organizacion     TEXT,
    hilo_gmail       TEXT,
    remitente        TEXT,
    estado           TEXT,      -- abierto | esperando-respuesta | cerrado | descartado
    ultimo_mensaje   TEXT,      -- fecha ISO del mensaje mas reciente del hilo
    ultimo_de        TEXT,      -- 'yo' | 'ellos'
    ultima_novedad   TEXT,      -- fecha del ultimo mensaje que NO salio de aqui
    resumen_novedad  TEXT,
    novedad_sin_leer INTEGER DEFAULT 0,
    requiere_accion  INTEGER DEFAULT 0,
    accion           TEXT,      -- que toca hacer, en una linea (lo escribe la persona)
    accion_fecha     TEXT,      -- para cuando (ISO). NULL = sin fecha
    revisado         TEXT,
    creado           TEXT
);
CREATE INDEX IF NOT EXISTS idx_tramites_novedad
    ON tramites(novedad_sin_leer, requiere_accion);
"""

# Las consultas con las que se pesca en Gmail. Van en sintaxis de Gmail y se
# limitan a lo reciente a proposito: un hilo de hace seis meses que nadie ha
# tocado no es un tramite en marcha, es historia.
#
# Por que estas palabras y no una lista larga: cada consulta es una llamada a
# la API. Las de aqui son genericas: becas, cursos, programas publicos de
# formacion, certificaciones y admisiones. Si tienes abierto un programa con
# nombre propio, anade una consulta con ese nombre. Anadir una palabra
# generica como "informacion" traeria la bandeja entera.
CONSULTAS = [
    'newer_than:120d (beca OR becas OR "convocatoria" OR "convocatorias")',
    'newer_than:120d (curso OR diplomado OR "inscripcion" OR "inscripción")',
    'newer_than:120d (mexia OR conahcyt OR secihti OR "innovation campus")',
    'newer_than:120d (certificacion OR "certificación" OR bootcamp '
    'OR "centro de formacion")',
    'newer_than:120d (admision OR "admisión" OR matricula OR "matrícula" OR examen)',
]

# La clase se decide por lo que dice el texto. El orden importa: la primera
# regla que casa gana, y estan de la mas especifica a la mas generica para que
# "convocatoria de beca" no acabe siendo solo 'convocatoria'.
CLASES = [
    ("beca", r"\b(beca|becas|becario|scholarship)\b"),
    ("convocatoria", r"\b(convocatoria|convocatorias|postulaci[oó]n\s+abierta)\b"),
    ("curso", r"\b(curso|diplomado|taller|bootcamp|campus|certificaci[oó]n|"
              r"capacitaci[oó]n)\b"),
    ("proceso", r"\b(examen|admisi[oó]n|matr[ií]cula|inscripci[oó]n|"
                r"entrevista|evaluaci[oó]n)\b"),
]

# QUE SEPARA UN TRAMITE DE UN BOLETIN, y por que no son palabras.
#
# La primera corrida (27-ago-2026) trajo 22 hilos y solo 5 eran tramites: el
# resto eran boletines de bolsas de trabajo y de plataformas de cursos. Filtrar
# por palabras NO los separa, y se probo: "curso", "oportunidad", "vacante" y
# "postulacion" salen exactamente igual en los dos lados.
#
# Lo que si los separa es una cabecera. `List-Unsubscribe` la lleva SIEMPRE un
# envio masivo --se la exige la ley de correo comercial-- y no la lleva NUNCA
# la coordinacion de un programa escribiendole a una persona. `correo_gmail`
# la pide y la devuelve como `lista_baja`. Es una senal estructural, no una
# adivinanza sobre el contenido.
#
# El segundo cedazo, para los remitentes automaticos que no ponen la cabecera
# (las alertas de las bolsas son el caso tipico). Va en DOS listas, y el
# reparto lo forzo una revision del 28-ago-2026, que le paso controles
# negativos a la version de una sola lista y tumbo cinco, entre ellos:
#
#   DESCARTADO  "Convocatoria Beca MEXIA 2026: promocion de mujeres en IA"
#   DESCARTADO  "Generacion 2026 - promocion de egresados"
#   DESCARTADO  remitente noreply@ de la universidad que coordinaba un
#               programa con el proceso ABIERTO
#   DESCARTADO  remitente no-reply@notificaciones.gob.mx
#
# Dos lecciones. Una: "promocion" en Mexico significa tambien *generacion de
# egresados*, asi que se cae de la lista entera -- una palabra ambigua en un
# filtro de descarte tira cosas buenas en silencio. Dos: las instituciones
# notifican desde `noreply@`, asi que ese patron NO puede descartar por si
# solo; solo cuenta si ademas viene con `List-Unsubscribe`. Perder la
# citacion de un examen porque la mando un buzon automatico seria el fallo mas
# caro que puede cometer este modulo.
RUIDO = re.compile(
    r"(newsletter|linkedin\.com|indeed\.com|occ\.com\.mx|glassdoor|"
    r"coursera|udemy|platzi|descuento|black\s*friday)",
    re.IGNORECASE)


def _es_difusion(m: dict) -> bool:
    """¿Es esto un envio masivo y no una carta? La prueba, en un solo sitio.

    Dos criterios, y ninguno mira si el contenido "parece" interesante:

      1. la cabecera `List-Unsubscribe` (o `Precedence: bulk`), que trae todo
         envio masivo y ninguna carta escrita a una persona;
      2. una lista corta de remitentes automaticos que no la ponen -- las
         alertas de las bolsas de trabajo, que son el caso que la motivo.

    `noreply@` NO esta en esa lista, y es deliberado: las instituciones
    notifican desde ahi. El correo de una universidad que cita a un examen de
    admision puede salir de un `noreply@`, y descartarlo seria perder un plazo
    sin dejar rastro. Si ese buzon manda ademas un boletin, la cabecera del
    punto 1 ya lo caza.

    Vive en una funcion y no repartida por el modulo porque `revisar()` y
    `limpiar_difusion()` tienen que aplicar EXACTAMENTE el mismo criterio: si
    se separan, una guarda lo que la otra borra y la tabla parpadea sin que
    nadie entienda por que.
    """
    if m.get("lista_baja"):
        return True
    return bool(RUIDO.search(f"{m.get('de', '')} {m.get('asunto', '')}"))


def _preparar(con) -> None:
    con.executescript(ESQUEMA)


def _id(*partes: str) -> str:
    return hashlib.sha1("|".join(partes).encode("utf-8")).hexdigest()[:16]


def _asunto_llano(asunto: str | None) -> str:
    """El asunto sin los prefijos que le pone el cliente de correo.

    "Re:", "RE:", "RV:", "Fwd:" y "Fw:" los añade quien contesta, asi que dos
    asuntos que son el mismo se ven distintos. Se quitan todos los prefijos
    encadenados, no solo el primero: "Re: RV: Re: ..." es real.
    """
    t = (asunto or "").strip().lower()
    while True:
        nuevo = re.sub(r"^\s*(re|rv|fwd|fw)\s*:\s*", "", t)
        if nuevo == t:
            return " ".join(nuevo.split())
        t = nuevo


def _clase(texto: str) -> str:
    t = texto.lower()
    for nombre, patron in CLASES:
        if re.search(patron, t):
            return nombre
    return "otro"


def _organizacion(remitente: str) -> str:
    """El dominio de quien escribe, que es lo mas fiable que hay.

    El nombre para mostrar lo pone quien manda y cambia ("Programa Ejemplo",
    "Equipo PE", "Coordinacion"); el dominio no. Se guarda el dominio y, si
    hay nombre, viaja delante para que se lea.
    """
    m = re.search(r"@([\w.-]+)", remitente or "")
    dominio = m.group(1).lower() if m else ""
    nombre = (remitente or "").split("<")[0].strip().strip('"')
    return f"{nombre} <{dominio}>" if nombre and dominio else (dominio or nombre)


def _fecha_iso(cabecera: str) -> str:
    """Fecha de cabecera de correo -> ISO. Cadena vacia si no parsea.

    Se usa `email.utils` y no un `strptime` a mano porque las cabeceras Date
    llegan en media docena de formatos y con husos distintos; un parser propio
    falla en silencio con los que no previo, y una fecha mal leida aqui
    significa una novedad que no se anuncia.
    """
    from email.utils import parsedate_to_datetime
    try:
        d = parsedate_to_datetime(cabecera)
    except (TypeError, ValueError):
        return ""
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone().isoformat(timespec="seconds")


def _mio(remitente: str, yo: str) -> bool:
    return bool(yo) and yo.lower() in (remitente or "").lower()


# --------------------------------------------------------------------------
# 1-3. Descubrir, clasificar, comparar
# --------------------------------------------------------------------------

def revisar(limite_por_consulta: int = 25) -> dict:
    """Recorre Gmail y actualiza la tabla. Devuelve el resumen de lo que cambio.

    Es la unica funcion que toca la red. Todo lo demas del modulo --y el
    informe de arranque-- lee lo que esta deja escrito, que es lo que permite
    que una sesion arranque sin esperar a Google.
    """
    import correo_gmail as gmail

    if not gmail.puede_leer():
        return {"error": "El token de Gmail no tiene permiso de lectura. "
                         "Autoriza con `python correo_gmail.py --ampliar`."}

    from perfil import CANDIDATO
    yo = CANDIDATO.get("correo", "")

    # Hilos que ya sigue `seguimiento.py`: se saltan para no contar dos veces
    # el mismo proceso con dos nombres. Ver la cabecera.
    with conexion() as con:
        _preparar(con)
        de_candidaturas = {r["hilo_gmail"] for r in con.execute(
            "SELECT hilo_gmail FROM candidaturas WHERE hilo_gmail IS NOT NULL")}
        # Y tambien por asunto normalizado: el guardia por hilo no basta.
        # Un proceso anclado en `candidaturas` por UN hilo puede tener otros
        # tres en Gmail, abiertos al cambiar el asunto, asi que el mismo
        # proceso aparecia dos veces en el arranque -- como "PROCESOS VIVOS" y
        # como "TRAMITES CON NOVEDAD". Es exactamente lo que la cabecera de
        # este modulo dice que no debe pasar.
        asuntos_candidatura = {
            _asunto_llano(r["asunto"]) for r in con.execute(
                "SELECT asunto FROM candidaturas WHERE asunto IS NOT NULL")
            if _asunto_llano(r["asunto"])}

    vistos: dict[str, dict] = {}
    for consulta in CONSULTAS:
        try:
            for m in gmail.mensajes(consulta, limite=limite_por_consulta):
                if m["hilo"] in de_candidaturas:
                    continue
                if _asunto_llano(m["asunto"]) in asuntos_candidatura:
                    continue
                # Difusion masiva: fuera. Un solo criterio, el de `_es_difusion`.
                if _es_difusion(m):
                    continue
                previo = vistos.get(m["hilo"])
                # De cada hilo interesa el mensaje MAS NUEVO: es el que dice si
                # hay novedad. (`seguimiento.emparejar` se queda con el mas
                # antiguo, porque alli lo que importa es cuando SALIO.)
                if previo is None or _fecha_iso(m["fecha"]) > _fecha_iso(previo["fecha"]):
                    vistos[m["hilo"]] = m
        except Exception as ex:                      # una consulta rota no
            print(f"  aviso: consulta fallida ({type(ex).__name__}: {ex})")  # tumba el resto

    nuevos, con_novedad, sin_cambio = [], [], 0
    ahora = ahora_iso()

    with conexion() as con:
        _preparar(con)
        for hilo, m in vistos.items():
            ident = _id("tramite", hilo)
            fecha = _fecha_iso(m["fecha"])
            de_ellos = not _mio(m["de"], yo)
            fila = con.execute("SELECT * FROM tramites WHERE id=?", (ident,)).fetchone()

            if fila is None:
                con.execute(
                    "INSERT INTO tramites (id, titulo, clase, organizacion, "
                    "hilo_gmail, remitente, estado, ultimo_mensaje, ultimo_de, "
                    "ultima_novedad, resumen_novedad, novedad_sin_leer, "
                    "requiere_accion, revisado, creado) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (ident, (m["asunto"] or "(sin asunto)")[:200],
                     _clase(f"{m['asunto']} {m['resumen']} {m['de']}"),
                     _organizacion(m["de"]), hilo, m["de"],
                     "abierto", fecha, "ellos" if de_ellos else "yo",
                     fecha if de_ellos else None,
                     (m["resumen"] or "")[:300] if de_ellos else None,
                     1 if de_ellos else 0, 0, ahora, ahora))
                nuevos.append({"id": ident, "titulo": m["asunto"], "hilo": hilo})
                continue

            # Ya existia. Solo hay novedad si entro algo mas nuevo que lo
            # ultimo registrado Y no lo escribimos nosotros. Comparar por
            # fecha y no por identificador de mensaje es lo que evita que una
            # relectura de la misma bandeja "descubra" la misma novedad cada
            # dia y el arranque acabe gritando cosas viejas.
            if fila["estado"] in ("cerrado", "descartado"):
                sin_cambio += 1
                con.execute("UPDATE tramites SET revisado=? WHERE id=?", (ahora, ident))
                continue

            es_nueva = de_ellos and fecha > (fila["ultima_novedad"] or "")
            if es_nueva:
                con.execute(
                    "UPDATE tramites SET ultimo_mensaje=?, ultimo_de='ellos', "
                    "ultima_novedad=?, resumen_novedad=?, novedad_sin_leer=1, "
                    "revisado=? WHERE id=?",
                    (fecha, fecha, (m["resumen"] or "")[:300], ahora, ident))
                con_novedad.append({"id": ident, "titulo": fila["titulo"],
                                    "resumen": (m["resumen"] or "")[:120]})
            else:
                sin_cambio += 1
                con.execute(
                    "UPDATE tramites SET ultimo_mensaje=?, ultimo_de=?, revisado=? "
                    "WHERE id=?",
                    (fecha, "ellos" if de_ellos else "yo", ahora, ident))

    return {"hilos_mirados": len(vistos), "nuevos": nuevos,
            "con_novedad": con_novedad, "sin_cambio": sin_cambio}


# --------------------------------------------------------------------------
# Consulta y gestos manuales
# --------------------------------------------------------------------------

def limpiar_difusion() -> int:
    """Saca de la tabla los hilos que hoy se reconocen como difusion.

    Existe porque la primera corrida (27-ago-2026) se hizo antes de que el
    filtro de `List-Unsubscribe` existiera y dejo 17 boletines dentro. NO
    adivina por el nombre: relee cada hilo en Gmail y mira la cabecera, que es
    la misma prueba que aplica `revisar()`. Comprobar cuesta una llamada por
    hilo; equivocarse cuesta borrar un tramite de verdad.

    Borrar aqui es correcto --y no lo seria en `vacantes`-- porque esta tabla
    es un espejo de Gmail: lo que haga falta, la siguiente revision lo trae.
    Se respeta lo que se haya tocado a mano (una accion anotada o un estado
    cerrado): eso es juicio humano y no se tira.
    """
    import correo_gmail as gmail

    if not gmail.puede_leer():
        return 0
    with conexion() as con:
        _preparar(con)
        filas = con.execute(
            "SELECT id, hilo_gmail, titulo, remitente FROM tramites "
            "WHERE (accion IS NULL OR accion='') "
            "AND estado NOT IN ('cerrado','descartado')").fetchall()
        fuera = []
        for f in filas:
            # Se RELEE el hilo antes de borrar, siempre. La version anterior
            # aplicaba la lista de palabras primero y borraba sin comprobar la
            # cabecera: con `noreply@` dentro de esa lista, eso habria tirado
            # la citacion a un examen sin mirarla. Comprobar cuesta
            # una llamada; equivocarse cuesta un plazo.
            m = gmail.ultimo_del_hilo(f["hilo_gmail"] or "")
            if m is None:
                continue                      # no se pudo leer: no se toca
            if _es_difusion({**m, "de": m.get("de") or f["remitente"],
                             "asunto": m.get("asunto") or f["titulo"]}):
                fuera.append(f["id"])
        for ident in fuera:
            con.execute("DELETE FROM tramites WHERE id=?", (ident,))
    return len(fuera)


# Dominios que no identifican a una organizacion: son buzones de personas.
BUZONES_PERSONALES = {"gmail.com", "hotmail.com", "outlook.com", "yahoo.com",
                      "live.com", "icloud.com", "protonmail.com"}


def _clave_proceso(fila) -> str:
    """Que hilos son el mismo asunto en la vida real.

    Gmail abre un hilo nuevo cada vez que cambia el asunto, asi que un solo
    programa llego a ocupar CUATRO filas ("EXAMEN DE SELECCION",
    "Reagendamiento", "Re: Reagendamiento", "Confirmacion para entrevista
    virtual") y otro, tres mas. Contarlas como cosas distintas no es solo
    inflar un numero: en el arranque de la sesion ocupaban nueve lineas de las
    veinte que hay, y enterraban lo que si es distinto.

    Se agrupa por ORGANIZACION, que es lo estable: el dominio de quien
    escribe no cambia aunque el asunto se reescriba entero. Lo detecto una
    revision el 28-ago-2026.
    """
    org = (fila["organizacion"] or "").split("<")[-1].strip(">").strip()
    # Si el ultimo mensaje del hilo lo escribiste tu, la "organizacion" es tu
    # propio buzon, y agrupar por ahi mete en un mismo saco cosas que no
    # tienen nada que ver -- pasaba con el reagendamiento de un examen y una
    # candidatura, juntas bajo "gmail.com" solo porque el ultimo en escribir
    # fue el mismo en las dos. Para esos, la clave es el asunto.
    if not org or org in BUZONES_PERSONALES:
        return _asunto_llano(fila["titulo"])[:60] or (fila["titulo"] or "")[:40]
    return org


def procesos(solo_novedades: bool = False) -> list[dict]:
    """Los tramites agrupados por proceso real, con su ultima novedad arriba.

    Es lo que debe leer un informe. `listar()` sigue devolviendo hilo a hilo,
    que es lo que hace falta para trabajar sobre uno concreto.
    """
    filas = listar(solo_abiertos=True)
    grupos: dict[str, dict] = {}
    for f in filas:
        clave = _clave_proceso(f)
        g = grupos.setdefault(clave, {
            "organizacion": clave, "clase": f["clase"], "hilos": 0,
            "titulo": f["titulo"], "id": f["id"], "ultima_novedad": "",
            "resumen_novedad": "", "novedad_sin_leer": 0, "requiere_accion": 0,
            "acciones": []})
        g["hilos"] += 1
        g["novedad_sin_leer"] = max(g["novedad_sin_leer"], f["novedad_sin_leer"] or 0)
        g["requiere_accion"] = max(g["requiere_accion"], f["requiere_accion"] or 0)
        if f.get("accion"):
            g["acciones"].append(f["accion"])
        # El titulo del grupo es el del mensaje MAS RECIENTE: "Confirmacion
        # para entrevista virtual" dice mucho mas que "EXAMEN DE SELECCION",
        # y es lo que esta pasando ahora.
        if (f["ultima_novedad"] or "") > g["ultima_novedad"]:
            g.update(ultima_novedad=f["ultima_novedad"], titulo=f["titulo"],
                     id=f["id"], resumen_novedad=f["resumen_novedad"] or "",
                     clase=f["clase"])
    salida = sorted(grupos.values(),
                    key=lambda g: (g["requiere_accion"], g["novedad_sin_leer"],
                                   g["ultima_novedad"]), reverse=True)
    return [g for g in salida if g["novedad_sin_leer"] or g["requiere_accion"]] \
        if solo_novedades else salida


def listar(solo_abiertos: bool = True) -> list[dict]:
    cond = "WHERE estado NOT IN ('cerrado','descartado')" if solo_abiertos else ""
    with conexion() as con:
        _preparar(con)
        return [dict(r) for r in con.execute(
            f"SELECT * FROM tramites {cond} "
            "ORDER BY requiere_accion DESC, novedad_sin_leer DESC, "
            "ultima_novedad DESC")]


def marcar_leido(ident: str = "") -> int:
    """Apaga la senal de novedad. Sin id, apaga todas.

    Existe porque una novedad que no se puede apagar deja de ser una senal: si
    el arranque grita lo mismo cinco dias seguidos, se aprende a ignorarlo, y
    entonces el dia que grite algo importante tampoco se leera.
    """
    with conexion() as con:
        _preparar(con)
        if ident:
            return con.execute(
                "UPDATE tramites SET novedad_sin_leer=0 WHERE id=?", (ident,)).rowcount
        return con.execute(
            "UPDATE tramites SET novedad_sin_leer=0 WHERE novedad_sin_leer=1").rowcount


def anotar_accion(ident: str, texto: str, fecha: str = "") -> bool:
    """Deja escrito que toca hacer con este tramite, y para cuando."""
    with conexion() as con:
        _preparar(con)
        return bool(con.execute(
            "UPDATE tramites SET accion=?, accion_fecha=?, requiere_accion=?, "
            "revisado=? WHERE id=?",
            (texto[:300], fecha or None, 1 if texto else 0, ahora_iso(),
             ident)).rowcount)


def cerrar(ident: str, descartado: bool = False) -> bool:
    with conexion() as con:
        _preparar(con)
        return bool(con.execute(
            "UPDATE tramites SET estado=?, novedad_sin_leer=0, requiere_accion=0, "
            "revisado=? WHERE id=?",
            ("descartado" if descartado else "cerrado", ahora_iso(), ident)).rowcount)


def resumen() -> dict:
    with conexion() as con:
        _preparar(con)
        por_clase = {r["clase"] or "otro": r["n"] for r in con.execute(
            "SELECT clase, COUNT(*) n FROM tramites "
            "WHERE estado NOT IN ('cerrado','descartado') GROUP BY clase")}
        n = con.execute(
            "SELECT COUNT(*) c FROM tramites WHERE novedad_sin_leer=1").fetchone()["c"]
        accion = con.execute(
            "SELECT COUNT(*) c FROM tramites WHERE requiere_accion=1").fetchone()["c"]
        ultimo = con.execute("SELECT MAX(revisado) f FROM tramites").fetchone()["f"]
    return {"por_clase": por_clase, "novedades": n, "requieren_accion": accion,
            "revisado": ultimo}


def _imprimir(filas: list[dict]) -> None:
    if not filas:
        print("Sin tramites abiertos. (`--revisar` para mirar el correo.)")
        return
    for f in filas:
        marcas = []
        if f.get("novedad_sin_leer"):
            marcas.append("NOVEDAD")
        if f.get("requiere_accion"):
            marcas.append("ACCION")
        marca = f" [{' '.join(marcas)}]" if marcas else ""
        print(f"{f['id']}  {(f['clase'] or 'otro'):13} {f['titulo'][:70]}{marca}")
        if f.get("accion"):
            cuando = f" (para {f['accion_fecha']})" if f.get("accion_fecha") else ""
            print(f"           toca: {f['accion']}{cuando}")
        if f.get("resumen_novedad") and f.get("novedad_sin_leer"):
            print(f"           ultimo: {f['resumen_novedad'][:100]}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--revisar", action="store_true", help="mira Gmail y actualiza")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--todos", action="store_true", help="incluye cerrados")
    ap.add_argument("--leidos", action="store_true", help="marca vistas las novedades")
    ap.add_argument("--leido", metavar="ID")
    ap.add_argument("--accion", nargs=2, metavar=("ID", "TEXTO"))
    ap.add_argument("--para", metavar="FECHA", default="", help="fecha ISO de --accion")
    ap.add_argument("--cerrar", metavar="ID")
    ap.add_argument("--descartar", metavar="ID")
    ap.add_argument("--limpiar", action="store_true",
                    help="saca de la tabla los boletines colados")
    args = ap.parse_args()

    if args.limpiar:
        print(f"{limpiar_difusion()} boletines fuera de la tabla.")
        return
    if args.leidos:
        print(f"{marcar_leido()} novedades marcadas como vistas.")
        return
    if args.leido:
        print("marcada." if marcar_leido(args.leido) else "no encontrada.")
        return
    if args.accion:
        ok = anotar_accion(args.accion[0], args.accion[1], args.para)
        print("anotada." if ok else "no encontrada.")
        return
    if args.cerrar or args.descartar:
        ident = args.cerrar or args.descartar
        print("cerrado." if cerrar(ident, bool(args.descartar)) else "no encontrado.")
        return

    if args.revisar:
        r = revisar()
        if r.get("error"):
            print(r["error"])
            return
        print(f"Hilos mirados: {r['hilos_mirados']} | nuevos: {len(r['nuevos'])} "
              f"| con novedad: {len(r['con_novedad'])} | sin cambio: {r['sin_cambio']}")
        for x in r["nuevos"]:
            print(f"  + {x['titulo'][:80]}")
        for x in r["con_novedad"]:
            print(f"  ! {x['titulo'][:60]} -> {x['resumen']}")

    filas = listar(solo_abiertos=not args.todos)
    if args.json:
        print(json.dumps({"tramites": filas, "resumen": resumen()},
                         ensure_ascii=False, indent=2))
    else:
        print()
        _imprimir(filas)


if __name__ == "__main__":
    main()
