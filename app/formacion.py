"""
Formacion: el mismo embudo que las vacantes, pero para cursos y convocatorias.

POR QUE EXISTE, y por que no bastaba con `cursos.py`. Ese modulo hace media
maquina: tiene catalogo (26 entradas comprobadas a mano), puntuacion contra las
brechas reales del CV y verificacion de que la URL sigue viva. Le faltan las
dos mitades que decidieron el giro de todo el proyecto:

  1. **A quien admite.** La tabla sabia lo que un curso ENSENA y lo que CUESTA,
     nunca a quien deja entrar. El aprendizaje mas caro estaba escrito en un
     comentario de `datos_cursos.py` --"Jovenes Construyendo el Futuro: exige
     NO estudiar"-- donde ninguna consulta lo ve. Un
     requisito de elegibilidad en prosa no filtra nada.
  2. **Si se inscribio.** No habia salida. El sistema entero llego a recomendar
     2.681 vacantes con cero postulaciones y por eso se giro de "buscador" a
     "maquina de postular"; un catalogo de 26 cursos con cero inscripciones es
     el mismo error con otro nombre.

LA METRICA DE ESTE CARRIL: **inscripciones ENVIADAS**. No cursos recolectados,
no cursos elegibles. Se cuenta con LISTA BLANCA (`ESTADOS_CUENTAN`) por la
cicatriz 26: con lista negra, anadir un estado nuevo infla la metrica en
silencio con cosas que no han salido.

POR QUE ESTE CARRIL MERECE EXISTIR AL LADO DEL DE VACANTES, dicho sin adornos:
no acelera una candidatura. Lo que hace es proteger contra el unico error que
no se puede deshacer. Una vacante perdida vuelve la semana siguiente con otro
identificador; **una convocatoria cerrada no vuelve hasta el ano que viene**.
Ya paso: una convocatoria se perdio por seis semanas.

LO QUE NO HACE, y son decisiones:

  - **No inscribe a nadie.** Deja el registro preparado y espera un si por
    curso, uno a uno, igual que `aprobaciones.py`. Sin aprobacion en bloque.
  - **No inventa elegibilidad.** `elegible` es ternario: 1 cabe, 0 no cabe,
    NULL no se sabe. Un 0 por defecto seria descartar por no haber leido, y
    asi se pierde una convocatoria buena en silencio (cicatriz 29).
  - **No lee mas alla de perfil.py.** Si una convocatoria pide un dato que no
    esta ahi (la edad, por ejemplo), el veredicto es NULL con el motivo
    escrito, nunca una suposicion. Cicatriz 6.

Uso:
    python formacion.py                       # el estado del carril
    python formacion.py --evaluar             # reevalua elegibilidad (UPDATE)
    python formacion.py --cola                # que conviene inscribir hoy
    python formacion.py --preparar CURSO_ID   # deja la inscripcion esperando un si
    python formacion.py --aprobar ID
    python formacion.py --rechazar ID "motivo"
    python formacion.py --enviada ID "folio o acuse"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

import areas                              # noqa: E402
from almacen import conexion              # noqa: E402
from nucleo import ahora_iso, normalizar, tiene_termino   # noqa: E402
from perfil import POSTULACION            # noqa: E402

# ---------------------------------------------------------------------------
# LA METRICA
#
# Lista BLANCA, nunca negra. La cicatriz 26 en una linea: `NOT IN
# ('borrador','descartada')` empezo a contar como enviadas las candidaturas
# `aprobada` el dia que ese estado se invento. Aqui, olvidarse de anadir un
# estado esconde una inscripcion real --se nota-- en vez de fabricar diez.
# ---------------------------------------------------------------------------
ESTADOS_CUENTAN = ("inscrita", "admitido", "en-curso", "completado")

# Estados que ocupan la plaza de un curso: mientras la inscripcion este en
# alguno de estos, ese curso NO se vuelve a proponer en la cola.
ESTADOS_VIVOS = ESTADOS_CUENTAN + ("borrador", "aprobada")


# ---------------------------------------------------------------------------
# ELEGIBILIDAD
#
# Que carreras cuentan como afines. Salen de las areas activas (`carreras` en
# `areas.py`) y de como escriben las convocatorias mexicanas: casi ninguna
# nombra la carrera exacta, dicen "areas afines a las TIC" o listan cuatro o
# cinco programas. Sin esta lista, un filtro por el nombre literal de una
# carrera descartaria practicamente todo.
# ---------------------------------------------------------------------------
def carreras_afines() -> list[str]:
    return areas.carreras_afines()

# Bloqueos duros. Cada uno sale de un requisito real visto en convocatorias
# mexicanas, y cada uno se contrasta contra `perfil.POSTULACION`, jamas contra
# una suposicion.
#
# El orden importa: se evalua de mas excluyente a menos, y el primero que
# dispara manda. Un curso que exige titulo no se salva porque ademas admita
# estudiantes.
BLOQUEOS = [
    ("no-estudiantes",
     ["no estar estudiando", "no encontrarse estudiando", "no ser estudiante",
      "que no estudien", "no estar inscrito en", "no cursar estudios"],
     "exige NO estar estudiando"),
    ("titulado",
     ["titulado", "titulados", "con titulo", "titulo de licenciatura",
      "haber concluido la licenciatura", "egresado titulado", "cedula profesional"],
     "pide titulo o cedula profesional"),
    ("posgrado",
     ["maestria", "doctorado", "posgrado", "master's degree", "phd",
      # Anadidos el 4-sep-2026 tras la primera corrida del vigilante: la
      # pagina de convocatorias de Secihti colo "Estancias Posdoctorales por
      # Mexico" y "Estancias Sabaticas" como candidatos elegibles, porque
      # "doctorado" no aparece en el titulo y "posdoctoral" no estaba aqui.
      "posdoctoral*", "postdoctoral*", "sabatic*", "de consolidacion",
      "investigadores por mexico", "catedras"],
     "es de nivel posgrado o para investigadores"),
    ("experiencia",
     ["2 anos de experiencia", "3 anos de experiencia", "5 anos de experiencia",
      "2+ years", "3+ years", "5+ years", "experiencia profesional comprobable"],
     "pide varios anos de experiencia profesional"),
    ("extranjero",
     ["residentes en estados unidos", "residentes en espana", "solo para residentes",
      "must be located in", "us residents only", "eu residents"],
     "restringido a residentes de otro pais"),
]


def _aplica_al_perfil(etiqueta: str) -> bool | None:
    """¿Este bloqueo le aplica a quien usa el sistema, segun `perfil.py`?

    True = aplica y descarta; False = no aplica; None = el perfil no lo dice,
    y entonces no se inventa un descarte (cicatriz 6: cero hechos fuera de
    perfil.py). "extranjero" no depende del perfil y aplica siempre.
    """
    p = POSTULACION
    if etiqueta == "titulado":
        return None if p.get("titulado") is None else not p.get("titulado")
    if etiqueta == "no-estudiantes":
        if p.get("titulado") is True:
            return False
        estudia = p.get("semestre") or "curso" in str(p.get("nivel_estudios") or "").lower()
        return True if estudia else None
    if etiqueta == "posgrado":
        nivel = str(p.get("nivel_estudios") or "").lower()
        if not nivel:
            return None
        return not any(x in nivel for x in ("maestr", "doctor", "posgrado"))
    if etiqueta == "experiencia":
        anios = p.get("anios_experiencia")
        return None if anios is None else anios < 2
    return True

# Lo contrario: senales de que SI es su sitio. No bastan por si solas para
# decir que si --primero tienen que pasar los bloqueos-- pero convierten un
# "no se sabe" en un "cabe".
SENALES_A_FAVOR = [
    ("estudiante-activo",
     ["estudiante", "estudiantes", "alumnos", "cursando", "inscrito en licenciatura",
      "undergraduate", "students", "universitarios"],
     "dirigido a estudiantes activos"),
    ("universidad-publica",
     ["universidad publica", "institucion publica", "instituciones publicas",
      "universidades publicas"],
     "exige institucion publica"),
    ("sin-requisitos",
     ["sin requisitos", "abierto a todo publico", "no se requiere experiencia",
      "no prior experience", "principiantes", "desde cero"],
     "abierto sin requisitos previos"),
]

# Datos que una convocatoria puede exigir y que NO estan en `perfil.py`.
# Cuando aparece uno de estos y nada mas bloquea, el veredicto es NULL con el
# motivo escrito: preferimos un "hay que leer las bases" visible a un si o un
# no inventado. Cicatriz 6 -- cero hechos fuera de perfil.py.
PIDE_DATO_QUE_NO_TENEMOS = [
    ("edad", ["entre 18 y 24 anos", "menores de 25", "rango de edad", "edad maxima",
              "hasta 29 anos", "jovenes de 18 a"],
     "pide un rango de edad y la edad no esta en perfil.py: hay que leer las bases"),
    ("promedio", ["promedio minimo", "promedio de 8", "promedio general de",
                  "gpa"],
     "pide promedio minimo y el promedio no esta en perfil.py"),
    ("carta-universidad", ["carta de la universidad", "carta de presentacion de la institucion",
                           "constancia de la facultad", "convenio de practicas"],
     "pide carta o convenio de la facultad (ver carta_de_la_universidad en perfil.py)"),
]

# ---------------------------------------------------------------------------
# AFINIDAD CON LAS AREAS
#
# La elegibilidad de arriba responde "¿me dejan entrar?"; esto responde "¿es de
# mis areas?". Son cosas distintas: una convocatoria de "Rotaciones Medicas y
# Estancias Tecnicas" deja postular a mucha gente y solo le sirve a quien tiene
# activa el area de salud.
#
# LA REGLA ES DE DOS LLAVES, y el orden importa: un curso solo se descarta por
# area cuando (a) nombra un dominio ajeno Y (b) NO nombra nada de las areas
# activas. Con una sola llave se cae en la cicatriz 29 -- un "Machine Learning
# aplicado a salud" o un "Ciberseguridad en el sector legal" son de tecnologia
# y llevan la palabra ajena dentro. Ninguno de los dos se descarta aqui, y
# estan en el test.
#
# Los tres vocabularios salen de `areas.py` segun ULTRACHAMBA_AREAS y
# ULTRACHAMBA_ZONA, y se leen en cada llamada, no al importar.
# ---------------------------------------------------------------------------
def otro_dominio() -> list[str]:
    """Dominios de curso ajenos a las areas activas."""
    return areas.terminos_otras_areas_curso()


def terminos_de_su_area() -> list[str]:
    """Lo de las areas activas: si aparece, la palabra ajena no descarta nada."""
    return areas.terminos_curso()


def cerca() -> list[str]:
    """Donde se puede asistir en persona: la zona base. Vacio en la zona
    `nacional`, y entonces la sede por si sola no descarta nada."""
    return areas.zona()["cerca_cursos"]


def _texto_de(c: dict) -> str:
    """Todo lo que dice el curso, junto y normalizado, para buscar terminos."""
    campos = ("nombre", "descripcion", "por_que", "requisitos", "publico",
              "carreras", "credencial", "institucion")
    return normalizar(" ".join(str(c.get(k) or "") for k in campos))


def evaluar(c: dict) -> tuple[int | None, str]:
    """Dice si un estudiante con el perfil de `perfil.py` cabe en este curso.

    Devuelve (1 | 0 | None, motivo). El NULL es tan importante como los otros
    dos: significa "la convocatoria no lo dice y no me lo invento".
    """
    texto = _texto_de(c)

    # 0. ¿Tenemos algo que leer, o solo un titulo?
    #
    # EL FALLO QUE ESTO CIERRA, y es el peor que ha tenido este modulo. Lo
    # encontro el agente `jefe` el 4-sep-2026, el mismo dia que se escribio:
    # las 33 filas que trajo el vigilante tenian `requisitos`, `carreras` y
    # `sede` VACIOS --nadie habia abierto la pagina-- y aun asi salian
    # `elegible=1`. El motivo era que `fuentes_cursos` copia `modalidad`,
    # `gratis` y `publico` de la constante SEMILLAS, y con eso la evaluacion
    # caia siempre en las ramas de abajo. Su prueba: un curso INVENTADO
    # ("Xyzzy Programa Zeta") daba "cabe" en once de las doce semillas.
    #
    # Un detector que siempre encuentra algo no detecta nada. Y el dano no era
    # teorico: "Becas Nacionales" (de POSGRADO) y "Estancias Tecnicas en Japon"
    # (que exige mudarse) salieron elegibles.
    #
    # La regla, y es de sentido comun escrito tarde: **de un titulo no se
    # deduce quien puede entrar.** Si el curso viene de una semilla y nadie ha
    # leido su ficha, el veredicto es NULL con el motivo dicho. NULL no es un
    # descarte: es la cola de trabajo, y ademas es cierto.
    origen = str(c.get("origen") or "")
    sin_leer = not any((c.get(k) or "").strip()
                       for k in ("requisitos", "carreras", "sede"))
    if origen.startswith("semilla:") and sin_leer:
        # Los bloqueos SI se aplican antes de rendirse: si el propio titulo
        # dice "posdoctoral" o "rotaciones medicas", eso ya es suficiente para
        # decir que no, y ahorra abrir la pagina. Solo los que el perfil
        # confirma: un bloqueo que perfil.py no resuelve no descarta.
        for etiqueta, terminos, motivo in BLOQUEOS:
            if any(tiene_termino(texto, t) for t in terminos):
                if etiqueta == "titulado" and tiene_termino(texto, "estudiantes"):
                    continue
                if _aplica_al_perfil(etiqueta) is True:
                    return 0, f"NO cabe: {motivo} (segun el titulo)"
        ajenos = [t for t in otro_dominio() if tiene_termino(texto, t)]
        if ajenos and not any(tiene_termino(texto, t) for t in terminos_de_su_area()):
            return 0, ("NO cabe: es de otro campo (" + ajenos[0].replace("*", "")
                       + "), no de tus areas")
        return None, ("POR CONFIRMAR: solo tenemos el titulo que salio de la "
                      "pagina; hay que abrirlo y leer los requisitos")

    # 1. Bloqueos duros. El primero que dispara Y le aplica al perfil manda.
    #    Si perfil.py no dice si le aplica, no se descarta: se anota, y si nada
    #    mas firme decide antes, el veredicto queda por confirmar.
    pendiente = None
    for etiqueta, terminos, motivo in BLOQUEOS:
        if any(tiene_termino(texto, t) for t in terminos):
            # Excepcion medida: "titulado" tambien aparece como "no titulado"
            # o "titulados y estudiantes". Si el texto admite explicitamente a
            # estudiantes, el bloqueo por titulo no aplica.
            if etiqueta == "titulado" and tiene_termino(texto, "estudiantes"):
                continue
            aplica = _aplica_al_perfil(etiqueta)
            if aplica is True:
                return 0, f"NO cabe: {motivo}"
            if aplica is None and pendiente is None:
                pendiente = f"POR CONFIRMAR: {motivo}, y perfil.py no dice si te aplica"

    # 2. Presencial fuera de la zona base. Descarta solo si perfil.py dice que
    #    no hay mudanza posible; sin zona base (`nacional`) la sede no decide.
    sede = normalizar(str(c.get("sede") or ""))
    modalidad = str(c.get("modalidad") or "")
    lugares = cerca()
    presencial = modalidad.startswith("presencial") or modalidad == "hibrido"
    if sede and lugares and presencial and not any(t in sede for t in lugares):
        mudanza = POSTULACION.get("disponibilidad_mudanza")
        if mudanza is False:
            return 0, (f"NO cabe: presencial en {c.get('sede')}, fuera de "
                       f"{areas.zona()['corta']} (perfil.disponibilidad_mudanza = False)")
        if mudanza is None and pendiente is None:
            pendiente = (f"POR CONFIRMAR: presencial en {c.get('sede')}, y perfil.py "
                         "no dice si puedes mudarte")

    # 2-bis. Otro campo del saber. Dos llaves: nombra un dominio ajeno Y no
    #        nombra ninguno de las areas activas. Con una sola se tiraria un
    #        "Machine Learning aplicado a salud", que es de tecnologia.
    ajeno = [t for t in otro_dominio() if tiene_termino(texto, t)]
    if ajeno and not any(tiene_termino(texto, t) for t in terminos_de_su_area()):
        return 0, ("NO cabe: es de otro campo (" + ajeno[0].replace("*", "") +
                   "), no de tus areas")

    if pendiente:
        return None, pendiente

    # 3. Datos que no tenemos. No bloquean: dejan el veredicto en "hay que
    #    leerlo", que es lo unico honesto.
    for etiqueta, terminos, motivo in PIDE_DATO_QUE_NO_TENEMOS:
        if (etiqueta == "carta-universidad"
                and POSTULACION.get("carta_de_la_universidad") is True):
            continue
        if any(tiene_termino(texto, t) for t in terminos):
            return None, f"POR CONFIRMAR: {motivo}"

    # 4. Carrera. Solo cuenta si la convocatoria SE MOLESTA en listar carreras;
    #    la mayoria no lo hace, y no decir nada no es excluir.
    campo_carreras = normalizar(str(c.get("carreras") or ""))
    if campo_carreras:
        afines = list(carreras_afines())
        if POSTULACION.get("carrera"):
            afines.append(normalizar(POSTULACION["carrera"]))
        if any(tiene_termino(campo_carreras, t) for t in afines):
            return 1, "cabe: admite carreras afines a tus areas"
        return 0, ("NO cabe: lista carreras y ninguna es afin a tus areas "
                   f"({c.get('carreras')})")

    # 5. Senales a favor. Dos dependen del perfil: "dirigido a estudiantes"
    #    solo suma si perfil.py dice que estudias, y "exige institucion
    #    publica" solo si dice que la tuya lo es.
    for etiqueta, terminos, motivo in SENALES_A_FAVOR:
        if not any(tiene_termino(texto, t) for t in terminos):
            continue
        # "no-estudiantes" le aplica justo a quien estudia.
        if etiqueta == "estudiante-activo" and _aplica_al_perfil("no-estudiantes") is not True:
            continue
        if etiqueta == "universidad-publica":
            publica = POSTULACION.get("institucion_publica")
            if publica is None:
                return None, ("POR CONFIRMAR: exige institucion publica; perfil.py "
                              "no dice si tu institucion lo es")
            if publica is False:
                continue
        return 1, f"cabe: {motivo}"

    # 6. Nada dijo nada. Un curso en linea y gratuito sin requisitos escritos
    #    casi siempre admite a cualquiera, pero "casi siempre" no es un dato.
    if modalidad == "linea" and (c.get("gratis") or "") == "total":
        return 1, ("cabe: curso en linea y gratuito, sin requisitos de acceso "
                   "declarados")
    return None, "POR CONFIRMAR: la ficha no dice a quien admite"


def reevaluar(solo_nulos: bool = False) -> dict:
    """Recalcula la elegibilidad de todo el catalogo.

    Es un UPDATE de columnas concretas y no un `guardar()`, por la cicatriz 2:
    reanalizar pasando por la escritura completa envenena los datos de origen
    (en vacantes borro la verificacion entera de dos corridas).
    """
    donde = "WHERE elegible IS NULL" if solo_nulos else ""
    with conexion() as con:
        filas = [dict(r) for r in con.execute(f"SELECT * FROM cursos {donde}")]
        cambios = []
        for c in filas:
            elegible, motivo = evaluar(c)
            cambios.append((elegible, motivo, ahora_iso(), c["id"]))
        con.executemany(
            "UPDATE cursos SET elegible=?, elegible_motivo=?, ultima_vez=? WHERE id=?",
            cambios)
        cuenta = {"cabe": 0, "no_cabe": 0, "por_confirmar": 0}
        for elegible, _m, _f, _i in cambios:
            if elegible == 1:
                cuenta["cabe"] += 1
            elif elegible == 0:
                cuenta["no_cabe"] += 1
            else:
                cuenta["por_confirmar"] += 1
    return {"evaluados": len(cambios), **cuenta}


# ---------------------------------------------------------------------------
# EL EMBUDO DE SALIDA
# ---------------------------------------------------------------------------
def _dias_para_cerrar(cierra: str | None) -> int | None:
    if not cierra:
        return None
    try:
        d = datetime.strptime(str(cierra)[:10], "%Y-%m-%d").date()
        return (d - date.today()).days
    except ValueError:
        return None


def _id_inscripcion(curso_id: str, cierra: str | None = None) -> str:
    """Un identificador por curso Y POR CONVOCATORIA.

    Lo senalo el `jefe`: siendo determinista solo por `curso_id`, un programa
    anual solo podia tener una inscripcion en toda su historia, y la
    convocatoria de 2027 sobrescribia la de 2026 sin dejar rastro. Es una
    subcuenta, no una inflada -- pero en un carril cuya metrica son las
    inscripciones, perder la del ano pasado al inscribirse este es justo lo
    contrario de lo que hace falta.
    """
    plazo = str(cierra or "")[:7]      # ano-mes del cierre, si lo hay
    return hashlib.sha1(f"insc|{curso_id}|{plazo}".encode("utf-8")).hexdigest()[:16]


# Palabras que no distinguen un programa de otro. Se quitan antes de comparar
# un curso con un tramite: sin esto, "Curso de IA" y "Curso de redes" comparten
# dos palabras y pareceria que son el mismo.
VACIAS = {"de", "del", "la", "el", "los", "las", "y", "en", "para", "con",
          "curso", "cursos", "programa", "beca", "becas", "convocatoria",
          "sede", "mexico", "2026", "2027", "por", "a", "al", "un", "una",
          # Palabras de PROCESO, no de programa. Las senalo una revision el
          # 4-sep-2026: un curso llamado "Examen de seleccion de datos"
          # emparejaba con el tramite de otro programa por {examen, seleccion}. Todo
          # tramite habla de examenes, registros y postulaciones; ninguna de
          # esas palabras distingue un programa de otro.
          "examen", "seleccion", "registrado", "registro", "postulacion",
          "oficial", "informacion", "importante", "solicitud", "estatus",
          "segunda", "primera", "aviso", "correo"}

# Alias escritos a mano: como llama el catalogo a un programa, y como lo llama
# el correo que manda ese programa.
#
# POR QUE ESTO ES UNA LISTA Y NO MAS COMPARACION DIFUSA. Una revision encontro
# que `tramite_vivo_de` no veia varios tramites abiertos de un programa porque
# el catalogo lo llamaba por su nombre publico y los correos del programa solo
# usaban sus siglas. La tentacion era comparar tambien la `institucion`; la
# misma revision explica por que seria peor: "Gobierno de Mexico" aparece en
# decenas de tramites, y un curso apartado por error es INVISIBLE -- no sale en
# la cola ni se queja.
#
# Una lista corta, explicita y auditable acierta donde la heuristica falla, y
# cuando se equivoca se ve en el archivo. Las entradas son programas publicos
# del catalogo de `datos_cursos.py`; anade los que uses tu.
ALIAS_PROGRAMAS = [
    (["cpf-ia", "cpfia", "mexia", "escuela publica de codigo"],
     ["cpfia", "cpf-ia", "centro publico de formacion", "propedeutico",
      "aspirantes.ia", "transformaciondigital"]),
    (["oci", "oracle"], ["oracle"]),
    (["samsung", "innovation campus"], ["samsung", "innovation campus", "sic "]),
]


def tramite_vivo_de(curso: dict) -> dict | None:
    """Devuelve el tramite abierto que YA cubre este curso, si lo hay.

    EL FALLO QUE ESTO ARREGLA, visto el 4-sep-2026 en la primera corrida de la
    cola: propuso inscribirse a un programa el mismo dia en que el correo ya
    mostraba el examen de seleccion aprobado y una entrevista agendada. Los dos
    datos eran ciertos y vivian en tablas que no se hablaban -- `cursos` y
    `tramites`.

    Es la cicatriz 22 otra vez: el problema no era el calculo, era que la
    consulta solo podia ver una parte del mundo. Proponer un gesto ya dado es
    la forma mas rapida de que quien usa el sistema deje de leer la cola.

    Se comparan TOKENS distintivos, no la cadena entera: el catalogo lo llama
    "Programa Ejemplo 2026 - sede Norte" y el correo "PE 2026 - EXAMEN DE
    SELECCION" o "Confirmacion para entrevista virtual - Programa Ejemplo". Se
    exigen DOS coincidencias para no emparejar por una palabra suelta.
    """
    nombre = normalizar(curso.get("nombre") or "")
    palabras = {p for p in nombre.split() if p not in VACIAS and len(p) > 3}

    # Los alias ganan a los tokens: son lo unico que puede cruzar del nombre
    # publico de un programa a las siglas con las que firma sus correos.
    alias_activos = [correos for claves, correos in ALIAS_PROGRAMAS
                     if any(k in nombre for k in claves)]

    if len(palabras) < 2 and not alias_activos:
        return None
    with conexion() as con:
        filas = con.execute("""
            SELECT id, titulo, organizacion, remitente, clase, estado, accion
            FROM tramites
            WHERE estado IS NULL OR estado NOT IN ('cerrado','descartado')
            """).fetchall()
    for t in filas:
        texto = normalizar(f"{t['titulo'] or ''} {t['organizacion'] or ''} "
                           f"{t['remitente'] or ''}")
        # Un solo alias basta: no es una coincidencia de palabras sueltas, es
        # un nombre propio de programa escrito a mano en ALIAS_PROGRAMAS.
        if any(any(a in texto for a in correos) for correos in alias_activos):
            return dict(t)
        if len({p for p in palabras if p in texto}) >= 2:
            return dict(t)
    return None


def cola_de_hoy(n: int = 3) -> list[dict]:
    """Que conviene inscribir hoy, y en que orden.

    El orden NO es por puntuacion. Manda el plazo: un curso de 60 puntos que
    cierra en cinco dias va antes que uno de 90 permanente, porque el segundo
    seguira ahi manana y el primero no. Es la diferencia entre este carril y el
    de vacantes, y la razon por la que existe.
    """
    with conexion() as con:
        filas = [dict(r) for r in con.execute(f"""
            SELECT c.* FROM cursos c
            WHERE (c.ver_estado IS NULL OR c.ver_estado != 'cerrada')
              AND (c.convocatoria IS NULL OR c.convocatoria != 'cerrada')
              AND (c.elegible IS NULL OR c.elegible = 1)
              AND (c.estado_revision IS NULL OR c.estado_revision = 'aceptado')
              AND c.descartado_motivo IS NULL
              AND c.id NOT IN (SELECT curso_id FROM inscripciones
                               WHERE estado IN ({",".join("?" * len(ESTADOS_VIVOS))}))
            """, ESTADOS_VIVOS)]

    vivos = []
    for c in filas:
        dias = _dias_para_cerrar(c.get("cierra"))
        if dias is not None and dias < 0:
            continue                      # el plazo ya vencio
        ya = tramite_vivo_de(c)
        if ya:
            # No se propone lo que ya esta en marcha por otra via. No se
            # descarta el curso: se aparta de la cola y se dice por que, para
            # que se pueda enlazar la inscripcion con `--enlazar`.
            continue
        c["dias_para_cerrar"] = dias
        # Urgencia primero (sin plazo = 9999, va al final), luego puntuacion.
        c["_orden"] = (dias if dias is not None else 9999, -(c.get("score") or 0))
        vivos.append(c)
    vivos.sort(key=lambda x: x["_orden"])
    for c in vivos:
        c.pop("_orden", None)
    return vivos[:n]


def preparar(curso_id: str, via: str = "formulario", nota: str = "") -> dict:
    """Deja una inscripcion esperando tu si. No inscribe nada."""
    with conexion() as con:
        curso = con.execute("SELECT * FROM cursos WHERE id=?", (curso_id,)).fetchone()
        if not curso:
            return {"error": f"no existe el curso {curso_id}"}
        curso = dict(curso)
        ya = con.execute("SELECT id, estado FROM inscripciones WHERE curso_id=?",
                         (curso_id,)).fetchone()
        if ya and ya["estado"] in ESTADOS_VIVOS:
            return {"error": f"ya hay una inscripcion {ya['estado']} para este curso",
                    "id": ya["id"]}
        iid = _id_inscripcion(curso_id, curso.get("cierra"))
        con.execute("""
            INSERT INTO inscripciones (id, curso_id, estado, via, url_registro,
                                       nota, creada, actualizada)
            VALUES (?,?,'borrador',?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET estado='borrador', via=excluded.via,
                url_registro=excluded.url_registro, nota=excluded.nota,
                motivo=NULL, actualizada=excluded.actualizada
            """, (iid, curso_id, via, curso.get("url"), nota,
                  ahora_iso(), ahora_iso()))
    return {"id": iid, "curso": curso["nombre"], "estado": "borrador",
            "url": curso.get("url")}


def _cambiar_estado(iid: str, nuevo: str, desde: tuple[str, ...],
                    **campos) -> dict:
    """Cambia el estado con cerrojo, no con 'comprobar y luego escribir'.

    La cicatriz 28: entre un SELECT que comprueba y un UPDATE que actua cabe
    otra ejecucion entera --el agente de casa corre cada 180 s-- y el resultado
    fue mandar el mismo correo dos veces. El cerrojo es que el propio UPDATE
    lleve el estado esperado en el WHERE: solo una ejecucion lo gana.
    """
    sets = ["estado=?", "actualizada=?"]
    args: list = [nuevo, ahora_iso()]
    for k, v in campos.items():
        sets.append(f"{k}=?")
        args.append(v)
    marcas = ",".join("?" * len(desde))
    with conexion() as con:
        cur = con.execute(
            f"UPDATE inscripciones SET {','.join(sets)} "
            f"WHERE id=? AND estado IN ({marcas})",
            args + [iid] + list(desde))
        if cur.rowcount == 0:
            fila = con.execute("SELECT estado FROM inscripciones WHERE id=?",
                               (iid,)).fetchone()
            actual = fila["estado"] if fila else "no existe"
            return {"error": f"no se pudo pasar a '{nuevo}': esta en '{actual}'"}
    return {"id": iid, "estado": nuevo}


def aprobar(iid: str) -> dict:
    """El si. Separado de la ejecucion a proposito (cicatriz 24)."""
    return _cambiar_estado(iid, "aprobada", ("borrador",),
                           aprobada_fecha=ahora_iso())


def rechazar(iid: str, motivo: str) -> dict:
    """El no, con motivo. Sin motivo solo se esconde la tarjeta."""
    if not (motivo or "").strip():
        return {"error": "un rechazo sin motivo no ensena nada: escribe por que"}
    with conexion() as con:
        fila = con.execute("SELECT curso_id FROM inscripciones WHERE id=?",
                           (iid,)).fetchone()
        if fila:
            # El motivo baja al curso, que es lo que lee `cola_de_hoy`, para
            # que esa clase de curso deje de proponerse. Mismo mecanismo que
            # `vacantes.descartada_motivo`.
            con.execute("UPDATE cursos SET descartado_motivo=? WHERE id=?",
                        (motivo, fila["curso_id"]))
    return _cambiar_estado(iid, "descartada", ("borrador", "aprobada"),
                           motivo=motivo)


def marcar_enviada(iid: str, evidencia: str = "") -> dict:
    """El registro salio. Esto, y solo esto, mueve la metrica."""
    return _cambiar_estado(iid, "inscrita", ("borrador", "aprobada"),
                           enviada=ahora_iso(), evidencia=evidencia)


def en_marcha() -> list[dict]:
    """Cursos del catalogo que ya tienen un tramite abierto en Gmail.

    Es lo que la cola aparta, puesto donde se ve. Cada linea de aqui es una
    inscripcion que probablemente YA ocurrio y que la metrica no esta contando:
    se enlaza con `--enlazar CURSO_ID TRAMITE_ID`, y solo despues de
    confirmarlo a mano. El sistema no da por hecho lo que encaja
    (cicatriz 20): encajar no es constar.
    """
    marcas = ",".join("?" * len(ESTADOS_VIVOS))
    with conexion() as con:
        filas = [dict(r) for r in con.execute(f"""
            SELECT * FROM cursos
            WHERE (estado_revision IS NULL OR estado_revision='aceptado')
              AND id NOT IN (SELECT curso_id FROM inscripciones
                             WHERE estado IN ({marcas}))
            """, ESTADOS_VIVOS)]
    salida = []
    for c in filas:
        t = tramite_vivo_de(c)
        if t:
            salida.append({"curso_id": c["id"], "curso": c["nombre"],
                           "tramite_id": t["id"], "tramite": t["titulo"],
                           "clase": t["clase"], "accion": t["accion"]})
    return salida


def enlazar(curso_id: str, tramite_id: str) -> dict:
    """Registra como inscrita una candidatura que ya ocurrio por correo.

    Mueve la metrica, asi que exige un hecho: el hilo de Gmail queda como
    evidencia. No se llama solo desde `en_marcha()` a proposito -- se dispara
    a mano cuando se confirma que ese hilo es de ese programa.
    """
    with conexion() as con:
        curso = con.execute("SELECT nombre, cierra FROM cursos WHERE id=?",
                            (curso_id,)).fetchone()
        tram = con.execute("SELECT titulo, hilo_gmail FROM tramites WHERE id=?",
                           (tramite_id,)).fetchone()
        if not curso or not tram:
            return {"error": "no existe el curso o el tramite"}
        iid = _id_inscripcion(curso_id, curso["cierra"])

        # Un enlace NO resucita algo que se descarto. Una revision lo marco
        # como el unico camino que saltaba el embudo entero: este INSERT ...
        # ON CONFLICT escribia 'inscrita' encima de cualquier estado, sin pasar
        # por `_cambiar_estado` ni por su cerrojo. Que exija dos identificadores
        # a mano no lo hace seguro: hace que el error sea raro, no imposible.
        previa = con.execute("SELECT estado FROM inscripciones WHERE id=?",
                             (iid,)).fetchone()
        if previa and previa["estado"] == "descartada":
            return {"error": "esta inscripcion se descarto antes; si cambio de "
                             "idea, preparala de nuevo con --preparar"}
        con.execute("""
            INSERT INTO inscripciones (id, curso_id, estado, via, nota,
                                       evidencia, hilo_gmail, creada, enviada,
                                       actualizada)
            VALUES (?,?,'inscrita','correo',?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET estado='inscrita',
                evidencia=excluded.evidencia, hilo_gmail=excluded.hilo_gmail,
                enviada=COALESCE(inscripciones.enviada, excluded.enviada),
                actualizada=excluded.actualizada
            """, (iid, curso_id, f"enlazada al tramite: {tram['titulo']}",
                  f"tramite:{tramite_id}", tram["hilo_gmail"],
                  ahora_iso(), ahora_iso(), ahora_iso()))
    return {"id": iid, "curso": curso["nombre"], "estado": "inscrita",
            "evidencia": f"tramite:{tramite_id}"}


def pendientes() -> list[dict]:
    """Lo que espera un si o un no, con su curso al lado."""
    with conexion() as con:
        filas = con.execute("""
            SELECT i.id, i.estado, i.via, i.url_registro, i.nota, i.creada,
                   c.nombre, c.institucion, c.cierra, c.gratis, c.credencial,
                   c.elegible, c.elegible_motivo, c.score
            FROM inscripciones i JOIN cursos c ON c.id = i.curso_id
            WHERE i.estado IN ('borrador','aprobada')
            ORDER BY (c.cierra IS NULL), c.cierra ASC
            """).fetchall()
    salida = []
    for f in filas:
        d = dict(f)
        d["dias_para_cerrar"] = _dias_para_cerrar(d.get("cierra"))
        salida.append(d)
    return salida


def cifras() -> dict:
    """La foto del carril, contada contra la base y de una sola llamada.

    Existe por lo mismo que `almacen.cifras_panel()`: mientras cada sitio
    reconstruia su propio WHERE, el dashboard llego a publicar 2.228 vacantes
    vivas contra las 3.700 de la base. Una cifra, un sitio.
    """
    marcas = ",".join("?" * len(ESTADOS_CUENTAN))
    # El MISMO conjunto para las cuatro cuentas, escrito una vez. Se corrigio
    # dos veces el mismo dia y la segunda la encontro el `jefe`: primero
    # faltaba `estado_revision` en tres de ellas (y "20 aceptados" convivia con
    # "39 le sirven"), y despues seguia faltando `ver_estado` y
    # `descartado_motivo`, lo que dejaba la puerta abierta a que la suma de las
    # partes volviera a superar al todo en cuanto se verificara un curso
    # cerrado o se rechazara uno. Un WHERE compartido no se puede
    # desincronizar consigo mismo.
    EN_CATALOGO = """(ver_estado IS NULL OR ver_estado != 'cerrada')
                     AND (estado_revision IS NULL OR estado_revision='aceptado')
                     AND descartado_motivo IS NULL"""
    with conexion() as con:
        fila = con.execute(f"""
            SELECT
              (SELECT COUNT(*) FROM cursos WHERE {EN_CATALOGO}) AS catalogo,
              (SELECT COUNT(*) FROM cursos WHERE estado_revision='candidato'
              ) AS candidatos,
              (SELECT COUNT(*) FROM cursos WHERE elegible=1
                 AND {EN_CATALOGO}) AS elegibles,
              (SELECT COUNT(*) FROM cursos WHERE elegible IS NULL
                 AND {EN_CATALOGO}) AS por_confirmar,
              (SELECT COUNT(*) FROM cursos WHERE elegible=0
                 AND {EN_CATALOGO}) AS no_elegibles,
              (SELECT COUNT(*) FROM inscripciones WHERE estado IN ({marcas})
              ) AS inscripciones_enviadas,
              (SELECT COUNT(*) FROM inscripciones WHERE estado='borrador'
              ) AS borradores,
              (SELECT COUNT(*) FROM inscripciones WHERE estado='aprobada'
              ) AS aprobadas_sin_salir,
              (SELECT COUNT(*) FROM inscripciones WHERE estado='admitido'
              ) AS admitido
            """, ESTADOS_CUENTAN).fetchone()
        cierran = [dict(r) for r in con.execute("""
            SELECT nombre, institucion, cierra, url FROM cursos
            WHERE cierra IS NOT NULL AND cierra <> ''
              AND date(cierra) >= date('now')
              AND (elegible IS NULL OR elegible = 1)
              AND descartado_motivo IS NULL
              AND id NOT IN (SELECT curso_id FROM inscripciones
                             WHERE estado NOT IN ('descartada'))
            ORDER BY cierra ASC LIMIT 5
            """)]
    d = dict(fila)
    # Se quitan los que ya estan en marcha por correo. Un aviso de "cierra en
    # 14 dias" sobre algo donde ya hiciste el examen no es urgencia: es ruido,
    # y el ruido en un aviso de plazos hace que se dejen de leer los plazos.
    cierran = [c for c in cierran if not tramite_vivo_de(c)]
    for c in cierran:
        c["dias"] = _dias_para_cerrar(c["cierra"])
    d["se_cierran_pronto"] = cierran
    return d


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _imprimir_estado() -> None:
    c = cifras()
    print(f"\nFORMACION | inscripciones enviadas: {c['inscripciones_enviadas']}"
          f" | admitido en: {c['admitido']}")
    # "sin bloqueo conocido", NO "le sirven". La diferencia la marco el `jefe`
    # y es la honesta: de los 16 del catalogo, trece salen de la rama "curso en
    # linea y gratuito, sin requisitos de acceso declarados", que significa
    # "nadie ha leido sus requisitos". Llamar a eso "le sirven" es vender un
    # dato que el sistema no tiene.
    print(f"Catalogo: {c['catalogo']} cursos aceptados"
          f" ({c['elegibles']} sin bloqueo conocido, {c['por_confirmar']} por"
          f" confirmar, {c['no_elegibles']} descartados)"
          f" | {c['candidatos']} candidatos sin revisar")
    if c["borradores"] or c["aprobadas_sin_salir"]:
        print(f"Esperando: {c['borradores']} borradores,"
              f" {c['aprobadas_sin_salir']} aprobadas sin salir")

    pend = pendientes()
    if pend:
        print("\nESPERAN TU VISTO BUENO:")
        for p in pend:
            plazo = (f"cierra en {p['dias_para_cerrar']} dias"
                     if p["dias_para_cerrar"] is not None else "sin plazo")
            print(f"  [{p['id']}] {p['estado']:8} | {p['nombre'][:50]:50} | {plazo}")

    marcha = en_marcha()
    if marcha:
        print("\nYA EN MARCHA por correo, y la metrica no lo cuenta"
              " (enlazar con --enlazar CURSO TRAMITE):")
        for m in marcha:
            print(f"  {m['curso'][:44]:44} <- {m['tramite'][:44]}")
            print(f"    curso {m['curso_id']} | tramite {m['tramite_id']}")

    if c["se_cierran_pronto"]:
        print("\nSE CIERRAN PRONTO (no se recuperan):")
        for x in c["se_cierran_pronto"]:
            print(f"  {x['cierra']} (en {x['dias']:3} dias) | {x['nombre'][:52]}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--evaluar", action="store_true",
                   help="recalcula la elegibilidad de todo el catalogo")
    p.add_argument("--solo-nulos", action="store_true",
                   help="con --evaluar: solo los que aun no tienen veredicto")
    p.add_argument("--cola", action="store_true", help="que conviene inscribir hoy")
    p.add_argument("--preparar", metavar="CURSO_ID")
    p.add_argument("--via", default="formulario")
    p.add_argument("--aprobar", metavar="ID")
    p.add_argument("--rechazar", nargs=2, metavar=("ID", "MOTIVO"))
    p.add_argument("--enviada", nargs="+", metavar="ID [EVIDENCIA]")
    p.add_argument("--enlazar", nargs=2, metavar=("CURSO_ID", "TRAMITE_ID"),
                   help="registra como inscrita una que ya ocurrio por correo")
    args = p.parse_args()

    if args.enlazar:
        print(enlazar(args.enlazar[0], args.enlazar[1]))
        sys.exit(0)

    if args.evaluar:
        print("elegibilidad:", reevaluar(solo_nulos=args.solo_nulos))
    elif args.preparar:
        print(json.dumps(preparar(args.preparar, via=args.via),
                         ensure_ascii=False, indent=2))
    elif args.aprobar:
        print(aprobar(args.aprobar))
    elif args.rechazar:
        print(rechazar(args.rechazar[0], args.rechazar[1]))
    elif args.enviada:
        print(marcar_enviada(args.enviada[0], " ".join(args.enviada[1:])))
    elif args.cola:
        lista = cola_de_hoy(5)
        print(f"\n{len(lista)} para inscribir hoy, por PLAZO (no por puntuacion)\n")
        for c in lista:
            plazo = (f"cierra en {c['dias_para_cerrar']} dias"
                     if c["dias_para_cerrar"] is not None else "permanente")
            print(f"  [{c['id']}] {c['score'] or 0:5.1f} | {c['nombre'][:44]:44}"
                  f" | {plazo}")
            print(f"          {c.get('elegible_motivo') or ''}")
    else:
        _imprimir_estado()
