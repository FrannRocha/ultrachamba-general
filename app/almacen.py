"""
Almacén persistente en SQLite: la memoria de la excavadora.

Por qué existe. Hasta ahora cada corrida reescribía `vacantes.json` entera.
Eso tiene tres problemas que solo se notan con el tiempo:

  1. Lo que desaparecía de las fuentes se perdía sin dejar rastro, así que era
     imposible saber si una vacante se cerró o si simplemente el scraper falló.
  2. No había forma de responder "¿qué salió nuevo desde ayer?", que es la
     pregunta que de verdad importa cuando revisas todos los días.
  3. Marcar una vacante como aplicada vivía solo en el navegador; si cambiabas
     de equipo, se perdía.

Con una tabla de vacantes y otra de avistamientos por corrida, las tres se
responden solas: primera_vez, ultima_vez y veces salen del historial.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

BD = Path(__file__).resolve().parent / "datos" / "ultrachamba.db"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS vacantes (
    id            TEXT PRIMARY KEY,
    titulo        TEXT NOT NULL,
    empresa       TEXT,
    url           TEXT,
    fuente        TEXT,
    ats           TEXT,
    ubicacion     TEXT,
    descripcion   TEXT,
    publicado     TEXT,
    salario       TEXT,
    extra         TEXT,
    -- historial
    primera_vez   TEXT,
    ultima_vez    TEXT,
    veces         INTEGER DEFAULT 0,
    -- analisis
    nivel         TEXT,
    area          TEXT,
    modalidad     TEXT,
    elegible_mx   INTEGER,
    requiere_mudanza INTEGER,
    anios_exigidos   INTEGER,
    evidencia_experiencia TEXT,
    score         REAL,
    veredicto     TEXT,
    motivos       TEXT,
    habilidades   TEXT,
    -- verificacion
    ver_estado    TEXT,
    ver_metodo    TEXT,
    ver_detalle   TEXT,
    ver_fecha     TEXT,
    ver_http      INTEGER,
    -- seguimiento del usuario (sobrevive a cualquier recoleccion)
    aplicada      INTEGER DEFAULT 0,
    fecha_aplicada TEXT,
    notas         TEXT
);
CREATE INDEX IF NOT EXISTS idx_score   ON vacantes(score DESC);
CREATE INDEX IF NOT EXISTS idx_ver     ON vacantes(veredicto);
CREATE INDEX IF NOT EXISTS idx_ultima  ON vacantes(ultima_vez);
CREATE INDEX IF NOT EXISTS idx_empresa ON vacantes(empresa);

CREATE TABLE IF NOT EXISTS corridas (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    inicio  TEXT,
    fin     TEXT,
    crudas  INTEGER,
    unicas  INTEGER,
    guardadas INTEGER,
    nuevas  INTEGER,
    notas   TEXT
);

CREATE TABLE IF NOT EXISTS avistamientos (
    vacante_id TEXT,
    corrida_id INTEGER,
    PRIMARY KEY (vacante_id, corrida_id)
);

-- Empresas objetivo. El giro de enfoque: durante semanas el sistema conto
-- VACANTES, y resulto que las dos "empresas" con mas anuncios en la zona base
-- eran "Recomendada" (67) y "Importante empresa del sector" (49) — anuncios que
-- ni siquiera dicen quien contrata. Contra eso no se puede escribir a nadie.
--
-- La unidad que importa no es la vacante, es la EMPRESA: una empresa con
-- operacion real del area en la zona base sigue siendo un objetivo aunque hoy
-- no publique nada, porque la mayoria de las practicas se dan sin anuncio.
-- (`en_monterrey` guarda "tiene operacion en la zona base"; el nombre de la
-- columna es de origen y se conserva para no romper bases existentes.)
CREATE TABLE IF NOT EXISTS empresas (
    id             TEXT PRIMARY KEY,
    nombre         TEXT NOT NULL,
    nombre_limpio  TEXT,
    dominio        TEXT,
    sitio          TEXT,
    linkedin       TEXT,
    sector         TEXT,
    tamano         TEXT,
    en_monterrey   INTEGER DEFAULT 0,
    -- Lo que se deduce de sus propias vacantes
    vacantes_total INTEGER DEFAULT 0,
    vacantes_ciber INTEGER DEFAULT 0,
    vacantes_ia    INTEGER DEFAULT 0,
    vacantes_prac  INTEGER DEFAULT 0,
    stack          TEXT,          -- herramientas que nombran sus anuncios
    -- Estrategia
    score          REAL,          -- que tan buen objetivo es
    motivos        TEXT,
    via            TEXT,          -- vacante-publicada | espontanea
    anonima        INTEGER DEFAULT 0,
    ats            TEXT,
    notas          TEXT,
    estado         TEXT,          -- sin-contactar | investigando | contactada | respondio | descartada
    primera_vez    TEXT,
    ultima_vez     TEXT
);

-- Personas a quien escribir. SOLO informacion profesional publicada: nombre,
-- puesto y empresa, de perfiles publicos o del sitio de la compañia.
--
-- Lo que NO se hace aqui, y no es negociable: nada de herramientas de OSINT
-- de brechas de datos, nada de datos personales, nada de correos personales.
-- Usar eso para escribirle a una reclutadora seria un problema legal bajo la
-- LFPDPPP y la peor carta de presentacion posible para alguien que quiere que
-- lo contraten en seguridad.
--
-- `confianza` distingue lo comprobado de lo deducido: un correo inferido por
-- patron corporativo NO es un correo verificado, y presentarlo como tal haria
-- que se escriba a una direccion inexistente creyendo que se acerto.
CREATE TABLE IF NOT EXISTS contactos (
    id            TEXT PRIMARY KEY,
    empresa_id    TEXT,
    nombre        TEXT,
    puesto        TEXT,
    perfil_url    TEXT,          -- perfil profesional publico
    correo        TEXT,
    correo_origen TEXT,          -- publicado | inferido-por-patron
    confianza     TEXT,          -- verificado | probable | inferido
    fuente        TEXT,
    notas         TEXT,
    primera_vez   TEXT,
    FOREIGN KEY (empresa_id) REFERENCES empresas(id)
);

-- Candidaturas: el estado real de la busqueda, no el catalogo.
--
-- El dato que obligo a crear esto: 2.681 vacantes recomendadas y 0 postuladas.
-- Una lista, por buena que sea, no produce candidaturas; produce la sensacion
-- de estar avanzando. Aqui se registra lo que de verdad pasa despues: que se
-- mando, a quien, cuando, y si contestaron.
--
-- Sirve para dos cosas que ninguna lista puede dar:
--   1. Saber a que NO hay que volver a postular (y no repetirse ante la misma
--      empresa, que queda fatal).
--   2. Medir que funciona. Sin esto, "manda mas correos" es un consejo a
--      ciegas; con esto se sabe si contestan mas las cartas en frio o las
--      postulaciones por el portal.
CREATE TABLE IF NOT EXISTS candidaturas (
    id            TEXT PRIMARY KEY,
    vacante_id    TEXT,          -- NULL si es candidatura espontanea
    empresa_id    TEXT,
    contacto_id   TEXT,
    via           TEXT,          -- portal | correo-directo | linkedin | referido | telefono
    asunto        TEXT,
    cuerpo        TEXT,
    estado        TEXT,          -- propuesta | borrador | aprobada | enviada | acuse
                                 -- | entrevista | oferta | rechazo | silencio
                                 -- | pendiente-accion (proceso vivo que espera un gesto: ver `pendiente`)
                                 --
                                 -- 'aprobada' se anadio el 27-ago-2026 con el modo movil:
                                 -- significa "la persona dijo que si, todavia no ha salido".
                                 -- Existe porque aprobar y ejecutar ocurren en sitios
                                 -- distintos --el telefono y la maquina de casa-- y sin un
                                 -- estado para el intervalo, un si desde la calle no tendria
                                 -- donde vivir hasta que el ordenador despertara.
    enviada       TEXT,
    respondida    TEXT,
    dias_silencio INTEGER,
    resultado     TEXT,
    notas         TEXT,
    creada        TEXT,
    actualizada   TEXT
);

-- Formacion gratuita. Vive aqui y no en un JSON aparte porque el sistema ya
-- aprendio, a base de fallos, que dos fuentes de verdad divergen: el panel, la
-- boveda y el corpus deben leer todos el mismo sitio.
--
-- `gratis` no es un si/no: hay tres realidades distintas y confundirlas es el
-- error mas caro para alguien que no puede pagar.
--   'total'        -> curso y credencial, ambos sin coste
--   'examen-pago'  -> el material es gratis, el examen se paga (se guarda cuanto)
--   'beca'         -> gratis solo si le aprueban una beca o convocatoria
CREATE TABLE IF NOT EXISTS cursos (
    id             TEXT PRIMARY KEY,
    nombre         TEXT NOT NULL,
    institucion    TEXT,
    url            TEXT,
    area           TEXT,          -- ciberseguridad | ia | nube | redes | general
    modalidad      TEXT,          -- linea | presencial-mty | hibrido
    gratis         TEXT,          -- total | examen-pago | beca
    costo_examen   TEXT,
    credencial     TEXT,          -- que papel te llevas, o NULL
    convocatoria   TEXT,          -- abierta | cerrada | permanente
    cierra         TEXT,          -- fecha ISO, si tiene plazo
    duracion       TEXT,
    idioma         TEXT,
    descripcion    TEXT,
    por_que        TEXT,          -- para que le sirve, en una linea
    score          REAL,
    motivos        TEXT,
    brecha         TEXT,          -- que hueco del CV cierra
    ver_estado     TEXT,          -- viva | cerrada | inaccesible | sin-verificar
    ver_http       INTEGER,
    ver_fecha      TEXT,
    ver_detalle    TEXT,
    primera_vez    TEXT,
    ultima_vez     TEXT
);

-- INSCRIPCIONES: el embudo de salida del carril de formacion.
--
-- Por que existe, y por que no bastaba con la tabla `cursos`. Esa tabla dice
-- QUE hay disponible; esta dice QUE SE HIZO. Es la misma leccion que
-- costo el giro de todo el proyecto: el sistema llego a recomendar 2.681
-- vacantes con cero postulaciones porque medir la entrada no mide nada. Un
-- catalogo de 26 cursos con cero inscripciones es exactamente el mismo error
-- con otro nombre.
--
-- LA METRICA DE ESTE CARRIL son las inscripciones ENVIADAS, y se cuenta con
-- LISTA BLANCA (ver estados de abajo). La cicatriz 26 del traspaso: con lista
-- negra, `NOT IN ('borrador','descartada')`, el dia que se anadio el estado
-- `aprobada` la metrica empezo a contar como enviadas cosas que no habian
-- salido. Olvidarse de un estado en una lista blanca ESCONDE algo real --
-- visible y molesto-- en vez de inventarse diez.
CREATE TABLE IF NOT EXISTS inscripciones (
    id             TEXT PRIMARY KEY,
    curso_id       TEXT NOT NULL,
    -- borrador  -> preparada, esperando su si
    -- aprobada  -> dijo que si, todavia no ha salido (la separacion de
    --              `aprobaciones.py`: aprobar desde el movil, ejecutar en casa)
    -- inscrita  -> el registro se mando. CUENTA para la metrica
    -- admitido / rechazado / completado -> lo que paso despues
    -- descartada -> decidio que no, con motivo
    estado         TEXT NOT NULL DEFAULT 'borrador',
    via            TEXT,          -- formulario | correo | presencial | plataforma
    url_registro   TEXT,
    nota           TEXT,          -- que hizo falta, en una linea
    motivo         TEXT,          -- por que se descarto, si se descarto
    evidencia      TEXT,          -- acuse, folio, hilo de Gmail
    hilo_gmail     TEXT,          -- ancla al hilo, si el registro fue por correo
    creada         TEXT,
    aprobada_fecha TEXT,
    enviada        TEXT,          -- cuando salio de verdad
    actualizada    TEXT
);

-- SEMILLAS: las paginas donde se publican convocatorias que vuelven cada ano.
--
-- Por que se vigila la PAGINA y no se rastrea un catalogo. Los cursos no
-- tienen API ni bolsa que consultar (lo dice `datos_cursos.py`), pero si
-- tienen algo que las vacantes no: se publican SIEMPRE en el mismo sitio.
-- MEXIA, Samsung, el CPFIA anuncian su siguiente convocatoria en la misma URL
-- del ano pasado. Guardando la huella del contenido, un cambio en esa pagina
-- es la senal mas barata que existe de "abrio algo".
--
-- Y responde a la cicatriz 13: un catalogo congelado no avisa. Aqui
-- `ultima_vez` y `ultimo_cambio` son visibles, asi que un vigilante que dejo
-- de mirar se ve, en vez de parecer que "no hay nada nuevo".
CREATE TABLE IF NOT EXISTS semillas (
    id             TEXT PRIMARY KEY,
    nombre         TEXT,
    url            TEXT,
    institucion    TEXT,
    huella         TEXT,          -- hash del contenido relevante
    estado         TEXT,          -- viva | inaccesible | rota
    http           INTEGER,
    detalle        TEXT,
    ultimo_cambio  TEXT,          -- cuando cambio el contenido por ultima vez
    cambios        INTEGER DEFAULT 0,
    primera_vez    TEXT,
    ultima_vez     TEXT
);
"""

