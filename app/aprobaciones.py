"""
El visto bueno: lo que la persona aprueba, y lo que pasa cuando lo aprueba.

POR QUE EXISTE. Hasta ahora aprobar ocurria por chat, asi que el sistema solo
funcionaba cuando habia alguien delante del ordenador. El resultado medido:
diez borradores escritos y sin salir. El correo estaba
redactado; lo que faltaba era el gesto, y el gesto exigia estar en casa,
abrir Gmail y acordarse.

Aqui la aprobacion se separa de la ejecucion, que es lo que permite las dos
cosas que hacen falta:

    APROBAR   un si/no desde donde sea -- el panel, el movil, esta consola.
              Cuesta un toque y no necesita que nada mas este encendido.
    EJECUTAR  lo hace la maquina de casa cuando puede (`agente_local.py`).
              Mandar el correo, o dejar la pestana abierta para el portal.

El estado `aprobada` es justo esa separacion: "la persona dijo que si,
todavia no ha salido". Sin el, un si desde el telefono no tendria donde vivir
hasta que el ordenador despertara -- y este proyecto ya aprendio, con una
respuesta que llego por telefono, que lo que no cabe en la tabla no existe.

LAS TRES REGLAS DE ESTE MODULO

  1. **Nada sale sin un si explicito por candidatura.** No hay aprobacion en
     bloque ni "aprobar todo lo que puntue mas de X". Una tarjeta, un gesto.
  2. **Se envia lo aprobado, byte a byte.** Si hay borrador en Gmail, se manda
     ESE, no una reconstruccion: lo que leyo y lo que salio tienen que ser el
     mismo texto.
  3. **Un rechazo ensena.** El motivo baja a `vacantes.descartada_motivo`, que
     es lo que leen `elegir()` y `ranking()`, para que esa clase de vacante
     deje de proponerse. Rechazar sin motivo solo esconde la tarjeta.

Uso:
    python aprobaciones.py                    # lo que espera un si o un no
    python aprobaciones.py --aprobar ID
    python aprobaciones.py --rechazar ID "motivo"
    python aprobaciones.py --ejecutar         # saca lo aprobado (lo usa el agente)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from almacen import conexion              # noqa: E402
from nucleo import ahora_iso              # noqa: E402

# El trabajo de la tabla `tareas` donde viven las aprobaciones por ejecutar.
# Se reutiliza `tandas.py` en vez de inventar otra cola: ya sabe reanudar,
# contar intentos y no repetir, que es todo lo que hace falta aqui.
TRABAJO = "candidatura_aprobada"
TRABAJO_NAVEGADOR = "abrir_navegador"

# Estados que significan "esto espera una decision suya".
ESPERANDO = ("propuesta", "borrador")


def _tarjeta(f) -> dict:
    """Lo minimo para decidir, y nada mas.

    Cuatro datos. La tentacion es mandar la descripcion entera de la vacante,
    y es un error medido: una tarjeta larga no se lee en el telefono, y una
    tarjeta que no se lee no se aprueba.
    """
    return {
        "id": f["id"],
        "estado": f["estado"],
        "via": f["via"],
        "empresa": f["empresa"] or f["empresa_vacante"] or "",
        "puesto": f["titulo"] or f["asunto"] or "",
        "asunto": f["asunto"] or "",
        "cuerpo": f["cuerpo"] or "",
        "destino": f["correo_contacto"] or "",
        "url": f["url"] or "",
        # La ubicacion viaja en la tarjeta porque el filtro automatico no
        # atrapa todo: una vacante marcada `modalidad='remoto'` pasa aunque
        # este anclada a Leipzig o a Ciudad de Mexico (medido el 28-ago-2026,
        # 638 vacantes viables tienen ubicacion no mexicana y la mayoria son
        # remotos legitimos). Ensenarla deja que el ojo humano corte lo que el
        # SQL no puede sin tirar tambien los remotos buenos.
        "donde": (f["donde"] or "").strip() or ("remoto" if f["modalidad"] == "remoto" else ""),
        # Si nadie abrio la ficha, la ubicacion es la de la TARJETA del
        # listado, y esa se inventa: el colector de OCC escribia
        # `ubicacion or "Nuevo Leon, Mexico"`, o sea que cuando no leia la
        # ciudad, AFIRMABA Nuevo Leon. El 28-ago-2026 habia 38 vacantes del
        # carril asi, y la primera del ranking se titulaba "Becario de IT
        # Compliance - Tijuana". Ninguna estaba en la cola de aprobacion ese
        # dia, pero bastaria una: mudarse es una restriccion que no se puede
        # saltar, asi que la tarjeta lo dice en vez de callarlo.
        "donde_comprobada": bool((f["ubicacion_ficha"] or "").strip()),
        "creada": f["creada"],
        # Si ya hay borrador en Gmail se manda ese; se enseña para que quien
        # aprueba sepa que va a salir exactamente lo que puede leer alli.
        "borrador_gmail": _borrador_de(f["notas"]),
    }


def _borrador_de(notas: str | None) -> str:
    n = notas or ""
    return n.split(": ", 1)[1].strip() if n.startswith("borrador en Gmail: ") else ""


SQL_TARJETA = """
    SELECT c.id, c.estado, c.via, c.asunto, c.cuerpo, c.notas, c.creada,
           c.vacante_id, c.empresa_id, c.contacto_id, c.hilo_gmail,
           v.titulo, v.url, v.empresa AS empresa_vacante,
           COALESCE(v.ubicacion_ficha, v.ubicacion) AS donde, v.modalidad,
           v.ubicacion_ficha,
           e.nombre AS empresa, ct.correo AS correo_contacto
    FROM candidaturas c
    LEFT JOIN vacantes  v  ON v.id  = c.vacante_id
    LEFT JOIN empresas  e  ON e.id  = c.empresa_id
    LEFT JOIN contactos ct ON ct.id = c.contacto_id
