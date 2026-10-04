"""
El dia entero, en un comando. Lo que nadie tiene que mover a mano.

    python app/dia.py            # el ciclo completo
    python app/dia.py --rapido   # sin la corrida larga, para probar

Que hace, en orden, y por que ese orden:

  1. RECOLECTAR   corrida de las 13 fuentes. Va primero porque todo lo demas
                  se calcula sobre lo que traiga.
  2. LIMPIAR      recalcula los anios de experiencia sobre las descripciones.
                  Va aqui y no en la corrida porque tambien arregla lo viejo:
                  el 24-ago-2026 saco 88 vacantes que ocultaban sus anios.
  3. ENCOLAR      apunta que fichas de OCC hay que ir a leer con el navegador.
                  No las lee: solo deja la lista, porque eso necesita Chrome.
  4. SEGUIR       lee el Gmail configurado y actualiza quien contesto y quien
                  lleva callado. NO necesita navegador: usa su propio token.
  5. PREPARAR     elige las candidaturas del dia y redacta sus correos.
  6. REGENERAR    dashboard y JSON derivado, todo desde la base.

Lo que este ciclo NO hace, y no es un descuido:

  - **Postular.** Eso ocurre en el navegador con la sesion del usuario, y
    ademas cada envio lo aprueba la persona. Un sistema que dispara curriculums solo
    es justo lo que hace que las bolsas cierren cuentas.
  - **Enviar correos.** Los deja escritos en su Gmail. El pulsa Enviar.
  - **Iniciar sesion en ningun sitio.** Jamas.

Asi que el reparto real queda:

    esta rutina    todo lo de arriba, sola, cada dia
    la persona     mantener la sesion viva y aprobar. Dos gestos.

Pensado para lanzarse desde el Programador de tareas de Windows. Escribe un
resumen en `datos/dia.log` y termina con codigo 0 aunque una parte falle: que
una fuente se caiga no puede impedir que el resto del dia ocurra.
"""
from __future__ import annotations

import argparse
import datetime as dt
import traceback

from nucleo import DATOS, ahora_iso, log

BITACORA = DATOS / "dia.log"


def _anotar(linea: str) -> None:
    print(linea)
    with BITACORA.open("a", encoding="utf-8") as f:
        f.write(f"{ahora_iso()}  {linea}\n")


def _paso(nombre: str, funcion) -> dict:
    """Ejecuta un paso y sigue aunque reviente.

    Un fallo en una fuente no puede tumbar el ciclo entero: la corrida del
    17 de agosto se perdio asi, y con ella el dia de trabajo.
    """
    inicio = dt.datetime.now()
    try:
        detalle = funcion() or ""
        seg = (dt.datetime.now() - inicio).total_seconds()
        _anotar(f"[ok]    {nombre:14} {seg:6.1f}s  {detalle}")
        return {"paso": nombre, "ok": True, "detalle": str(detalle)}
    except Exception as ex:
        seg = (dt.datetime.now() - inicio).total_seconds()
        _anotar(f"[FALLO] {nombre:14} {seg:6.1f}s  {type(ex).__name__}: {ex}")
        _anotar("        " + traceback.format_exc().splitlines()[-1])
        return {"paso": nombre, "ok": False, "detalle": f"{type(ex).__name__}: {ex}"}


# --------------------------------------------------------------- los pasos --

def recolectar(rapido: bool) -> str:
    import excavadora
    r = excavadora.ejecutar(rapido=rapido) or {}
    return f"{r.get('guardadas', '?')} vacantes tocadas"