CAMPOS = [
    "id", "titulo", "empresa", "url", "fuente", "ats", "ubicacion",
    "descripcion", "publicado", "salario", "extra",
    "nivel", "area", "modalidad", "elegible_mx", "requiere_mudanza",
    "anios_exigidos", "evidencia_experiencia", "score", "veredicto",
    "motivos", "habilidades",
    "ver_estado", "ver_metodo", "ver_detalle", "ver_fecha", "ver_http",
]


# Columnas que se añadieron DESPUES de que la base ya existiera en disco.
# `CREATE TABLE IF NOT EXISTS` no toca una tabla que ya esta creada, asi que
# ampliar el ESQUEMA de arriba no basta: una base en uso puede llevar meses
# viva y hay que alterarla en su sitio. Es idempotente a proposito -- se
# ejecuta en CADA apertura y no debe hacer nada cuando ya esta al dia.
AMPLIACIONES = {
    "candidaturas": {
        # El ancla del seguimiento. Se guarda el HILO y no el asunto porque
        # el asunto lo puede cambiar quien contesta ("Re:", "RV:", o
        # reescribirlo entero) y entonces se pierde el rastro en silencio.
        # El hilo de Gmail sobrevive a todo eso.
        "hilo_gmail": "TEXT",
        "mensaje_gmail": "TEXT",     # ultimo mensaje NUESTRO en ese hilo
        "ultimo_visto": "TEXT",      # cuando se reviso por ultima vez

        # 'candidatura' = pedir un puesto. 'gestion' = correspondencia dentro
        # de un proceso YA abierto (reagendar un examen, preguntar por una
        # asignacion). Sin esta distincion las gestiones inflaban la tasa de
        # respuesta del correo hasta el 50% y le robaban las plazas diarias al
        # unico canal que habia entregado algo. Ver el 24-ago-2026.
        "tipo": "TEXT",

        # EL HUECO DE LOS PROCESOS QUE NO PASAN POR GMAIL.
        #
        # Una respuesta puede llegar por TELEFONO: una empresa llama para
        # citar a un examen o a una entrevista. `procesos-en-marcha` se
        # construia con `WHERE hilo_gmail IS NOT NULL`, asi que un proceso
        # que entra por telefono no existia: no es que saliera mal, es que
        # no cabia. El panel seguia diciendo "Con respuesta: 0" el mismo dia
        # en que una candidatura avanzo por primera vez mas alla de `enviada`.
        # Y antes de dar por hecho de donde vino una respuesta, se pregunta:
        # que algo encaje no lo convierte en un dato.
        #
        # `via` ya dice por donde SALIO la candidatura (portal-occ). Estas
        # columnas dicen por donde ENTRO la respuesta y que espera ahora, que
        # son cosas distintas: una candidatura puede salir por el portal de
        # OCC y recibir la respuesta por telefono.
        "canal_respuesta": "TEXT",   # correo | telefono | portal | presencial
        "pendiente": "TEXT",         # que espera AHORA este proceso, en una linea
        "pendiente_fecha": "TEXT",   # cuando toca (ISO). NULL = sin fecha
    },
    "vacantes": {
        # Por que no basta con `ver_estado`. Esa columna responde "¿sigue viva
        # la oferta?"; esta responde "¿nos sirve?". Son cosas distintas: una
        # vacante puede estar perfectamente viva y ser inservible, porque el
        # clasificador la puso en Nuevo Leon cuando el anuncio decia Ciudad de
        # Mexico y presencial.
        #
        # Se rellena al abrir la oferta en el navegador, que es cuando se ve
        # lo que el pipeline no vio. Sin esta columna, la misma vacante mala
        # vuelve a salir la primera cada vez que se pide la siguiente.
        "descartada_motivo": "TEXT",
        "descartada_fecha": "TEXT",

        # Campos que la bolsa publica YA ESTRUCTURADOS en la ficha y que el
        # colector tiraba: leia solo la tarjeta del listado. Son justo los que
        # decidieron los descartes del 24-ago-2026 --"Universitario titulado"
        # echo abajo tres vacantes, "Presencial" otras cuatro-- y tenerlos en
        # columnas los vuelve filtrables por SQL, sin abrir el navegador.
        "req_educacion": "TEXT",     # p.ej. "Universitario sin titulo"
        "req_contratacion": "TEXT",  # tiempo completo | medio tiempo
        "req_horario": "TEXT",       # jornada completa | tiempo parcial
        "req_espacio": "TEXT",       # presencial | remoto | hibrido
        "ubicacion_ficha": "TEXT",   # la que dice la FICHA, no la tarjeta
        "detalle_fecha": "TEXT",
        # Cuantas veces se intento leer la ficha sin sacar ni un campo.
        # Sella a los 3. Ver el fallo de las 257 selladas en vacio.
        "detalle_intentos": "INTEGER",

        # Riesgo de vacante fantasma (`fantasma.py`). Se declaran AQUI y no
        # solo en el ALTER de `fantasma.py`, que solo corre si ese modulo se
        # ejecuta: el panel y la cola las consultan SIEMPRE, y con una base
        # recien creada el servidor moria al arrancar con "no such column".
        "riesgo_fantasma": "INTEGER",
        "motivos_fantasma": "TEXT",
    },
    "cursos": {
        # EL HUECO DEL 4-sep-2026: la tabla sabia lo que un curso ENSENA y lo
        # que CUESTA, pero no a QUIEN admite. Y eso es lo primero que decide si
        # un estudiante puede entrar. `datos_cursos.py` ya guardaba el
        # aprendizaje en su cabecera, en prosa, fuera de toda consulta:
        # "Jovenes Construyendo el Futuro: exige NO estudiar." Un requisito de
        # elegibilidad escrito en un comentario no filtra nada; en una
        # columna, si.
        "publico": "TEXT",        # estudiantes | egresados | profesionales | abierto
        "carreras": "TEXT",       # carreras afines que admite, literal del anuncio
        "requisitos": "TEXT",     # lo que exige, tal cual lo dice la convocatoria
        "sede": "TEXT",           # ciudad/pais si es presencial (NULL = en linea)
        # Ternario a proposito, como `elegible_mx` en vacantes: 1 cabe, 0 no
        # cabe, NULL **no se sabe todavia**. Un 0 por defecto seria inventarse
        # un descarte, y este proyecto ya perdio la convocatoria de MEXIA por
        # un filtro que tiraba cosas buenas en silencio (cicatriz 29).
        "elegible": "INTEGER",
        "elegible_motivo": "TEXT",
        # De donde salio: 'curado' (escrito a mano y comprobado en
        # `datos_cursos.py`) o 'semilla:<id>' (lo encontro el vigilante). No se
        # mezclan: lo recolectado entra como `candidato` y no se publica hasta
        # que alguien lo acepta.
        "origen": "TEXT",
        "estado_revision": "TEXT",   # candidato | aceptado | descartado
        "descartado_motivo": "TEXT",
    },
    "empresas": {
        # El identificador de su bolsa de trabajo propia.  ya decia la
        # plataforma (greenhouse, lever...), pero sin el token no se puede
        # consultar: son cosas distintas y faltaba la segunda.
        "ats_token": "TEXT",
        "ats_probado": "TEXT",   # cuando se busco, haya salido o no
    },
}


