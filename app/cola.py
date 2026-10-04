"""
La cola del dia: tres candidaturas listas para revisar y enviar.

Por que existe. El sistema llego a recomendar 2.681 vacantes con CERO
postuladas. Una lista de 2.681 elementos no es una ayuda: es una forma
elegante de no empezar nunca. Nadie abre un panel y decide a cual de dos mil
seiscientas escribirle hoy.

Lo que hace este modulo es lo contrario de un buscador: **decide por quien
lo usa**. Cada dia elige tres, escribe el correo, y deja solo dos acciones
posibles — enviar o descartar. Tres es el numero a proposito: suficiente para
avanzar de verdad, pocas para que no se posponga.

Reglas que aplica al elegir, y por que:

  - **Nunca repite empresa en la misma semana.** Dos correos en tres dias a la
    misma compañia no duplican las opciones: las queman.
  - **Nunca repite vacante ya postulada.** Obvio, y sin registro es imposible.
  - **Mezcla las dos vias**: dos por vacante publicada y una en frio. La via
    en frio tiene menos competencia pero tarda mas; la publicada es inmediata
    pero compite con cientos. Hacer solo una de las dos es apostar todo a un
    canal.
  - **Prioriza lo que caduca.** Una vacante de hace tres dias vale mas que una
    de hace tres meses, aunque puntue algo menos: la segunda probablemente ya
    tiene finalistas.

Uso:
    python cola.py                # la cola de hoy
    python cola.py --preparar     # ademas, escribe los correos
    python cola.py --enviada ID   # marcar una como enviada
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timedelta

from almacen import conexion
from nucleo import ahora_iso

TAMANO = 3
DIAS_BLOQUEO_EMPRESA = 7


def _id(*partes: str) -> str:
    return hashlib.sha1("|".join(partes).encode("utf-8")).hexdigest()[:16]


def _empresas_bloqueadas() -> set[str]:
    """Empresas a las que ya se escribio hace poco.

    Escribir dos veces en pocos dias a la misma empresa no duplica las
    opciones: las quema. Se bloquean una semana.
    """
    corte = (date.today() - timedelta(days=DIAS_BLOQUEO_EMPRESA)).isoformat()
    with conexion() as con:
        filas = con.execute(
            "SELECT DISTINCT empresa_id FROM candidaturas "
            "WHERE enviada IS NOT NULL AND enviada >= ?", (corte,)).fetchall()
    return {f["empresa_id"] for f in filas if f["empresa_id"]}


def _ya_postuladas() -> set[str]:
    """Vacantes que ya NO deben volver a proponerse.

    Solo las enviadas o descartadas. Los borradores NO cuentan: el panel
    registra un borrador cada vez que muestra la cola, y si eso excluyera la
    vacante, cada recarga propondria tres distintas — la cola pareceria una
    ruleta en vez de un plan.
    """
    with conexion() as con:
        filas = con.execute(
            "SELECT vacante_id FROM candidaturas WHERE vacante_id IS NOT NULL "
            "AND estado != 'borrador'").fetchall()
    return {f["vacante_id"] for f in filas}


def _dias_desde(fecha: str | None) -> int | None:
    if not fecha:
        return None
    try:
        d = datetime.strptime(str(fecha)[:10], "%Y-%m-%d").date()
        return (date.today() - d).days
    except ValueError:
        return None


def _frescura(publicado: str | None) -> tuple[float, str]:
    """Una vacante recien publicada vale mas que una antigua con mejor puntaje.

    A los tres meses lo normal es que ya tengan finalistas: postular ahi es
    gastar el tiro. No se descarta, pero pierde prioridad.
    """
    dias = _dias_desde(publicado)
    if dias is None:
        return 0.0, "la fuente no dice cuando se publico"
    if dias <= 7:
        return 25.0, f"publicada hace {dias} dias: llegas de los primeros"
    if dias <= 21:
        return 15.0, f"publicada hace {dias} dias: aun a tiempo"
    if dias <= 60:
        return 5.0, f"publicada hace {dias} dias"
    return -12.0, f"publicada hace {dias} dias: probablemente ya tienen finalistas"


# --------------------------------------------------------------- la metrica --
# La MISMA decision escrita una sola vez. Antes vivia duplicada en
# `rendimiento()` y en `situacion()`, y las dos copias se separaron: el
# marcador del panel decia 10 candidaturas y 40% mientras `rendimiento()`,
# seis funciones mas abajo en este mismo archivo, decia 17 y 50%.
#
# El fallo de `situacion()` era de conjuntos: contaba como enviadas solo
# `estado='enviada'` y como respuestas solo `acuse/entrevista/oferta`, que son
# estados EXCLUYENTES. Numerador y denominador eran conjuntos disjuntos, asi
# que al llegar un acuse el marcador iba a BAJAR de 10 a 9.
#
# Y el rebote no es una respuesta: rellena `respondida` porque el servidor
# contesto, pero lo que contesto fue "esa direccion no existe". Contarlo
# inflaba el correo directo con la prueba de su propio fallo.
#
# LISTA BLANCA, no lista negra, y esto costo una noche. Esto decia
# `NOT IN ('borrador','descartada')`, asi que cualquier estado NUEVO entraba
# en la metrica por omision. El 27-ago-2026 se anadio `aprobada` para el modo
# movil y el agente `jefe` lo reprodujo sobre una copia: aprobar los diez
# borradores desde el telefono, SIN QUE SALIERA UN SOLO CORREO, subia la
# metrica de 14 a 24. Diez de las contadas tenian `enviada IS NULL`.
#
# Con lista blanca hay que decir explicitamente que un estado significa "esta
# candidatura salio". Olvidarse ahora esconde una candidatura real --molesto y
# visible-- en vez de inventarse diez --invisible y mentiroso--. La lista es
# la misma que habia de hecho el 27-ago, asi que la cifra no cambia: 14.
SQL_CUENTA = ("estado IN ('enviada','acuse','entrevista','oferta','rechazo',"
              "'silencio','rebote','pendiente-accion')")

# Solo lo que de verdad pide un puesto entra en la metrica. `COALESCE` porque
# las filas anteriores a esta columna se leen como candidaturas: las gestiones
# antiguas se marcaron a mano, una por una, al introducir la columna.
SQL_ES_CANDIDATURA = "COALESCE(tipo,'candidatura') = 'candidatura'"
SQL_RESPUESTA = ("(estado IN ('acuse','entrevista','oferta') "
                 "OR (respondida IS NOT NULL AND estado <> 'rebote'))")


def rendimiento() -> dict:
    """Que canal contesta de verdad, medido, no supuesto.

    Se agrupan todos los portales en uno: para decidir el reparto da igual si
    fue OCC o LinkedIn, lo que se compara es "rellenar un formulario" contra
    "escribirle a una persona".

    La tasa va SUAVIZADA con la regla de Laplace --(respuestas+1)/(enviadas+2)--
    y no cruda. Con pocos datos (por ejemplo, 0 respuestas en 7 envios por
    portal) la tasa cruda seria 0% exacto, y repartir por eso significaria no
    volver a postular por portal jamas: el canal quedaria condenado por siete
    intentos. La suavizada le deja un 11% y sigue midiendo.

    Es la diferencia entre aprender de los datos y quedarse atrapado en los
    primeros que llegaron.

    `telefono` va aparte y no cae en el cajon de 'correo'. El CASE anterior era
    binario --portal o correo-- asi que cualquier via nueva se contaba como
    correo sin avisar. Hoy solo hay gestiones por telefono, que este SQL ya
    excluye, pero el dia que entre una candidatura por ahi habria inflado la
    tasa del correo con algo que nunca paso por Gmail. Fallo silencioso
    evitado, no observado (27-ago-2026).
    """
    with conexion() as con:
        filas = con.execute("""
            SELECT CASE WHEN via LIKE 'portal-%' OR via='portal' THEN 'portal'
                        WHEN via='telefono' THEN 'telefono'
                        ELSE 'correo' END AS canal,
                   COUNT(*) AS enviadas,
                   SUM(CASE WHEN {resp} THEN 1 ELSE 0 END) AS respuestas
            FROM candidaturas
            WHERE {cuenta} AND {es_cand}
            GROUP BY canal""".format(resp=SQL_RESPUESTA, cuenta=SQL_CUENTA,
                                     es_cand=SQL_ES_CANDIDATURA)).fetchall()

    salida = {}
    for f in filas:
        n, r = f["enviadas"], f["respuestas"] or 0
        salida[f["canal"]] = {
            "enviadas": n, "respuestas": r,
            "tasa": round(100 * r / n, 1) if n else None,
            "tasa_suave": round(100 * (r + 1) / (n + 2), 1),
            # Con menos de diez casos cualquier conclusion es una anecdota.
            "fiable": n >= 10,
        }
    return salida


def _capacidad_correo() -> int:
    """A cuantas empresas se puede escribir HOY con una direccion verificada.

    Un correo inferido por patron no cuenta: no es una direccion, es una
    conjetura, y puede rebotar.
    """
    with conexion() as con:
        return con.execute("""
            SELECT COUNT(*) FROM contactos
            WHERE confianza = 'verificado'
              AND correo IS NOT NULL AND TRIM(correo) <> ''
              AND id NOT IN (SELECT contacto_id FROM candidaturas
                             WHERE contacto_id IS NOT NULL
                               AND estado <> 'descartada')
            """).fetchone()[0]


def _reparto(tamano: int) -> dict:
    """Cuantas plazas de la cola de hoy van a cada canal.

    Dos reglas, y la segunda importa tanto como la primera:

      1. **Explotar**: el canal que contesta se lleva las plazas, en
         proporcion a su tasa suavizada.
      2. **Explorar**: el otro canal conserva SIEMPRE al menos una. Sin esa
         plaza el sistema deja de medirlo, la tasa se congela y la decision de
         hoy queda grabada para siempre. Una plaza al dia es barato; quedarse
         ciego, no.
    """
    r = rendimiento()
    correo = r.get("correo", {}).get("tasa_suave", 50.0)
    portal = r.get("portal", {}).get("tasa_suave", 50.0)
    total = correo + portal or 1

    n_correo = max(1, round(tamano * correo / total))
    n_portal = max(1, tamano - n_correo)
    # El redondeo puede pasarse; manda el tamano pedido.
    while n_correo + n_portal > tamano and n_correo > 1:
        n_correo -= 1

    # El tope de realidad: una plaza de correo sin direccion verificada no
    # produce una candidatura, produce un borrador sin destinatario.
    cap = _capacidad_correo()
    razon = f"correo {correo}% vs portal {portal}% (tasas suavizadas)"
    if n_correo > cap:
        razon += f"; correo recortado a {cap} por contactos verificados"
        n_correo = cap

    return {"correo": n_correo, "portal": max(0, tamano - n_correo),
            "capacidad_correo": cap, "razon": razon}


def _viable(alias: str = "") -> str:
    """El criterio de viabilidad, traido de `postular.py`, con su alias.

    No se copia: se importa. Tener dos definiciones de "esta vacante sirve"
    fue lo que hizo que la cola propusiera vacantes de dos anios de
    experiencia mientras el ranking de postulacion las descartaba.
    """
    import re

    import postular
    sql = postular.SQL_VIABLE
    if alias:
        # Las columnas van sin prefijo en la constante; aqui se les pone el
        # del JOIN. Se hace por nombre exacto para no tocar los literales.
        for col in ("ver_estado", "aplicada", "descartada_motivo", "elegible_mx",
                    "anios_exigidos", "req_educacion", "ubicacion_ficha",
                    "req_espacio", "modalidad", "ubicacion"):
            sql = re.sub(rf"(?<![\w.]){col}\b", f"{alias}.{col}", sql)
    return f"({sql})"


def elegir(tamano: int = TAMANO) -> list[dict]:
    """Elige la cola de hoy: dos por vacante publicada y una en frio."""
    bloqueadas = _empresas_bloqueadas()
    postuladas = _ya_postuladas()
    import empresas as mod_emp

    # --- Via 1: vacantes abiertas que encajan -----------------------------
    with conexion() as con:
        filas = con.execute("""
            SELECT v.*, e.id AS empresa_id, e.nombre_limpio, e.score AS score_empresa
            FROM vacantes v
            LEFT JOIN empresas e ON e.nombre = v.empresa
            WHERE v.score >= 55 AND v.elegible_mx = 1 AND v.area != 'fuera'
              AND (v.nivel IS NULL OR v.nivel != 'excluido')
              AND (v.ver_estado IS NULL OR v.ver_estado != 'cerrada')
              AND (v.riesgo_fantasma IS NULL OR v.riesgo_fantasma < 55)
              AND """ + _viable("v") + """
            ORDER BY v.score DESC LIMIT 400""").fetchall()

    import postular

    prioritarias = set(postular.areas_suyas())
    candidatas = []
    for f in filas:
        v = dict(f)
        if v["id"] in postuladas or (v.get("empresa_id") in bloqueadas and v.get("empresa_id")):
            continue

        # El carril: las areas prioritarias activas (ver `areas.py`). Una
        # vacante legitima de otra area gasta una plaza de la cola en algo que
        # no construye el perfil que se persigue.
        if v.get("area") not in prioritarias:
            continue

        # Y las reglas que solo se ven leyendo el anuncio: autorizacion para
        # trabajar en EEUU, matricula en universidad alemana, semestre exigido,
        # practicas no remuneradas. El SQL no puede con esto; `evaluar()` si.
        # Sin este paso la cola proponia un "Werkstudent" de Leipzig, que exige
        # estar matriculado en Alemania.
        bloqueos = postular.evaluar(
            f"{v.get('titulo') or ''} {v.get('descripcion') or ''}",
            v.get("ubicacion") or "")
        if bloqueos:
            continue
        bonus, motivo_fecha = _frescura(v.get("publicado"))
        v["prioridad"] = round((v.get("score") or 0) + bonus, 1)
        v["motivo_cola"] = [f"encaja contigo: {v.get('score')}/100", motivo_fecha]
        if v.get("score_empresa"):
            v["motivo_cola"].append(
                f"{v.get('nombre_limpio') or v['empresa']} es un objetivo fuerte "
                f"({round(v['score_empresa'])}/100 como empresa)")
        v["via"] = "portal"
        candidatas.append(v)

    candidatas.sort(key=lambda x: -x["prioridad"])

    # Una sola por empresa dentro de la misma cola: repetirse el mismo dia es peor.
    cola, empresas_en_cola = [], set()
    for v in candidatas:
        clave = v.get("empresa_id") or v.get("empresa")
        if clave in empresas_en_cola:
            continue
        empresas_en_cola.add(clave)
        cola.append(v)
        if len(cola) >= tamano - 1:
            break

    # Si de esa empresa ya se investigo a alguien, el correo del portal se
    # dirige a esa persona por su nombre en vez de al equipo. No se busca a
    # nadie nuevo aqui: solo se aprovecha lo que ya esta verificado en la base.
    with conexion() as con:
        for v_ in cola:
            if not v_.get("empresa_id"):
                continue
            c = con.execute(
                # Primero TENER direccion, despues la confianza: ver cabecera.
                "SELECT * FROM contactos WHERE empresa_id=? ORDER BY "
                "  CASE WHEN correo IS NOT NULL AND TRIM(correo) <> '' THEN 0 ELSE 1 END, "
                "  CASE confianza WHEN 'rebotado' THEN 9 WHEN 'verificado' THEN 0 "
                "       WHEN 'inferido-por-patron' THEN 1 WHEN 'inferido' THEN 2 ELSE 3 END "
                "LIMIT 1", (v_["empresa_id"],)).fetchone()
            if c:
                v_["contacto"] = dict(c)

    # --- Via 2: una candidatura espontanea --------------------------------
    # El mercado oculto, con dos reglas que salieron de la investigacion:
    #
    #   1. NUNCA a una empresa con programa formal de becarios (Cemex,
    #      Deloitte, Scotiabank...): ahi el correo en frio no salta la fila y
    #      puede irritar a quien decide. Su via es el portal.
    #   2. Las empresas CON contacto investigado van primero, ordenadas por la
    #      confianza del dato: un contacto verificado en una empresa de 74
    #      puntos vale mas que ninguno en una de 100 — al segundo no hay a
    #      quien escribirle.
    candidatos_frio = []
    for e in mod_emp.objetivos(40):
        if (e["id"] in bloqueadas or e["id"] in empresas_en_cola
                or e.get("via") == "programa-formal"):
            continue
        with conexion() as con:
            # Igual que con las vacantes: un borrador no bloquea, solo lo
            # enviado o descartado.
            ya = con.execute(
                "SELECT COUNT(*) c FROM candidaturas WHERE empresa_id=? "
                "AND via='correo-directo' AND estado != 'borrador'",
                (e["id"],)).fetchone()["c"]
            contacto = con.execute(
                # Primero TENER direccion, despues la confianza: ver cabecera.
                "SELECT * FROM contactos WHERE empresa_id=? ORDER BY "
                "  CASE WHEN correo IS NOT NULL AND TRIM(correo) <> '' THEN 0 ELSE 1 END, "
                "  CASE confianza WHEN 'rebotado' THEN 9 WHEN 'verificado' THEN 0 "
                "       WHEN 'inferido' THEN 1 ELSE 2 END "
                "LIMIT 1", (e["id"],)).fetchone()
        if ya:
            continue
        rango_confianza = {"verificado": 0, "inferido": 1}.get(
            (contacto["confianza"] if contacto else ""), 2)
        # Sin direccion cuenta casi como sin contacto: no hay correo que enviar.
        sin_correo = not (contacto and (contacto["correo"] or "").strip())
        candidatos_frio.append((contacto is None, sin_correo, rango_confianza,
                                -e["score"], e,
                                dict(contacto) if contacto else None))

    candidatos_frio.sort(key=lambda x: x[:4])

    # AQUI manda la evidencia, no una constante. Antes eran "dos por portal y
    # una en frio" escritas a mano; ahora el reparto sale de la tasa de
    # respuesta medida: si el correo contesta mucho mas que los portales, la
    # mezcla se invierte a dos correos y un portal.
    reparto = _reparto(tamano)
    cola = cola[:reparto["portal"]]

    for _, _, _, _, e, contacto in candidatos_frio[:reparto["correo"]]:
        cola.append({
            "id": None, "empresa_id": e["id"], "empresa": e["nombre_limpio"],
            "titulo": "(candidatura espontanea)", "via": "correo-directo",
            "prioridad": e["score"], "contacto": contacto,
            "motivo_cola": e["motivos"][:2] + [
                "sin vacante publicada: aqui compites contra casi nadie"
                if not e["vacantes_total"] else
                "escribir directo, ademas de postular por el portal"],
        })

    return cola[:tamano]


def registrar(elemento: dict, asunto: str = "", cuerpo: str = "") -> str:
    ident = _id(elemento.get("id") or "", elemento.get("empresa_id") or "",
                date.today().isoformat())
    ahora = ahora_iso()
    with conexion() as con:
        con.execute("""
            INSERT INTO candidaturas (id, vacante_id, empresa_id, contacto_id, via,
                                      asunto, cuerpo, estado, creada, actualizada)
            VALUES (?,?,?,?,?,?,?,'borrador',?,?)
            ON CONFLICT(id) DO UPDATE SET asunto=excluded.asunto,
                cuerpo=excluded.cuerpo, actualizada=excluded.actualizada""",
            (ident, elemento.get("id"), elemento.get("empresa_id"),
             (elemento.get("contacto") or {}).get("id"), elemento.get("via"),
             asunto, cuerpo, ahora, ahora))
    return ident


def marcar_enviada(ident: str) -> bool:
    with conexion() as con:
        cur = con.execute(
            "UPDATE candidaturas SET estado='pendiente-acuse', enviada=?, "
            "actualizada=? WHERE id=?",
            (date.today().isoformat(), ahora_iso(), ident))
        if cur.rowcount:
            fila = con.execute("SELECT vacante_id FROM candidaturas WHERE id=?",
                               (ident,)).fetchone()
            if fila and fila["vacante_id"]:
                con.execute("UPDATE vacantes SET aplicada=1 WHERE id=?",
                            (fila["vacante_id"],))
        return bool(cur.rowcount)


def situacion() -> dict:
    """El estado real de la busqueda. Es la cifra que importa, no cuantas
    vacantes hay en el panel.

    `enviadas` cuenta los intentos; `confirmadas` solo los que tienen prueba
    --un acuse de la bolsa o una respuesta humana--. La diferencia entre las
    dos es lo que el sistema CREE haber hecho menos lo que puede demostrar, y
    conviene mirarla.
    """
    with conexion() as con:
        f = con.execute("""
            SELECT COUNT(*) total,
                   SUM(CASE WHEN {cuenta} AND {es_cand} THEN 1 ELSE 0 END) enviadas,
                   SUM(CASE WHEN {cuenta} AND NOT {es_cand} THEN 1 ELSE 0 END) gestiones,
                   SUM(CASE WHEN estado='borrador' THEN 1 ELSE 0 END) borradores,
                   SUM(CASE WHEN {resp} AND {es_cand} THEN 1 ELSE 0 END) con_respuesta,
                   SUM(CASE WHEN estado='entrevista' THEN 1 ELSE 0 END) entrevistas,
                   SUM(CASE WHEN estado='rebote' THEN 1 ELSE 0 END) rebotes,
                   SUM(CASE WHEN estado='pendiente-acuse' THEN 1 ELSE 0 END) sin_confirmar,
                   SUM(CASE WHEN {cuenta} AND {es_cand} AND estado <> 'pendiente-acuse'
                            THEN 1 ELSE 0 END) confirmadas
            FROM candidaturas""".format(cuenta=SQL_CUENTA, resp=SQL_RESPUESTA,
                                     es_cand=SQL_ES_CANDIDATURA)).fetchone()
        por_via = {r["via"]: r["n"] for r in con.execute(
            "SELECT via, COUNT(*) n FROM candidaturas WHERE " + SQL_CUENTA
            + " GROUP BY via")}
    d = dict(f)
    d["por_via"] = por_via
    enviadas = d.get("enviadas") or 0
    d["tasa_respuesta"] = (round(100 * (d.get("con_respuesta") or 0) / enviadas, 1)
                           if enviadas else None)
    return d


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--preparar", action="store_true", help="escribe los correos")
    p.add_argument("--enviada", help="marca una candidatura como enviada")
    args = p.parse_args()

    if args.enviada:
        print("marcada como enviada" if marcar_enviada(args.enviada) else "no encontrada")
        raise SystemExit(0)

    s = situacion()
    print(f"SITUACION: {s['enviadas'] or 0} candidaturas enviadas, "
          f"{s['con_respuesta'] or 0} con respuesta"
          + (f" ({s['tasa_respuesta']}%)" if s["tasa_respuesta"] is not None else ""))
    print()
    print("=" * 70)
    print(f"TU COLA DE HOY — {date.today().isoformat()}")
    print("=" * 70)

    for i, e in enumerate(elegir(), 1):
        via = "POSTULAR POR EL PORTAL" if e["via"] == "portal" else "ESCRIBIR EN FRIO"
        print(f"\n{i}. [{via}]  {e['titulo'][:52]}")
        print(f"   {e['empresa']}")
        for m in e["motivo_cola"]:
            print(f"     - {m}")
        if e.get("contacto"):
            c = e["contacto"]
            print(f"     -> escribir a: {c.get('nombre')} ({c.get('puesto')}) "
                  f"[{c.get('confianza')}]")
        if e.get("url"):
            print(f"   {e['url'][:88]}")
        if args.preparar:
            try:
                # Cada via con su generador: al portal se le responde con la
                # carta de postulacion; a una persona se le escribe en frio,
                # que es otro genero por completo (corto, un solo pedido).
                if e["via"] == "portal":
                    import generador_correos
                    correo = generador_correos.generar(e, contacto=e.get("contacto"))
                elif e.get("contacto"):
                    import correos_frios
                    from almacen import conexion as _cx
                    with _cx() as _c:
                        emp = _c.execute("SELECT * FROM empresas WHERE id=?",
                                         (e["empresa_id"],)).fetchone()
                    correo = correos_frios.generar_frio(dict(emp), e["contacto"])
                else:
                    correo = None
                    print("   [sin contacto investigado: buscarlo antes de escribir]")
                if correo:
                    ident = registrar(e, correo.get("asunto", ""), correo.get("cuerpo", ""))
                    print(f"\n   --- CORREO PREPARADO ({ident}) ---")
                    print(f"   Asunto: {correo.get('asunto','')}")
                    print("   " + (correo.get("cuerpo", "")[:500]).replace("\n", "\n   "))
                    for a in correo.get("avisos", []):
                        aviso = a if isinstance(a, str) else str(a)
                        print(f"   !! {aviso[:110]}")
            except Exception as ex:
                print(f"   [no se pudo preparar el correo: {ex}]")
