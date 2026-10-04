"""
El estado del sistema en una sola llamada: lo que ve una sesion que despierta.

POR QUE EXISTE. Cada sesion nueva de Claude empieza sin memoria y hasta hoy la
recuperaba leyendo: el traspaso (26 KB), la boveda, el codigo. Medido el
27-ago-2026, ese arranque costaba ~23.000 tokens y varios turnos, y aun asi
llegaba con cifras VIEJAS -- las del dia en que alguien escribio la nota, no
las de ahora. Dos veces se publico un numero sacado de un derivado.

Este modulo invierte el orden: en vez de que la sesion vaya a buscar el estado,
el estado sale a su encuentro, contado contra la base en el momento. Se puede
lanzar a mano o desde un gancho de inicio de sesion (por ejemplo `SessionStart`
de Claude Code), y lo usa tambien la vista movil del panel. Dice:

  - LA METRICA (candidaturas enviadas) y como se movio
  - que espera un gesto de la persona HOY, y desde cuando
  - que tramites (becas, cursos, convocatorias) tienen novedad sin leer
  - que se le vence pronto -- una convocatoria perdida no se recupera
  - si los datos estan sanos y si el catalogo se congelo

REGLAS QUE OBEDECE, y por que importan aqui mas que en ningun sitio:

  - Todo sale de `almacen.conexion()` y `cifras_panel()`. Ni un numero de un
    JSON: si esto miente, MIENTE EN TODAS LAS SESIONES a la vez.
  - No toca la red. Un gancho de arranque que llama a Gmail cuelga la sesion
    entera si Google tarda. Lo que hay de correo es lo que `tramites.py` y
    `seguimiento.py` dejaron escrito en su ultima corrida, con su fecha a la
    vista para que se note si esta viejo.
  - No escribe nada... salvo lo que escribe `conexion()` al abrir (DDL
    idempotente). Esto es de solo lectura para los datos.

Uso:
    python app/arranque.py            # informe completo, para leerlo tu
    python app/arranque.py --breve    # version corta, la que inyecta el gancho
    python app/arranque.py --json     # para encadenar
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Los modulos del proyecto se importan planos (`from almacen import ...`), asi
# que hasta ahora habia que estar parado en `app/`. Un gancho de sesion se
# lanza desde donde le da la gana al arnes, y una ruta relativa rota lo dejaria
# fallando en silencio -- justo el fallo que este proyecto ya pago tres veces.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# La consola de Windows escribe en cp1252 y este informe lleva nombres de
# empresa con acentos. Sin esto, un solo caracter fuera de la pagina de codigos
# tumba el gancho de sesion con UnicodeEncodeError y la sesion arranca CIEGA,
# que es peor que arrancar con un acento mal puesto.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from almacen import cifras_panel, conexion          # noqa: E402
from nucleo import DATOS                            # noqa: E402

# Cuantos dias sin corrida se consideran "catalogo congelado". Sale de la
# cicatriz 13: el sistema estuvo SIETE DIAS sin recolectar porque todos los
# ciclos se lanzaron con `--rapido`, y nada se puso rojo.
DIAS_CATALOGO_VIEJO = 3

# Una convocatoria que cierra dentro de esto es urgente. Dos semanas es el
# plazo real para juntar papeles de una beca sin correr.
DIAS_CIERRE_URGENTE = 21


def _hoy() -> date:
    return date.today()


def _dias_desde(iso: str | None) -> int | None:
    """Dias transcurridos desde una fecha ISO. None si no hay fecha o no parsea."""
    if not iso:
        return None
    try:
        return (_hoy() - datetime.fromisoformat(str(iso)[:19]).date()).days
    except ValueError:
        return None


def _dias_hasta(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        return (datetime.fromisoformat(str(iso)[:19]).date() - _hoy()).days
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Los bloques del informe. Cada uno es independiente y devuelve datos crudos:
# la presentacion va aparte, para que `--json` y el texto no se desincronicen.
# --------------------------------------------------------------------------

def _metrica(con) -> dict:
    """LA metrica y su movimiento reciente.

    `cifras_panel()` da el total; aqui interesa ademas si se movio, porque un
    numero quieto durante una semana es la unica senal fiable de que el sistema
    dejo de servir para lo que existe.
    """
    from cola import SQL_CUENTA, SQL_ES_CANDIDATURA

    ultima = con.execute(
        f"SELECT MAX(enviada) f FROM candidaturas WHERE {SQL_CUENTA} "
        f"AND {SQL_ES_CANDIDATURA}").fetchone()["f"]
    semana = con.execute(
        f"SELECT COUNT(*) n FROM candidaturas WHERE {SQL_CUENTA} "
        f"AND {SQL_ES_CANDIDATURA} AND enviada >= ?",
        ((_hoy() - timedelta(days=7)).isoformat(),)).fetchone()["n"]
    return {
        "ultima_enviada": ultima,
        "dias_sin_enviar": _dias_desde(ultima),
        "enviadas_7d": semana,
    }


def _esperando_visto_bueno(con) -> list[dict]:
    """Lo que esta detenido esperando UN gesto suyo.

    Es el primer bloque del informe a proposito. La regla del plan de
    automatizacion --"la persona solo verifica y envia"-- implica que si algo
    espera su visto bueno, eso es lo unico que importa de esta sesion.

    La lista NO se consulta aqui: se pide a `aprobaciones.pendientes()`, que es
    donde vive la definicion y que ademas aplica el filtro de viabilidad de
    `postular.SQL_VIABLE`. La primera version de este modulo escribia su propio
    SELECT y por eso anunciaba diez cuando de verdad eran siete: tres apuntaban
    a vacantes descartadas o de otra ciudad. Dos definiciones de lo mismo
    siempre acaban separandose -- es la cicatriz mas repetida del proyecto.
    """
    import aprobaciones

    salida = []
    for c in aprobaciones.pendientes():
        salida.append({
            "id": c["id"],
            "estado": c["estado"],
            "via": c["via"],
            "puesto": c["puesto"] or "(sin titulo)",
            "empresa": c["empresa"],
            "dias": _dias_desde(c["creada"]),
            "en_gmail": bool(c["borrador_gmail"]),
        })
    return salida


def _procesos_vivos(con) -> list[dict]:
    """Procesos que ya avanzaron y siguen abiertos.

    Incluye a proposito los que NO pasan por Gmail: la cicatriz 22 dice que el
    panel publicaba "Con respuesta: 0" el dia que llego la primera respuesta,
    porque la consulta filtraba por `hilo_gmail IS NOT NULL` y una llamada de
    telefono no tenia donde vivir. Aqui se cuenta por ESTADO, no por canal.
    """
    filas = con.execute(
        """
        SELECT c.id, c.estado, c.via, c.canal_respuesta, c.pendiente,
               c.pendiente_fecha, c.dias_silencio, c.respondida, c.enviada,
               c.asunto, v.titulo, e.nombre AS empresa, v.empresa AS empresa_vacante
        FROM candidaturas c
        LEFT JOIN vacantes v ON v.id = c.vacante_id
        LEFT JOIN empresas e ON e.id = c.empresa_id
        WHERE c.estado IN ('pendiente-accion', 'acuse', 'entrevista', 'oferta')
           OR (c.estado = 'enviada' AND c.respondida IS NOT NULL)
        ORDER BY CASE WHEN c.pendiente_fecha IS NULL THEN 1 ELSE 0 END,
                 c.pendiente_fecha ASC
        """).fetchall()
    return [{
        "id": f["id"],
        "estado": f["estado"],
        "empresa": f["empresa"] or f["empresa_vacante"] or "",
        "puesto": f["titulo"] or f["asunto"] or "",
        "pendiente": f["pendiente"] or "",
        "para_cuando": f["pendiente_fecha"],
        "dias_para": _dias_hasta(f["pendiente_fecha"]),
        "canal": f["canal_respuesta"] or "correo",
    } for f in filas]


def _silencios(con) -> list[dict]:
    """Candidaturas enviadas y calladas: candidatas a insistir.

    `seguimiento.py` ya calcula `dias_silencio`; aqui solo se saca a la
    superficie, porque insistir a los 7 dias es el gesto mas barato que existe
    y el que mas se olvida.
    """
    filas = con.execute(
        """
        SELECT c.id, c.dias_silencio, c.enviada, c.hilo_gmail, c.asunto,
               e.nombre AS empresa, v.empresa AS empresa_vacante, v.titulo
        FROM candidaturas c
        LEFT JOIN vacantes v ON v.id = c.vacante_id
        LEFT JOIN empresas e ON e.id = c.empresa_id
        WHERE c.estado IN ('enviada', 'silencio')
          AND c.respondida IS NULL
          AND COALESCE(c.dias_silencio, 0) >= 7
        ORDER BY c.dias_silencio DESC
        """).fetchall()
    return [{
        "id": f["id"],
        "empresa": f["empresa"] or f["empresa_vacante"] or "",
        "puesto": f["titulo"] or f["asunto"] or "",
        "dias": f["dias_silencio"],
        "hilo": f["hilo_gmail"],
    } for f in filas]


def _tramites(con) -> dict:
    """Becas, cursos y convocatorias con novedad sin leer.

    La tabla la mantiene `tramites.py`. Si aun no ha corrido nunca, esto
    devuelve vacio y lo DICE -- no finge que no hay novedades, que es la
    diferencia entre "no hay nada" y "nadie ha mirado".
    """
    hay = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='tramites'"
    ).fetchone()
    if not hay:
        return {"disponible": False, "novedades": [], "abiertos": 0}

    # Agrupado por PROCESO, no por hilo. Gmail abre un hilo nuevo cada vez que
    # cambia el asunto, asi que un solo programa llego a ocupar cuatro lineas
    # de un informe de veinte, y nueve hilos resultaron ser cinco procesos.
    import tramites
    novedades = tramites.procesos(solo_novedades=True)
    abiertos = con.execute(
        "SELECT COUNT(*) n FROM tramites WHERE estado NOT IN ('cerrado','descartado')"
    ).fetchone()["n"]
    ultima = con.execute("SELECT MAX(revisado) f FROM tramites").fetchone()["f"]
    return {"disponible": True, "novedades": novedades, "abiertos": abiertos,
            "revisado": ultima, "dias_sin_revisar": _dias_desde(ultima)}


def _cierres_proximos(con) -> list[dict]:
    """Convocatorias que se vencen. Lo unico irrecuperable del sistema.

    Una vacante perdida vuelve la semana que viene con otro id. Una
    convocatoria de beca cerrada no vuelve hasta el ano siguiente: ya se perdio
    una por seis semanas. Por eso los cierres van en el arranque y no
    escondidos en una pestana.
    """
    filas = con.execute(
        """
        SELECT nombre, institucion, cierra, gratis, url
        FROM cursos
        WHERE cierra IS NOT NULL AND cierra <> ''
          -- Anadido el 4-sep-2026 con el carril de formacion. Un aviso de
          -- plazo solo sirve si el plazo es TUYO: sin estos tres filtros el
          -- arranque gritaba por convocatorias que no admiten a un estudiante
          -- de licenciatura (estancias posdoctorales), por candidatos que
          -- nadie ha revisado todavia y por cosas ya descartadas a mano. Un
          -- aviso que incluye casos resueltos se aprende a ignorar, y el dia
          -- que marque algo real tampoco se mirara (cicatriz 31).
          AND (elegible IS NULL OR elegible = 1)
          AND descartado_motivo IS NULL
          AND (estado_revision IS NULL OR estado_revision = 'aceptado')
        ORDER BY cierra ASC
        """).fetchall()
    salida = []
    for f in filas:
        d = _dias_hasta(f["cierra"])
        if d is None or d < 0 or d > DIAS_CIERRE_URGENTE:
            continue
        salida.append({"nombre": f["nombre"], "institucion": f["institucion"],
                       "cierra": f["cierra"], "dias": d, "url": f["url"]})

    # Y no se avisa de lo que ya esta en marcha por correo. El arranque llego
    # a decir "este programa cierra en 14 dias" el mismo dia en que otra
    # seccion suya decia que el examen ya estaba aprobado y habia cita a
    # entrevista. Las dos frases eran ciertas; juntas, mentian.
    try:
        import formacion
        salida = [x for x in salida if not formacion.tramite_vivo_de(x)]
    except Exception:
        # El arranque no puede caerse por una mejora suya: si `formacion` no
        # esta o falla, se avisa de mas, que es el error barato de los dos.
        pass
    return salida


def _avisos(con, cif: dict) -> list[str]:
    """Lo que esta roto o a punto de estarlo, en frases que se entienden solas.

    Cada aviso de aqui nacio de un fallo real que no lanzaba excepcion. Es la
    lista de las cosas que el sistema ya se ha creido alguna vez.
    """
    avisos = []

    # Cicatriz 13: catalogo congelado siete dias sin que nada se pusiera rojo.
    ultima = con.execute("SELECT MAX(primera_vez) f FROM vacantes").fetchone()["f"]
    d = _dias_desde(ultima)
    if d is not None and d > DIAS_CATALOGO_VIEJO:
        avisos.append(
            f"CATALOGO VIEJO: {d} dias sin vacantes nuevas (ultima {str(ultima)[:10]}). "
            "Antes de decir 'no hay nada en tu carril', comprueba si recolecto.")

    # La salud de los datos la mide `salud.py`. Aqui solo se lee su veredicto:
    # repetir las comprobaciones seria una segunda fuente de verdad.
    archivo = DATOS / "salud.json"
    if archivo.exists():
        try:
            s = json.loads(archivo.read_text(encoding="utf-8"))
            # Las claves son las que ESCRIBE `salud.py` ("pruebas", "fallos"),
            # miradas en el archivo. La primera version de esto invento
            # "comprobaciones" porque encajaba, y el aviso no salio nunca sin
            # dar ningun error: la cicatriz 20 otra vez, en el modulo escrito
            # para vigilar las cicatrices.
            malas = s.get("fallos") or [c["nombre"] for c in s.get("pruebas", [])
                                        if not c.get("ok")]
            dias = _dias_desde(s.get("fecha"))
            if malas:
                avisos.append("SALUD DE DATOS en rojo: " + ", ".join(malas))
            if dias is not None and dias > 3:
                avisos.append(f"El informe de salud tiene {dias} dias: relanza `python app/dia.py`.")
        except (ValueError, KeyError):
            avisos.append("`datos/salud.json` no se puede leer: relanza `python app/salud.py`.")
    else:
        avisos.append("Nunca se ha medido la salud de los datos (`python app/salud.py`).")

    # Aprobadas que no salen. Este es el fallo nuevo que puede traer el modo
    # movil: se aprueba desde la calle, el agente de casa esta apagado,
    # y los correos se quedan en la cola sin que nadie lo note. Aprobar y
    # ejecutar estan separados a proposito (ver `aprobaciones.py`), asi que
    # alguien tiene que vigilar la costura -- y es aqui.
    n_aprobadas = con.execute(
        "SELECT COUNT(*) FROM candidaturas WHERE estado='aprobada'").fetchone()[0]
    if n_aprobadas:
        latido = DATOS / "agente_local.json"
        hace = None
        if latido.exists():
            hace = int((_hoy() - datetime.fromtimestamp(
                latido.stat().st_mtime).date()).days)
        if hace is None:
            avisos.append(
                f"{n_aprobadas} candidaturas APROBADAS y sin salir: el agente local "
                "no ha corrido nunca (`python app/agente_local.py`).")
        elif hace >= 1:
            avisos.append(
                f"{n_aprobadas} candidaturas APROBADAS y sin salir: el agente local "
                f"lleva {hace} dias sin pasar.")

    # Correo sin mirar. `tramites.py` solo sabe lo de su ultima corrida, asi
    # que un informe viejo se presenta como viejo y no como "no hay nada".
    t = _tramites(con)
    if t["disponible"] and (t.get("dias_sin_revisar") or 0) >= 2:
        avisos.append(f"El correo lleva {t['dias_sin_revisar']} dias sin revisarse "
                      "(`python app/tramites.py --revisar`).")

    # La metrica parada. No es un fallo tecnico, es EL fallo del proyecto.
    m = _metrica(con)
    if m["dias_sin_enviar"] is not None and m["dias_sin_enviar"] >= 7:
        avisos.append(
            f"{m['dias_sin_enviar']} dias sin enviar una candidatura. "
            "Es LA metrica: cualquier otro trabajo es secundario hoy.")

    if cif.get("sin_verificar", 0) and cif.get("panel"):
        pct = round(100 * cif["sin_verificar"] / cif["panel"])
        if pct >= 40:
            avisos.append(f"{pct}% del panel sin verificar ({cif['sin_verificar']} vacantes).")

    return avisos


# --------------------------------------------------------------------------
# El informe
# --------------------------------------------------------------------------

def estado() -> dict:
    """Todo el estado, en datos. La presentacion es cosa de `texto()`."""
    cif = cifras_panel()
    with conexion() as con:
        d = {
            "fecha": _hoy().isoformat(),
            "cifras": cif,
            "metrica": _metrica(con),
            "esperando_visto_bueno": _esperando_visto_bueno(con),
            "procesos_vivos": _procesos_vivos(con),
            "silencios": _silencios(con),
            "tramites": _tramites(con),
            "cierres": _cierres_proximos(con),
        }
        d["avisos"] = _avisos(con, cif)
    d["formacion"] = _formacion()
    return d


def _formacion() -> dict:
    """El carril de cursos, en una linea y solo si hay algo que hacer.

    Se llama FUERA del `with conexion()` de arriba a proposito: `formacion`
    abre la suya y anidar dos conexiones sobre el mismo archivo es como se
    fabrican los bloqueos intermitentes que luego nadie reproduce.

    Y devuelve `{}` cuando no hay nada accionable. El arranque ya costo 23.000
    tokens de contexto una vez por acumular secciones que casi siempre estaban
    vacias; una seccion que se imprime siempre acaba sin leerse.
    """
    try:
        import formacion
        c = formacion.cifras()
        return {"cifras": c,
                "pendientes": formacion.pendientes(),
                "en_marcha": formacion.en_marcha()}
    except Exception as e:
        # Igual que en los cierres: una mejora no puede tumbar el arranque.
        return {"error": f"{type(e).__name__}: {e}"}


def _linea_proceso(p: dict) -> str:
    cuando = ""
    if p["dias_para"] is not None:
        cuando = (f" (en {p['dias_para']} dias)" if p["dias_para"] >= 0
                  else f" (VENCIO hace {-p['dias_para']} dias)")
    que = f" | {p['pendiente']}" if p["pendiente"] else ""
    quien = p["empresa"] or (p["puesto"] or "(sin empresa)")[:60]
    return f"  - {quien}: {p['estado']}{que}{cuando}"


def texto(d: dict, breve: bool = False) -> str:
    """El informe en prosa corta. Breve = lo que cabe en un arranque de sesion.

    El formato no es decorativo: la sesion que lo lee tiene que poder decidir
    con esto SIN abrir un archivo mas. Por eso cada bloque dice el numero, la
    fecha y que hacer, y los bloques vacios se omiten en vez de imprimir un
    cero que hay que interpretar.
    """
    c, m = d["cifras"], d["metrica"]
    p = []
    p.append(f"ESTADO ULTRA CHAMBA | {d['fecha']} | contado contra la base")
    p.append("")
    p.append(f"METRICA | candidaturas enviadas: {c['candidaturas_enviadas']}"
             + (f" | ultima hace {m['dias_sin_enviar']} dias" if m["dias_sin_enviar"] is not None else "")
             + f" | {m['enviadas_7d']} en los ultimos 7 dias")
    p.append(f"Vacantes en juego: {c['en_juego']} (panel {c['panel']}, historico {c['historicas']})")

    if d["esperando_visto_bueno"]:
        p.append("")
        p.append(f"ESPERAN TU VISTO BUENO ({len(d['esperando_visto_bueno'])}):")
        for e in d["esperando_visto_bueno"][:6]:
            marca = "borrador ya en Gmail" if e["en_gmail"] else e["estado"]
            edad = f", hace {e['dias']} dias" if e["dias"] else ""
            p.append(f"  - {e['empresa']} | {e['puesto']} [{e['via']}, {marca}{edad}]")
        if len(d["esperando_visto_bueno"]) > 6:
            p.append(f"  - ... y {len(d['esperando_visto_bueno']) - 6} mas")

    if d["procesos_vivos"]:
        p.append("")
        p.append(f"PROCESOS VIVOS ({len(d['procesos_vivos'])}):")
        for pr in d["procesos_vivos"][:6]:
            p.append(_linea_proceso(pr))

    t = d["tramites"]
    if t["disponible"] and t["novedades"]:
        p.append("")
        p.append(f"TRAMITES CON NOVEDAD ({len(t['novedades'])}):")
        for n in t["novedades"][:6]:
            marca = "ACCION" if n.get("requiere_accion") else "nuevo"
            hilos = f" [{n['hilos']} correos]" if n.get("hilos", 1) > 1 else ""
            p.append(f"  - [{marca}] {n['titulo']}{hilos} ({n['clase']}): "
                     f"{(n.get('resumen_novedad') or '')[:90]}")
    elif not t["disponible"]:
        p.append("")
        p.append("TRAMITES: aun sin revisar nunca (`python app/tramites.py --revisar`).")

    if d["cierres"]:
        p.append("")
        p.append("SE CIERRAN PRONTO (no se recuperan):")
        for x in d["cierres"]:
            p.append(f"  - {x['nombre']} | cierra {x['cierra']} (en {x['dias']} dias)")

    # FORMACION. Solo lo accionable: una inscripcion que espera un si, o un
    # programa que avanzo por correo y la metrica no esta contando. El catalogo
    # entero vive en el panel; aqui no cabe y no hace falta.
    f = d.get("formacion") or {}
    fc = f.get("cifras") or {}
    lineas_f = []
    if f.get("pendientes"):
        lineas_f.append(f"  - {len(f['pendientes'])} inscripciones esperan tu si"
                        " (`python app/formacion.py`)")
    for m in (f.get("en_marcha") or [])[:3]:
        lineas_f.append(f"  - {m['curso'][:44]} avanza por correo y no cuenta como"
                        " inscripcion: enlazala")
    if fc.get("candidatos"):
        lineas_f.append(f"  - {fc['candidatos']} convocatorias encontradas sin revisar"
                        " (`python app/fuentes_cursos.py --candidatos`)")
    if lineas_f:
        p.append("")
        p.append(f"FORMACION | inscripciones enviadas: "
                 f"{fc.get('inscripciones_enviadas', 0)}")
        p.extend(lineas_f)

    if d["silencios"] and not breve:
        p.append("")
        p.append(f"CALLADAS 7+ DIAS ({len(d['silencios'])}): "
                 + ", ".join(f"{s['empresa']} ({s['dias']}d)" for s in d["silencios"][:8]))

    if d["avisos"]:
        p.append("")
        p.append("AVISOS:")
        for a in d["avisos"]:
            p.append(f"  ! {a}")

    if not breve:
        p.append("")
        p.append("Por fuente: " + ", ".join(
            f"{k}={v}" for k, v in list((c.get("por_fuente") or {}).items())[:8]))
        p.append("Comandos: `python app/dia.py` (ciclo) | `python app/servidor.py` (panel :8800) "
                 "- `python app/tramites.py --revisar` (correo)")

    return "\n".join(p)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--breve", action="store_true",
                    help="version corta, la que inyecta el gancho de sesion")
    ap.add_argument("--json", action="store_true", help="datos crudos")
    args = ap.parse_args()

    d = estado()
    if args.json:
        print(json.dumps(d, ensure_ascii=False, indent=2))
    else:
        print(texto(d, breve=args.breve))


if __name__ == "__main__":
    main()