def _ampliar(con) -> None:
    for tabla, columnas in AMPLIACIONES.items():
        try:
            hay = {r["name"] for r in con.execute(f"PRAGMA table_info({tabla})")}
        except sqlite3.Error:
            continue
        if not hay:            # la tabla aun no existe: el ESQUEMA ya la creara
            continue
        for nombre, tipo in columnas.items():
            if nombre not in hay:
                con.execute(f"ALTER TABLE {tabla} ADD COLUMN {nombre} {tipo}")


@contextmanager
def conexion():
    BD.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(BD)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(ESQUEMA)
        _ampliar(con)
        yield con
        con.commit()
    finally:
        con.close()


def _fila(v: dict) -> tuple:
    ver = v.get("verificacion") or {}
    return (
        v.get("id"), v.get("titulo"), v.get("empresa"), v.get("url"),
        v.get("fuente"), v.get("ats"), v.get("ubicacion"),
        (v.get("descripcion") or "")[:8000], v.get("publicado"), v.get("salario"),
        json.dumps(v.get("extra") or {}, ensure_ascii=False),
        v.get("nivel"), v.get("area"), v.get("modalidad"),
        int(bool(v.get("elegible_mx"))), int(bool(v.get("requiere_mudanza"))),
        v.get("anios_exigidos"), v.get("evidencia_experiencia"),
        v.get("score"), v.get("veredicto"),
        json.dumps(v.get("motivos") or [], ensure_ascii=False),
        json.dumps(v.get("habilidades_coincidentes") or [], ensure_ascii=False),
        ver.get("estado"), ver.get("metodo"), ver.get("detalle"),
        ver.get("fecha"), ver.get("http"),
    )