def limpiar_experiencia() -> str:
    """Recalcula los anios exigidos sobre las descripciones ya limpias."""
    import experiencia
    from almacen import conexion

    cambios = 0
    with conexion() as con:
        filas = con.execute(
            "SELECT id, titulo, descripcion, anios_exigidos FROM vacantes "
            "WHERE descripcion IS NOT NULL AND LENGTH(descripcion) > 150").fetchall()
        for f in filas:
            r = experiencia.anos_exigidos(f["titulo"] or "", f["descripcion"] or "")
            if r["minimo"] != f["anios_exigidos"]:
                con.execute(
                    "UPDATE vacantes SET anios_exigidos=?, evidencia_experiencia=? WHERE id=?",
                    (r["minimo"], (r.get("evidencia") or "")[:300], f["id"]))
                cambios += 1
    return f"{cambios} vacantes con los anios corregidos"


def enriquecer_http() -> str:
    """Lee las fichas de las fuentes que NO bloquean al robot.

    Computrabajo responde 200 a una peticion normal, asi que su
    enriquecimiento cabe entero dentro del ciclo automatico: no necesita que
    nadie abra Chrome. OCC e Indeed no pueden hacerlo --403 y estrangulamiento
    respectivamente-- y por eso van encolados para el navegador.

    Se limita a 80 por tanda: el resto lo coge el ciclo de mañana. Ir despacio
    con una fuente que no nos bloquea todavia es como se sigue sin bloquear.
    """
    import enriquecer
    r = enriquecer.computrabajo(80)
    return (f"{r['escritas']} fichas de computrabajo leidas"
            + (f", {r['cerradas']} cerradas" if r["cerradas"] else ""))


def buscar_bolsas() -> str:
    """Descubre la bolsa de trabajo propia de las empresas objetivo.

    Va despacio a proposito --25 empresas por ciclo-- porque cada intento son
    varias peticiones a terceros. En un mes cubre cientos de empresas sin que
    ninguna plataforma note nada.

    El valor: una vacante publicada en el sitio de la empresa se ve dias antes
    de llegar a OCC, si es que llega, y con la ubicacion que escribio la
    empresa en vez de un valor por defecto.
    """
    import descubrir_ats
    r = descubrir_ats.descubrir(25)
    n = len(r["hallados"])
    return (f"{r['probadas']} empresas probadas, {n} bolsas nuevas"
            + (": " + ", ".join(h["empresa"][:18] for h in r["hallados"]) if n else ""))


def encolar_fichas() -> str:
    """Deja apuntadas las fichas de OCC que hay que leer en el navegador."""
    import tandas
    import verificador_chrome as vc

    ids = vc.ids_para_detalle(500)
    if not ids:
        return "nada pendiente"
    tandas.encolar("ficha-occ", ids)
    p = tandas.progreso("ficha-occ")
    return f"{len(ids)} fichas en cola (pendientes totales: {p.get('pendiente', 0)})"


def seguir_correo() -> str:
    import correo_gmail as gmail
    if not gmail.puede_leer():
        return "sin permiso de lectura; se omite"
    import seguimiento as seg
    seg.emparejar()
    seg.revisar()
    r = seg.resumen()
    return (f"{len(r['pendientes'])} hilos vivos, "
            f"{len(r['hay_que_insistir'])} llevan 7 dias o mas")


def confirmar_acuses() -> str:
    """Comprueba en el correo que las postulaciones por portal LLEGARON.

    Pulsar Enviar no es enviar. El 24-ago-2026 cuatro envios por OCC fallaron
    en silencio --el modal se cierra, no hay error, la oferta sigue diciendo
    "Postularme"-- y dos de ellos quedaron marcados como enviados con la
    vacante aplicada=1, que SQL_VIABLE excluye para siempre. Se quemaron dos
    vacantes vivas del carril y el marcador mintio en dos.

    Por eso el panel ya no marca 'enviada' sino 'pendiente-acuse', y solo el
    acuse de la bolsa --leido aqui, del correo configurado-- lo asciende.
    """
    import correo_gmail as gmail
    if not gmail.puede_leer():
        return "sin permiso de lectura; se omite"
    import postular
    hechas = postular.confirmar()
    if not hechas:
        return "ningun acuse nuevo"
    return f"{len(hechas)} confirmadas: " + ", ".join(h["empresa"][:18] for h in hechas)


