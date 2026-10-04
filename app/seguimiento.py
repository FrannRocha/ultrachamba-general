"""
Seguimiento automatico de candidaturas: quien contesto y quien lleva callado.

Por que existe. La idea es hacer UNA sola cosa: leer el correo y darle a
Enviar. Todo lo demas --enterarse de que salio, vigilar si contestan, contar
los dias de silencio-- tiene que ocurrir solo. Hasta ahora `enviada` solo se
rellenaba si alguien pulsaba "ya la envie" en el panel, es decir: el sistema
pedia hacer de secretario de uno mismo. Este modulo lo mira en Gmail.

Las tres cosas que hace, en orden:

  1. EMPAREJAR. Busca en Enviados el correo que corresponde a cada candidatura
     y le pega su hilo de Gmail. A partir de ahi la candidatura tiene ancla.
  2. REVISAR. Recorre cada hilo anclado y ve si entro algo que no salio de
     esta cuenta. Si entro -> respondida. Si no -> cuenta los dias callados.
  3. ADOPTAR. Mete en el sistema hilos que se mandaron A MANO antes de que
     esto existiera (por ejemplo, con un programa de formacion). Sin esto, el
     seguimiento solo veria el trocito de mundo que genero la cola, que es
     justo lo contrario de lo que sirve.

Se ancla al HILO y no al asunto: el asunto lo reescribe quien contesta ("Re:",
"RV:", o de cero) y el rastro se pierde EN SILENCIO, que es la peor forma de
perderlo. El hilo de Gmail sobrevive a todo eso.

Regla que hereda del proyecto: esto solo hace UPDATE de columnas concretas.
Nunca crea corridas ni pasa por `guardar()`.

LO QUE ESTE MODULO NO PUEDE VER, y por que importa. Todo lo de arriba mira
Gmail, asi que un proceso que avanza POR TELEFONO le es invisible: una empresa
que llama para citar a un examen no deja hilo. El panel llego a decir "Con
respuesta: 0" el mismo dia en que una candidatura avanzo por telefono, no por
un fallo de calculo sino porque esa respuesta no cabia en ningun sitio:
`procesos-en-marcha` se construia con `WHERE hilo_gmail IS NOT NULL`.

Desde entonces una candidatura puede llevar `via='telefono'` o el estado
`pendiente-accion`, con `canal_respuesta`, `pendiente` y `pendiente_fecha`
(ver `almacen.AMPLIACIONES`). Este modulo NO las escribe ni las pisa --las
pone la persona, y son juicio humano-- pero si las cuenta en `resumen()`, que
es lo que lee el panel. Y `emparejar()` las excluye a proposito: emparejar por
asunto una llamada con un hilo de correo le pondria un ancla falsa.

Uso:
    python seguimiento.py                      # emparejar + revisar + informe
    python seguimiento.py --adoptar "convocatoria"  # adopta hilos ya enviados
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import re

import correo_gmail as gmail
from almacen import conexion
from nucleo import ahora_iso, sin_acentos

# Estados que este modulo puede escribir. Los demas (entrevista, oferta,
# rechazo, descartada, pendiente-accion) los pone la persona y aqui NO se
# tocan: una heuristica no debe pisar un juicio humano.
MIOS = {"borrador", "pendiente-acuse", "enviada", "acuse", "silencio",
        "rebote"}

DIAS_PARA_AVISAR = 7   # a los 7 dias sin respuesta deja de ser "esperando"

# Un correo devuelto importa mas que uno sin contestar: significa que la
# direccion era mala. El proyecto ya avisa de que un correo inferido por
# patron puede rebotar, y hasta ahora nadie se enteraba de que rebotaba.
REMITENTES_DE_REBOTE = ("mailer-daemon", "postmaster")


def _id(*partes: str) -> str:
    return hashlib.sha1("|".join(partes).encode()).hexdigest()[:16]


def _asunto_normal(texto: str) -> str:
    """El asunto sin los prefijos que le anaden al responder o reenviar."""
    t = sin_acentos(texto or "").lower().strip()
    while True:
        nuevo = re.sub(r"^\s*(re|rv|fwd|fw)\s*(\[\d+\])?\s*:\s*", "", t)
        if nuevo == t:
            break
        t = nuevo
    return re.sub(r"\s+", " ", t).strip()


def _fecha(ms: str | int | None) -> str:
    """La fecha interna de Gmail (ms desde epoch) como ISO local."""
    if not ms:
        return ""
    return dt.datetime.fromtimestamp(int(ms) / 1000).astimezone().isoformat(
        timespec="seconds")


def _cabeceras(mensaje: dict) -> dict:
    return {h["name"].lower(): h["value"]
            for h in mensaje.get("payload", {}).get("headers", [])}


def _yo() -> str:
    return gmail._servicio().users().getProfile(userId="me")\
        .execute()["emailAddress"].lower()


# --------------------------------------------------------------------------
# 1. Emparejar: candidatura -> hilo de Gmail
# --------------------------------------------------------------------------

def emparejar(dias: int = 90) -> list[dict]:
    """Ancla al hilo las candidaturas que ya salieron, y las marca enviadas.

    Aqui es donde el sistema deja de depender de que alguien avise. Si el
    asunto aparece en Enviados, es que la mando: se anota la fecha REAL del
    envio, no la del dia que se acordo de pulsar el boton.
    """
    s = gmail._servicio()
    enviados = s.users().messages().list(
        userId="me", q=f"in:sent newer_than:{dias}d", maxResults=200).execute()

    # asunto normalizado -> el mensaje MAS ANTIGUO con ese asunto (el original,
    # no la insistencia posterior; la fecha de envio que interesa es la primera)
    por_asunto: dict[str, dict] = {}
    for m in enviados.get("messages", []):
        d = s.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["Subject", "To"]).execute()
        clave = _asunto_normal(_cabeceras(d).get("subject", ""))
        if not clave:
            continue
        previo = por_asunto.get(clave)
        if previo is None or int(d["internalDate"]) < int(previo["internalDate"]):
            por_asunto[clave] = d

    tocadas = []
    with conexion() as con:
        # Se excluyen los procesos que NO nacieron del correo (via='telefono'
        # desde el 27-ago-2026). Si no, este emparejador por asunto le pega un
        # hilo de Gmail a una llamada telefonica solo porque el texto se
        # parece, y a partir de ahi `revisar()` cuenta dias de silencio de un
        # correo que nunca se mando. El ancla equivocada es peor que ninguna:
        # no da error, miente en silencio.
        pendientes = con.execute(
            "SELECT id, asunto, estado FROM candidaturas "
            "WHERE hilo_gmail IS NULL AND asunto IS NOT NULL "
            "AND (via IS NULL OR via != 'telefono')").fetchall()
        for c in pendientes:
            hallado = por_asunto.get(_asunto_normal(c["asunto"]))
            if not hallado:
                continue
            estado = "enviada" if c["estado"] in MIOS else c["estado"]
            con.execute(
                "UPDATE candidaturas SET hilo_gmail=?, mensaje_gmail=?, "
                "enviada=COALESCE(enviada, ?), estado=?, actualizada=? WHERE id=?",
                (hallado["threadId"], hallado["id"],
                 _fecha(hallado["internalDate"])[:10], estado, ahora_iso(), c["id"]))
            tocadas.append({"id": c["id"], "asunto": c["asunto"],
                            "enviada": _fecha(hallado["internalDate"])[:10]})
    return tocadas


# --------------------------------------------------------------------------
# 2. Revisar: quien contesto, quien calla
# --------------------------------------------------------------------------

def revisar() -> list[dict]:
    """Mira cada hilo anclado y actualiza respuesta / dias de silencio."""
    s = gmail._servicio()
    yo = _yo()
    hoy = dt.date.today()
    informe = []

    with conexion() as con:
        filas = con.execute(
            "SELECT id, asunto, estado, hilo_gmail FROM candidaturas "
            "WHERE hilo_gmail IS NOT NULL").fetchall()

        for c in filas:
            try:
                hilo = s.users().threads().get(
                    userId="me", id=c["hilo_gmail"], format="metadata",
                    metadataHeaders=["From", "Subject", "Date"]).execute()
            except Exception as ex:      # el hilo se borro: se suelta el ancla
                if "404" not in str(ex):
                    raise
                con.execute("UPDATE candidaturas SET hilo_gmail=NULL, "
                            "actualizada=? WHERE id=?", (ahora_iso(), c["id"]))
                continue

            mensajes = sorted(hilo.get("messages", []),
                              key=lambda m: int(m.get("internalDate", 0)))
            salientes = [m for m in mensajes if "SENT" in (m.get("labelIds") or [])]
            # Entrante = ni lo mandamos nosotros ni es un borrador a medias.
            entrantes = [m for m in mensajes
                         if "SENT" not in (m.get("labelIds") or [])
                         and "DRAFT" not in (m.get("labelIds") or [])
                         and yo not in _cabeceras(m).get("from", "").lower()]

            if not salientes:
                continue
            ultimo_nuestro = salientes[-1]
            corte = int(ultimo_nuestro["internalDate"])
            # Solo cuenta lo que llego DESPUES de lo ultimo que mandamos: una
            # respuesta vieja de otro asunto del mismo hilo no es una respuesta
            # a esta candidatura.
            respuestas = [m for m in entrantes if int(m["internalDate"]) > corte]

            nuevo_estado, respondida, silencio, nota = c["estado"], None, None, None

            if respuestas:
                ultima = respuestas[-1]
                de = _cabeceras(ultima).get("from", "")
                respondida = _fecha(ultima["internalDate"])[:10]
                rebote = any(x in de.lower() for x in REMITENTES_DE_REBOTE)
                if c["estado"] in MIOS:
                    nuevo_estado = "rebote" if rebote else "acuse"
                nota = ("DEVUELTO por " if rebote else "respondio ") + \
                       f"{de[:60]} el {respondida}: {(ultima.get('snippet') or '')[:120]}"
            else:
                silencio = (hoy - dt.date.fromisoformat(
                    _fecha(ultimo_nuestro["internalDate"])[:10])).days
                if silencio >= DIAS_PARA_AVISAR and c["estado"] in MIOS:
                    nuevo_estado = "silencio"

            con.execute(
                "UPDATE candidaturas SET estado=?, respondida=?, dias_silencio=?, "
                "mensaje_gmail=?, ultimo_visto=?, "
                "notas=COALESCE(?, notas), actualizada=? WHERE id=?",
                (nuevo_estado, respondida, silencio, ultimo_nuestro["id"],
                 ahora_iso(), nota, ahora_iso(), c["id"]))

            informe.append({"id": c["id"], "asunto": c["asunto"],
                            "estado": nuevo_estado, "respondida": respondida,
                            "dias_silencio": silencio, "nota": nota})
    return informe


# --------------------------------------------------------------------------
# 3. Adoptar: hilos que se mandaron a mano
# --------------------------------------------------------------------------

def adoptar(consulta: str, via: str = "correo-directo") -> list[dict]:
    """Da de alta como candidatura cada hilo enviado que case con la consulta.

    Para lo que ya se movio por cuenta propia --reagendar un examen, preguntar
    por el estatus de un programa-- y que el sistema no vio nacer. Si el seguimiento solo cubriera lo que genero la cola, seria un
    seguimiento de la cola, no de su busqueda.
    """
    s = gmail._servicio()
    r = s.users().messages().list(
        userId="me", q=f"in:sent {consulta}", maxResults=25).execute()

    por_hilo: dict[str, dict] = {}
    for m in r.get("messages", []):
        d = s.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["Subject", "To"]).execute()
        h = d["threadId"]
        if h not in por_hilo or int(d["internalDate"]) < int(por_hilo[h]["internalDate"]):
            por_hilo[h] = d

    # Lo adoptado nace como 'gestion' a proposito. Estos hilos se escribieron
    # a mano y la mayoria son tramites de procesos abiertos; dar por
    # supuesto que son candidaturas fue justo lo que inflo la tasa del correo.
    # Si alguno SI es una candidatura, se asciende a mano: mejor quedarse corto
    # en una metrica que presumir de lo que no se hizo.
    nuevas = []
    with conexion() as con:
        for hilo, d in por_hilo.items():
            if con.execute("SELECT 1 FROM candidaturas WHERE hilo_gmail=?",
                           (hilo,)).fetchone():
                continue
            cab = _cabeceras(d)
            asunto, para = cab.get("subject", ""), cab.get("to", "")
            ident = _id("adoptada", hilo)
            ahora = ahora_iso()
            con.execute("""
                INSERT INTO candidaturas (id, via, asunto, estado, enviada,
                                          hilo_gmail, mensaje_gmail, notas,
                                          creada, actualizada, tipo)
                VALUES (?,?,?,'enviada',?,?,?,?,?,?,'gestion')
                ON CONFLICT(id) DO NOTHING""",
                (ident, via, asunto, _fecha(d["internalDate"])[:10], hilo, d["id"],
                 f"adoptada del correo; enviada a mano a {para[:80]}", ahora, ahora))
            nuevas.append({"id": ident, "asunto": asunto, "para": para,
                           "enviada": _fecha(d["internalDate"])[:10]})
    return nuevas


# --------------------------------------------------------------------------

def resumen() -> dict:
    """Lo que el panel necesita para ensenar el estado sin recalcular nada."""
    with conexion() as con:
        por_estado = {r["estado"]: r["n"] for r in con.execute(
            "SELECT estado, COUNT(*) n FROM candidaturas GROUP BY estado")}
        pendientes = [dict(r) for r in con.execute("""
            SELECT id, asunto, estado, enviada, dias_silencio, respondida, notas,
                   canal_respuesta, pendiente, pendiente_fecha, via
            FROM candidaturas
            WHERE estado IN ('enviada','acuse','silencio','rebote','pendiente-accion')
            ORDER BY (dias_silencio IS NULL), dias_silencio DESC""")]
    # Las acciones van aparte y PRIMERO. Un hilo en silencio puede esperar a
    # manana; un examen no. Un examen con fecha llego a quedar sepultado bajo
    # nueve hilos de correo ordenados por dias de silencio, que es exactamente
    # el orden equivocado.
    acciones = sorted(
        (p for p in pendientes if p["estado"] == "pendiente-accion"),
        key=lambda p: (p["pendiente_fecha"] is None, p["pendiente_fecha"] or ""))
    return {"por_estado": por_estado, "pendientes": pendientes,
            "acciones": acciones,
            "hay_que_insistir": [p for p in pendientes
                                 if (p["dias_silencio"] or 0) >= DIAS_PARA_AVISAR]}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Seguimiento de candidaturas")
    p.add_argument("--adoptar", help="consulta de Gmail sobre Enviados")
    p.add_argument("--via", default="correo-directo")
    args = p.parse_args()

    if not gmail.puede_leer():
        raise SystemExit("falta el permiso de lectura: python correo_gmail.py --ampliar")

    if args.adoptar:
        for n in adoptar(args.adoptar, args.via):
            print(f"  adoptada: {n['enviada']} | {n['para'][:40]} | {n['asunto'][:60]}")
    else:
        for e in emparejar():
            print(f"  emparejada: {e['enviada']} | {e['asunto'][:60]}")

    revisar()
    r = resumen()
    print()
    print("ESTADOS:", ", ".join(f"{k}={v}" for k, v in sorted(r["por_estado"].items())) or "(vacio)")
    for x in r["pendientes"]:
        marca = "!" if (x["dias_silencio"] or 0) >= DIAS_PARA_AVISAR else " "
        # No confundir "no hay dias de silencio" con "contestaron". Una
        # postulacion por portal no tiene hilo de correo, asi que nunca tiene
        # dias contados; decir "respondida" ahi es una mentira del informe.
        dias = (f"{x['dias_silencio']}d callado" if x["dias_silencio"] is not None
                else "CONTESTADA" if x.get("respondida")
                else "por portal")
        print(f" {marca} [{x['estado']:9}] {dias:14} | {(x['asunto'] or '')[:55]}")