def abrir_corrida(notas: str = "") -> int:
    from nucleo import ahora_iso
    with conexion() as con:
        cur = con.execute(
            "INSERT INTO corridas (inicio, notas) VALUES (?, ?)", (ahora_iso(), notas)
        )
        return cur.lastrowid


def guardar(vacantes: list[dict], corrida_id: int) -> dict:
    """Inserta o actualiza, preservando historial y el seguimiento del usuario."""
    from nucleo import ahora_iso
    ahora = ahora_iso()
    nuevas = 0

    with conexion() as con:
        existentes = {r["id"] for r in con.execute("SELECT id FROM vacantes")}
        for v in vacantes:
            es_nueva = v["id"] not in existentes
            nuevas += es_nueva
            marcadores = ",".join("?" * len(CAMPOS))
            # Las columnas de verificacion NO se pisan con lo que venga: se
            # conservan si el dict entrante no trae nada. Un reanalisis
            # (clasificar de nuevo lo ya guardado) no verifica nada, y su dict
            # no lleva la clave 'verificacion'; sin este COALESCE, ese UPDATE
            # ponia a NULL el estado de las 2.997 filas y se perdio entera la
            # verificacion del sistema, en silencio. Solo un dato de
            # verificacion real puede sustituir a otro.
            actualiza = ",".join(
                f"{c}=COALESCE(excluded.{c}, vacantes.{c})" if c.startswith("ver_")
                else f"{c}=excluded.{c}"
                for c in CAMPOS if c != "id")
            con.execute(
                f"""
                INSERT INTO vacantes ({",".join(CAMPOS)}, primera_vez, ultima_vez, veces)
                VALUES ({marcadores}, ?, ?, 1)
                ON CONFLICT(id) DO UPDATE SET
                    {actualiza},
                    ultima_vez = excluded.ultima_vez,
                    veces = vacantes.veces + 1
                """,
                _fila(v) + (ahora, ahora),
            )
            con.execute(
                "INSERT OR IGNORE INTO avistamientos (vacante_id, corrida_id) VALUES (?,?)",
                (v["id"], corrida_id),
            )
        con.execute(
            "UPDATE corridas SET fin=?, guardadas=?, nuevas=? WHERE id=?",
            (ahora, len(vacantes), nuevas, corrida_id),
        )
    return {"guardadas": len(vacantes), "nuevas": nuevas}