"""


def pendientes(todas: bool = False) -> list[dict]:
    """Las que esperan un si o un no, YA FILTRADAS por viabilidad.

    El filtro no se escribe aqui: se importa de `postular.SQL_VIABLE` a traves
    de `cola._viable()`, que es la misma definicion que usa la cola al elegir.
    Escribirlo a mano es la cicatriz 4 del proyecto, y sin el pasaba esto
    (tres casos de diez en una revision):

      - Una vacante descartada por escrito ("pide experiencia") seguia
        ofreciendose para aprobar, porque su borrador era anterior al descarte
        y `rechazar()` no toca a los hermanos de la misma vacante. Un si desde
        el movil habria postulado a lo que ya se habia rechazado.
      - Otra era presencial en Ciudad de Mexico, `requiere_mudanza=1`.
      - Otra era un Werkstudent en Alemania, `ver_estado='inaccesible'`.

    El veto existia desde siempre, pero se aplicaba al GENERAR la cola y no al
    MOSTRAR lo pendiente, asi que una vacante que dejaba de ser viable despues
    de redactarle el correo se colaba igual.

    `todas=True` las devuelve sin filtrar, para poder ver que se esta ocultando.
    """
    from cola import _viable

    with conexion() as con:
        marcas = ",".join("?" * len(ESPERANDO))
        # Una candidatura espontanea (sin vacante) no tiene nada que filtrar.
        filtro = "" if todas else f" AND (c.vacante_id IS NULL OR {_viable('v')})"
        filas = con.execute(
            SQL_TARJETA + f" WHERE c.estado IN ({marcas}){filtro} "
            "ORDER BY c.creada DESC", ESPERANDO).fetchall()
    return [_tarjeta(f) for f in filas]


def atascadas() -> list[dict]:
    """Las que se quedaron en 'enviando': hubo un fallo a mitad del envio.

    No se reintentan solas. Hay que abrir Gmail y mirar si el correo salio;
    luego `--reintentar ID` (si no salio) o marcarla enviada a mano.
    """
    with conexion() as con:
        filas = con.execute(
            SQL_TARJETA + " WHERE c.estado = 'enviando'").fetchall()
    return [_tarjeta(f) for f in filas]


def aprobadas_sin_ejecutar() -> list[dict]:
    with conexion() as con:
        filas = con.execute(
            SQL_TARJETA + " WHERE c.estado = 'aprobada' ORDER BY c.creada ASC"
        ).fetchall()
    return [_tarjeta(f) for f in filas]


# --------------------------------------------------------------------------
# Los dos gestos
# --------------------------------------------------------------------------

def aprobar(ident: str, nota: str = "") -> dict:
    """Marca la candidatura como aprobada y la encola para ejecucion.

    NO envia aqui, a proposito. Aprobar tiene que responder al instante desde
    el telefono; enviar puede tardar, fallar por red o necesitar el navegador.
    Mezclarlos haria que un toque en el movil se quedara girando, y un boton
    que gira es un boton que se pulsa dos veces.
    """
    import tandas

    with conexion() as con:
        f = con.execute("SELECT estado FROM candidaturas WHERE id=?",
                        (ident,)).fetchone()
        if not f:
            return {"ok": False, "error": "candidatura no encontrada"}
        if f["estado"] not in ESPERANDO:
            return {"ok": False, "error": f"no esta esperando decision (esta en "
                                          f"'{f['estado']}')"}
        con.execute(
            "UPDATE candidaturas SET estado='aprobada', actualizada=?, "
            "notas=COALESCE(notas,'') || ? WHERE id=?",
            (ahora_iso(), f" | aprobada {ahora_iso()[:16]}"
                          + (f": {nota[:120]}" if nota else ""), ident))
    tandas.encolar(TRABAJO, [ident])
    return {"ok": True, "id": ident, "estado": "aprobada",
            "siguiente": "el agente local lo ejecutara (correo enviado o pestana abierta)"}


def rechazar(ident: str, motivo: str = "") -> dict:
    """Descarta la candidatura Y ensena al filtro.

    El motivo baja a la vacante porque la candidatura es de usar y tirar --
    manana se genera otra con otro identificador -- mientras que la vacante
    es la que se vuelve a mirar. Sin este paso, la misma oferta reaparece al
    dia siguiente y el rechazo no sirvio de nada.
    """
    motivo = (motivo or "descartada a mano").strip()[:200]
    with conexion() as con:
        n = con.execute(
            "UPDATE candidaturas SET estado='descartada', actualizada=?, "
            "notas=COALESCE(notas,'') || ' | rechazada: ' || ? WHERE id=?",
            (ahora_iso(), motivo, ident)).rowcount
        fila = con.execute("SELECT vacante_id FROM candidaturas WHERE id=?",
                           (ident,)).fetchone()
        if fila and fila["vacante_id"]:
            con.execute(
                "UPDATE vacantes SET descartada_motivo=?, descartada_fecha=? "
                "WHERE id=?", (motivo, ahora_iso(), fila["vacante_id"]))
    return {"ok": bool(n), "id": ident, "motivo": motivo}


# --------------------------------------------------------------------------
# La ejecucion (la hace el agente local, no el que aprueba)
# --------------------------------------------------------------------------

def ejecutar_una(ident: str) -> dict:
    """Saca adelante UNA candidatura aprobada. Devuelve que hizo exactamente.

    Tres desenlaces posibles, y los tres son resultados validos:

      enviada          salio el correo. La metrica se movio.
      borrador-listo   no hay permiso de envio: queda escrito en su Gmail con
                       el enlace directo. Sigue haciendo falta su dedo, pero
                       ya no hace falta que redacte ni que busque nada.
      navegador        es via portal: se encola abrir la pestana en casa. Un
                       portal pide su sesion, y el sistema no teclea
                       contrasenas ni resuelve CAPTCHAs. Eso no es una
                       limitacion por resolver: es la linea.
    """
    import correo_gmail as gmail
    import tandas

    with conexion() as con:
        f = con.execute(SQL_TARJETA + " WHERE c.id = ?", (ident,)).fetchone()
    if not f:
        return {"id": ident, "estado": "fallido", "error": "no encontrada"}
    if f["estado"] != "aprobada":
        return {"id": ident, "estado": "hecho", "nota": f"ya no esta aprobada "
                                                        f"(esta en '{f['estado']}')"}

    t = _tarjeta(f)

    # --- via portal: el navegador, en la maquina de casa ---
    #
    # Acaba en `en-portal` y no en `aprobada`, y es la diferencia entre una
    # cola que avanza y una que se atasca: el `jefe` vio que estos se quedaban
    # en 'aprobada' para siempre, saliendo cada dia en "aprobadas y sin salir"
    # y --antes del arreglo 1-- contando ademas en la metrica sin que nadie
    # hubiera tocado el portal. `en-portal` significa exactamente lo que pasa:
    # la pestana esta abierta y el formulario lo rellena el.
    if (t["via"] or "").startswith("portal"):
        if t["url"]:
            tandas.encolar(TRABAJO_NAVEGADOR, [t["url"]])
        _marcar(ident, "en-portal",
                pendiente="postular en el portal (la pestana queda abierta)")
        return {"id": ident, "estado": "navegador", "url": t["url"]}

    # --- via correo ---
    #
    # Sin destinatario no se envia, y no es un detalle: la cicatriz 17 dice que
    # "un contacto sin direccion es una pista, no un destinatario", y la cola
    # llego a proponer escribir a dos contactos "verificados" con la casilla
    # vacia. Aqui, ademas, la API de Gmail aceptaria el mensaje y lo mandaria a
    # ninguna parte -- se gastaria la candidatura sin que nadie la recibiera.
    if not t["destino"]:
        # `bloqueada`, no `aprobada`: le falta un dato y reintentarlo sin
        # conseguirlo antes solo gasta vueltas. Vuelve a la cola con
        # `python aprobaciones.py --reintentar ID` cuando haya correo.
        _marcar(ident, "bloqueada",
                pendiente="falta la direccion de correo del contacto")
        return {"id": ident, "estado": "sin-destinatario",
                "que_hacer": "conseguir el correo del contacto (empresas.py / "
                             "datos_contactos.py) y volver a ejecutar"}

    puede, porque = gmail.puede_enviar()
    if not puede:
        # Sin permiso de envio se deja el borrador, que es exactamente lo que
        # hacia el sistema antes. Degradar asi es deliberado: es mejor que
        # fallar, y deja el motivo a la vista para que se pueda arreglar.
        try:
            r = _asegurar_borrador(t)
            _marcar(ident, "aprobada", nota=f"borrador en Gmail: {r['id']}",
                    pendiente="pulsar Enviar en Gmail")
            return {"id": ident, "estado": "borrador-listo", "enlace": r.get("enlace"),
                    "por_que_no_se_envio": porque}
        except Exception as ex:
            return {"id": ident, "estado": "fallido", "error": f"{type(ex).__name__}: {ex}"}

    # EL CERROJO. Antes de tocar Gmail, la candidatura pasa a 'enviando' con
    # un UPDATE condicionado a que siga en 'aprobada'. Si otra ejecucion ya lo
    # hizo, el rowcount es 0 y esta se retira sin mandar nada.
    #
    # Sin esto habia dos formas de mandar el mismo correo dos veces, las dos
    # reproducidas por el `jefe` el 28-ago-2026:
    #   1. `agente_local` (cada 180 s) y el paso `aprobadas` de `dia.py` a la
    #      vez: `tandas` vuelve a servir una fila 'en-curso' con menos de 3
    #      intentos, y el chequeo de estado no valia porque el UPDATE a
    #      'enviada' ocurre DESPUES del envio.
    #   2. Una excepcion despues de que Gmail ya aceptara el mensaje (un
    #      tiempo de espera leyendo la respuesta): se marcaba fallida y se
    #      reintentaba hasta tres veces.
    # Dos correos iguales a la misma empresa no son un fallo tecnico: son una
    # candidatura quemada.
    with conexion() as con:
        tomada = con.execute(
            "UPDATE candidaturas SET estado='enviando', actualizada=? "
            "WHERE id=? AND estado='aprobada'", (ahora_iso(), ident)).rowcount
    if not tomada:
        return {"id": ident, "estado": "hecho",
                "nota": "otra ejecucion la tomo primero"}

    try:
        borrador = t["borrador_gmail"]
        if borrador:
            r = gmail.enviar_borrador(borrador)      # sale lo que el pudo leer
        else:
            r = gmail.enviar(t["destino"], t["asunto"], t["cuerpo"],
                             hilo=f["hilo_gmail"] or "")
    except Exception as ex:
        # Queda en 'enviando' A PROPOSITO: no se sabe si Gmail lo acepto antes
        # de romperse. Un reintento automatico podria duplicarlo, asi que se
        # deja parada y visible (`aprobaciones.py --atascadas`) para mirarla en
        # Gmail y decidir. Ante la duda, no mandar dos veces.
        with conexion() as con:
            con.execute(
                "UPDATE candidaturas SET pendiente=? WHERE id=?",
                (f"envio interrumpido: comprobar en Gmail si salio "
                 f"({type(ex).__name__})", ident))
        return {"id": ident, "estado": "fallido", "revisar_a_mano": True,
                "error": f"{type(ex).__name__}: {ex}"}

    with conexion() as con:
        con.execute(
            "UPDATE candidaturas SET estado='enviada', enviada=COALESCE(enviada, ?), "
            "hilo_gmail=COALESCE(?, hilo_gmail), mensaje_gmail=?, actualizada=? "
            "WHERE id=?",
            (ahora_iso()[:10], r.get("hilo"), r.get("id"), ahora_iso(), ident))
        # La vacante se marca aplicada para que el ranking no la reofrezca.
        # Ojo: `aplicada` es una senal para el ranking, NO la metrica.
        if f["vacante_id"]:
            con.execute("UPDATE vacantes SET aplicada=1 WHERE id=?", (f["vacante_id"],))
    return {"id": ident, "estado": "enviada", "destino": t["destino"],
            "hilo": r.get("hilo")}


def _asegurar_borrador(t: dict) -> dict:
    """Crea el borrador si no lo hay; si ya existe, lo reescribe.

    Nunca crea uno nuevo cuando hay uno vivo: la primera version de esto
    dejaba una copia mas en la bandeja cada vez que se tocaba el boton.
    """
    import correo_gmail as gmail
    if t["borrador_gmail"]:
        vivo = gmail.actualizar_borrador(t["borrador_gmail"], t["destino"],
                                         t["asunto"], t["cuerpo"])
        if vivo:
            return vivo
    return gmail.crear_borrador(t["destino"], t["asunto"], t["cuerpo"])


def _marcar(ident: str, estado: str, nota: str = "", pendiente: str = "") -> None:
    with conexion() as con:
        con.execute(
            "UPDATE candidaturas SET estado=?, actualizada=?, "
            "pendiente=COALESCE(NULLIF(?,''), pendiente), "
            "notas=CASE WHEN ?='' THEN notas ELSE ? END WHERE id=?",
            (estado, ahora_iso(), pendiente, nota, nota, ident))


def ejecutar_pendientes(tope: int = 5) -> list[dict]:
    """Todas las aprobadas que quepan, de una en una.

    El tope existe para que un fallo repetido no vacie la cola entera contra
    una API caida. `tandas` ya cuenta intentos y sella a los tres.
    """
    import tandas

    hechas = []
    for ident in tandas.siguiente_tanda(TRABAJO, tamano=tope):
        r = ejecutar_una(ident)
        tandas.completar(TRABAJO, {ident: {
            "estado": r.get("estado") if r.get("estado") != "fallido" else None,
            "error": r.get("error"), **r}})
        hechas.append(r)
    return hechas


def reintentar(ident: str) -> dict:
    """Devuelve a la cola una candidatura bloqueada, cuando ya no lo esta."""
    import tandas

    with conexion() as con:
        n = con.execute(
            "UPDATE candidaturas SET estado='aprobada', pendiente=NULL, "
            "actualizada=? WHERE id=? AND estado='bloqueada'",
            (ahora_iso(), ident)).rowcount
    if n:
        tandas.reiniciar(TRABAJO, solo_fallidas=False)
        tandas.encolar(TRABAJO, [ident])
    return {"ok": bool(n), "id": ident}


def bloqueadas() -> list[dict]:
    """Aprobadas que no pueden salir por algo concreto, con el motivo."""
    with conexion() as con:
        filas = con.execute(
            SQL_TARJETA + " WHERE c.estado IN ('bloqueada','en-portal') "
            "ORDER BY c.actualizada DESC").fetchall()
    return [_tarjeta(f) for f in filas]


def navegaciones_pendientes() -> list[str]:
    """URLs que esperan una pestana en la maquina de casa."""
    import tandas
    return tandas.siguiente_tanda(TRABAJO_NAVEGADOR, tamano=5)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aprobar", metavar="ID")
    ap.add_argument("--nota", default="")
    ap.add_argument("--rechazar", nargs=2, metavar=("ID", "MOTIVO"))
    ap.add_argument("--ejecutar", action="store_true")
    ap.add_argument("--atascadas", action="store_true",
                    help="las que se quedaron a mitad de envio")
    ap.add_argument("--bloqueadas", action="store_true",
                    help="aprobadas que no pueden salir, con el motivo")
    ap.add_argument("--reintentar", metavar="ID")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.aprobar:
        print(json.dumps(aprobar(args.aprobar, args.nota), ensure_ascii=False))
        return
    if args.rechazar:
        print(json.dumps(rechazar(*args.rechazar), ensure_ascii=False))
        return
    if args.atascadas:
        for f in atascadas():
            print(f"{f['id']}  {f['empresa'][:24]:24} {f['puesto'][:40]}")
            print("   comprueba en Gmail si salio; luego --reintentar o marcala enviada")
        return
    if args.bloqueadas:
        for f in bloqueadas():
            print(f"{f['id']}  {f['estado']:10} {f['empresa'][:24]:24} {f['puesto'][:34]}")
        return
    if args.reintentar:
        print(json.dumps(reintentar(args.reintentar), ensure_ascii=False))
        return
    if args.ejecutar:
        for r in ejecutar_pendientes():
            print(json.dumps(r, ensure_ascii=False))
        return

    filas = pendientes()
    if args.json:
        print(json.dumps({"pendientes": filas,
                          "aprobadas_sin_ejecutar": aprobadas_sin_ejecutar()},
                         ensure_ascii=False, indent=2))
        return
    if not filas:
        print("Nada esperando decision.")
    for f in filas:
        print(f"{f['id']}  {f['empresa'][:24]:24} {f['puesto'][:44]:44} "
              f"[{f['via']}]")
    esperando = aprobadas_sin_ejecutar()
    if esperando:
        print(f"\nAprobadas sin ejecutar: {len(esperando)} "
              f"(las saca `python app/agente_local.py`)")


if __name__ == "__main__":
    main()