def revisar_tramites() -> str:
    """Becas, cursos y convocatorias: lo que no es una candidatura.

    Va junto al seguimiento de correo porque usa el mismo token y la misma
    bandeja, y porque el dia que no se mira ninguno de los dos es el dia que
    se pierde una convocatoria. Ver `tramites.py`.
    """
    import tramites
    r = tramites.revisar()
    if r.get("error"):
        return r["error"]
    return (f"{r['hilos_mirados']} hilos, {len(r['nuevos'])} nuevos, "
            f"{len(r['con_novedad'])} con novedad")


def sacar_aprobadas() -> str:
    """Ejecuta lo que se haya aprobado desde el movil.

    Esta aqui ADEMAS de en `agente_local.py`, y la duplicidad es deliberada:
    si el agente esta apagado, el ciclo diario es la segunda oportunidad para
    que una aprobacion no se quede en la cola una semana. Ejecutar dos veces
    la misma no hace dano -- `ejecutar_una` comprueba el estado antes.
    """
    import aprobaciones
    hechas = aprobaciones.ejecutar_pendientes()
    if not hechas:
        return "nada aprobado pendiente"
    return ", ".join(f"{h.get('id','')[:8]}:{h.get('estado')}" for h in hechas)


def preparar_cola() -> str:
    import cola
    elegidas = cola.elegir()
    return f"{len(elegidas)} candidaturas listas para revisar"


def regenerar() -> str:
    import generar_todo
    codigo = generar_todo.main()
    return "derivados regenerados" if codigo == 0 else f"generar_todo devolvio {codigo}"


def revisar_salud() -> str:
    """Ultimo paso: comprobar que los datos no mienten.

    Va al final a proposito, para medir el estado en que queda el dia. Si algo
    se rompio durante el ciclo, aparece aqui y no dentro de tres semanas.
    """
    import salud
    inf = salud.revisar()
    if inf["correcta"]:
        return "SALUD DE LOS DATOS: correcta"
    detalle = ", ".join(
        f"{p['nombre']}={p['valor']}" for p in inf["pruebas"] if not p["ok"])
    return f"*** SALUD: {len(inf['fallos'])} PROBLEMAS -> {detalle}"


# --------------------------------------------------------------------------

def ejecutar(rapido: bool = False) -> list[dict]:
    _anotar("=" * 64)
    _anotar(f"CICLO DIARIO {'(rapido)' if rapido else ''}")
    pasos = [
        ("recolectar", lambda: recolectar(rapido)),
        ("experiencia", limpiar_experiencia),
        ("enriquecer", enriquecer_http),
        ("bolsas", buscar_bolsas),
        ("fichas", encolar_fichas),
        ("seguimiento", seguir_correo),
        ("tramites", revisar_tramites),
        ("acuses", confirmar_acuses),
        ("aprobadas", sacar_aprobadas),
        ("cola", preparar_cola),
        ("regenerar", regenerar),
        ("salud", revisar_salud),
    ]
    if rapido:
        pasos = [p for p in pasos if p[0] != "recolectar"]

    resultados = [_paso(n, f) for n, f in pasos]
    fallidos = [r["paso"] for r in resultados if not r["ok"]]
    _anotar(f"FIN. {len(resultados) - len(fallidos)}/{len(resultados)} pasos ok"
            + (f" | fallaron: {', '.join(fallidos)}" if fallidos else ""))
    _anotar("Te toca: aprobar. Desde el ordenador, el panel en :8800 -> Plan de "
            "hoy. Desde el telefono, :8800/movil (arranca el servidor con --host).")
    return resultados


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rapido", action="store_true",
                    help="salta la corrida larga de recoleccion")
    a = ap.parse_args()
    ejecutar(rapido=a.rapido)
    raise SystemExit(0)   # nunca falla el proceso entero: ver la bitacora