def nuevas_de_la_corrida(corrida_id: int) -> list[dict]:
    """Las que se vieron por primera vez en esta corrida."""
    with conexion() as con:
        filas = con.execute(
            """
            SELECT v.* FROM vacantes v
            JOIN avistamientos a ON a.vacante_id = v.id
            WHERE a.corrida_id = ? AND v.veces = 1
            ORDER BY v.score DESC
            """,
            (corrida_id,),
        ).fetchall()
    return [dict(f) for f in filas]


def desaparecidas(corrida_id: int) -> list[dict]:
    """Estaban en la corrida anterior y ya no aparecen: candidatas a cerradas."""
    with conexion() as con:
        previa = con.execute(
            "SELECT id FROM corridas WHERE id < ? ORDER BY id DESC LIMIT 1", (corrida_id,)
        ).fetchone()
        if not previa:
            return []
        filas = con.execute(
            """
            SELECT v.* FROM vacantes v
            JOIN avistamientos a ON a.vacante_id = v.id AND a.corrida_id = ?
            WHERE v.id NOT IN (SELECT vacante_id FROM avistamientos WHERE corrida_id = ?)
            ORDER BY v.score DESC
            """,
            (previa["id"], corrida_id),
        ).fetchall()
    return [dict(f) for f in filas]


def consultar(
    veredictos: list[str] | None = None,
    minimo: float = 40.0,
    solo_vivas: bool = True,
    limite: int = 5000,
) -> list[dict]:
    condiciones = ["score >= ?"]
    args: list = [minimo]
    if veredictos:
        condiciones.append(f"veredicto IN ({','.join('?' * len(veredictos))})")
        args += veredictos
    if solo_vivas:
        condiciones.append("(ver_estado IS NULL OR ver_estado != 'cerrada')")
    with conexion() as con:
        filas = con.execute(
            f"SELECT * FROM vacantes WHERE {' AND '.join(condiciones)} "
            f"ORDER BY score DESC LIMIT {int(limite)}",
            args,
        ).fetchall()
    return [_desde_fila(dict(f)) for f in filas]


def _desde_fila(f: dict) -> dict:
    """Devuelve el diccionario en el formato que ya usan dashboard y Obsidian."""
    f["motivos"] = json.loads(f.get("motivos") or "[]")
    f["habilidades_coincidentes"] = json.loads(f.get("habilidades") or "[]")
    f["extra"] = json.loads(f.get("extra") or "{}")
    f["elegible_mx"] = bool(f.get("elegible_mx"))
    f["requiere_mudanza"] = bool(f.get("requiere_mudanza"))
    f["verificacion"] = {
        "estado": f.pop("ver_estado", None),
        "metodo": f.pop("ver_metodo", None),
        "detalle": f.pop("ver_detalle", None),
        "fecha": f.pop("ver_fecha", None),
        "http": f.pop("ver_http", None),
    }
    return f


def marcar_aplicada(vacante_id: str, aplicada: bool = True, notas: str = "") -> None:
    from nucleo import ahora_iso
    with conexion() as con:
        con.execute(
            "UPDATE vacantes SET aplicada=?, fecha_aplicada=?, notas=? WHERE id=?",
            (int(aplicada), ahora_iso() if aplicada else None, notas, vacante_id),
        )


# --------------------------------------------------------------------------
# Las cifras del panel, en UN solo sitio.
#
# LA CICATRIZ (27-ago-2026, tercera vez). Cinco notas de la boveda publicaban
# "2.228 vacantes vivas" con fecha de HOY mientras la base decia 3.700 y otras
# notas del mismo dia decian 3.691. El motivo es siempre el mismo y es el
# primer aviso del CLAUDE.md: la cifra salia de `datos/estadisticas.json`, un
# DERIVADO, en vez de la base. Peor que estar desfasado: el JSON se reescribe
# en cada corrida, asi que la nota parecia fresca y mentia igual. Un agente que
# aterrizara en `sistema/panel-de-vacantes` se equivocaba en un 66%.
#
# Antes de esto el mismo WHERE estaba copiado en servidor.py (dos veces),
# salud.py y generar_todo.py. Copiar un filtro es fabricar la proxima
# divergencia: la unica forma de que dos numeros no discrepen es que salgan
# de la misma linea.
SQL_VIVAS_PANEL = (
    "(ver_estado IS NULL OR ver_estado != 'cerrada') "
    "AND (nivel IS NULL OR nivel != 'excluido') "
    "AND (area IS NULL OR area != 'fuera') AND score >= 40"
)

# `vacantes.json` filtra ADEMAS por `elegible_mx = 1`, y por eso exporta 9
# menos que las que ensena el panel (medido el 27-ago-2026: 3.691 contra
# 3.700). No es un fallo -- el JSON no quiere llevarse vacantes que no
# contratan desde Mexico -- pero la diferencia se declara aqui en vez de
# quedar escondida en otro WHERE copiado.
SQL_VIVAS_EXPORTABLES = SQL_VIVAS_PANEL + " AND elegible_mx = 1"


def cifras_panel() -> dict:
    """Lo que el panel ensena AHORA, contado contra la base.

    Es la unica fuente para cualquier nota, informe o cifra que se ensene a
    quien usa el sistema. Si un numero no sale de aqui o de una consulta hermana, es un
    numero de un derivado y no vale.
    """
    with conexion() as con:
        def n(donde: str) -> int:
            return con.execute(f"SELECT COUNT(*) FROM vacantes WHERE {donde}").fetchone()[0]

        d = {
            "panel": n(SQL_VIVAS_PANEL),
            "exportables": n(SQL_VIVAS_EXPORTABLES),
            "historicas": con.execute("SELECT COUNT(*) FROM vacantes").fetchone()[0],
            "aplicadas": n("aplicada = 1"),
            "cerradas": n("ver_estado = 'cerrada'"),
            "verificadas_vivas": n(SQL_VIVAS_PANEL + " AND ver_estado = 'viva'"),
            "sin_verificar": n(SQL_VIVAS_PANEL
                               + " AND (ver_estado IS NULL OR ver_estado = 'sin-verificar')"),
            # Sin fecha de publicacion no aplica la senal principal de
            # `fantasma.py`. Estaba escrito a mano en la boveda como "1.023 de
            # 2.228 (46%)" y a 27-ago-2026 la base decia 1.542 de 3.700 (42%).
            "sin_fecha": n(SQL_VIVAS_PANEL + " AND (publicado IS NULL OR publicado = '')"),

            # Vacantes ya descartadas a mano, con motivo escrito ("presencial
            # en otra ciudad", "pide experiencia", "el anuncio dice otra ciudad
            # y el clasificador la puso en la zona base"). Siguen en el
            # panel a proposito --puede querer reconsiderar alguna, y el motivo
            # esta ahi para juzgarlo-- pero NO estan en juego, asi que se
            # cuentan aparte. `postular.py` ya las excluye de la cola y del
            # ranking (lineas 126, 370 y 471): no le cuestan gestos a nadie.
            #
            # Esconderlas del panel seria la otra opcion y es peor: una vacante
            # descartada por un motivo que hoy ya no aplica --cambio de
            # semestre, cambio de ciudad-- deja de existir sin que nadie pueda
            # revisarla. Se cuenta el todo y se dice cuanto de ese todo esta
            # realmente en juego.
            "descartadas_a_mano": n(
                SQL_VIVAS_PANEL
                + " AND descartada_motivo IS NOT NULL AND descartada_motivo <> ''"),
            "en_juego": n(
                SQL_VIVAS_PANEL
                + " AND (descartada_motivo IS NULL OR descartada_motivo = '')"),
        }
        d["pct_sin_fecha"] = (round(100 * d["sin_fecha"] / d["panel"])
                              if d["panel"] else 0)

        # LA METRICA vive aqui para que nadie tenga que decidir de donde la
        # saca. Llegaron a convivir tres numeros parecidos y una nota publicaba
        # el equivocado bajo el rotulo "Ya postuladas":
        #
        #   candidaturas enviadas              <- LA metrica: lo que se mando
        #   vacantes que alguna candidatura apunta
        #   vacantes con `aplicada = 1`
        #
        # El tercero no es ninguno de los dos que importan. Marca las DOS filas
        # de una misma vacante republicada con otro id de LinkedIn: correcto
        # para que el ranking no la vuelva a ofrecer, y equivocado como cuenta
        # de puertas tocadas. `aplicada` es una senal para el ranking, no una
        # metrica.
        #
        # La definicion no se copia: se importa de `cola`, que es donde vive.
        # El import va dentro de la funcion porque `cola` importa `almacen` al
        # cargarse y a nivel de modulo seria un ciclo.
        from cola import SQL_CUENTA, SQL_ES_CANDIDATURA
        d["candidaturas_enviadas"] = con.execute(
            f"SELECT COUNT(*) FROM candidaturas WHERE {SQL_CUENTA} "
            f"AND {SQL_ES_CANDIDATURA}").fetchone()[0]
        d["vacantes_con_candidatura"] = con.execute(
            f"SELECT COUNT(DISTINCT vacante_id) FROM candidaturas "
            f"WHERE {SQL_CUENTA} AND {SQL_ES_CANDIDATURA} "
            "AND vacante_id IS NOT NULL").fetchone()[0]
        d["por_veredicto"] = {r["veredicto"]: r["n"] for r in con.execute(
            f"SELECT veredicto, COUNT(*) n FROM vacantes WHERE {SQL_VIVAS_PANEL} "
            "GROUP BY veredicto ORDER BY n DESC")}
        # NULL y 'sin-verificar' son el mismo estado para quien lee, pero SQL
        # los agrupa por separado: hay que SUMARLOS, no meterlos en un dict
        # por comprension, que se pisan y tiran uno de los dos. Aqui eso
        # habria escondido 1.381 vacantes de las 1.709 sin verificar.
        ver: dict[str, int] = {}
        for r in con.execute(
                f"SELECT ver_estado, COUNT(*) n FROM vacantes WHERE {SQL_VIVAS_PANEL} "
                "GROUP BY ver_estado"):
            clave = r["ver_estado"] or "sin-verificar"
            ver[clave] = ver.get(clave, 0) + r["n"]
        d["por_verificacion"] = dict(sorted(ver.items(), key=lambda kv: -kv[1]))
        d["por_ats"] = {r["ats"]: r["n"] for r in con.execute(
            f"SELECT ats, COUNT(*) n FROM vacantes WHERE {SQL_VIVAS_PANEL} "
            "AND ats IS NOT NULL AND ats <> '' GROUP BY ats ORDER BY n DESC")}
        d["por_fuente"] = {r["fuente"]: r["n"] for r in con.execute(
            f"SELECT fuente, COUNT(*) n FROM vacantes WHERE {SQL_VIVAS_PANEL} "
            "GROUP BY fuente ORDER BY n DESC")}
    return d


def resumen() -> dict:
    with conexion() as con:
        t = con.execute("SELECT COUNT(*) n FROM vacantes").fetchone()["n"]
        c = con.execute("SELECT COUNT(*) n FROM corridas").fetchone()["n"]
        a = con.execute("SELECT COUNT(*) n FROM vacantes WHERE aplicada=1").fetchone()["n"]
        por_v = {
            r["veredicto"]: r["n"]
            for r in con.execute(
                "SELECT veredicto, COUNT(*) n FROM vacantes GROUP BY veredicto"
            )
        }
    return {"vacantes_historicas": t, "corridas": c, "aplicadas": a, "por_veredicto": por_v}


if __name__ == "__main__":
    print(json.dumps(resumen(), ensure_ascii=False, indent=2))
