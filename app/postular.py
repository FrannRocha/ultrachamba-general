"""
Postular en las bolsas (OCC, Indeed, Computrabajo) con una persona de portera.

Como funciona el reparto, que es lo importante:

    el sistema  elige la vacante, prepara el paquete y rellena el formulario
    la persona  MIRA la pantalla y dice si
    el sistema  pulsa Enviar
    el correo   confirma que llego de verdad

Por que no lo hace todo solo. Dos razones, y ninguna es tecnica:

  1. Una postulacion es un acto suyo con su nombre. Que la revise antes de
     salir no es burocracia, es lo que separa una herramienta de un bot que
     dispara curriculums.
  2. Las bolsas detectan y castigan el envio automatico. Perder la cuenta de
     OCC seria perder 772 vacantes de golpe. Una a una, a ritmo humano y con
     un humano mirando, es tambien lo mas seguro.

Lo que este modulo NO hace, nunca: iniciar sesion, escribir una contraseña,
resolver un CAPTCHA ni inventarse un dato que no este en `perfil.py`. Si un
formulario pide algo que no sabemos, la postulacion se para y lo pregunta.

La pieza que lo cierra: **la confirmacion se lee del correo**. OCC e Indeed
mandan un acuse ("tu postulacion fue enviada con exito"). Hasta que ese correo
aparece, la candidatura no cuenta como enviada. Haber pulsado un boton no es
prueba de nada; el acuse si.

CICATRIZ DEL 24 DE AGOSTO DE 2026 -- leer antes de automatizar un envio.

Cuatro postulaciones "se enviaron" y ninguna existio. El modal se cerraba, no
salia ningun error, y al recargar la oferta seguia diciendo "Postularme". La
hipotesis facil era que OCC estaba bloqueando envios automaticos, y se estuvo
a punto de darla por buena y parar.

Lo que dijo el registro de red: **no habia ni una sola peticion a OCC**. Ni un
POST rechazado, ni un 429: nada. El servidor nunca se entero. El clic sobre
"Postularme" del modal, hecho por COORDENADAS, no llegaba al boton.

La solucion es pulsar el ELEMENTO, no el punto:

    localizar el dialogo por su texto ("Completa el nivel de conocimientos"),
    buscar dentro su boton "Postularme", y despachar sobre el la secuencia
    completa pointerdown -> mousedown -> pointerup -> mouseup -> click.

Con eso entra a la primera. Dos lecciones que valen mas que el arreglo:

  1. **Ante un fallo silencioso, medir antes de teorizar.** "Nos estan
     bloqueando" era plausible, encajaba con los sintomas y era FALSO. Treinta
     segundos de registro de red lo desmintieron.
  2. **Pulsar un boton no es enviar.** La unica prueba valida es recargar la
     oferta y ver "Ya estas postulado", que es estado del servidor.

Uso:
    python postular.py --siguiente          # el paquete de la proxima
    python postular.py --siguiente --occ    # solo de una bolsa
    python postular.py --confirmar          # busca acuses en el correo
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import re

import areas
from almacen import conexion
from nucleo import ahora_iso
from perfil import POSTULACION, huecos_de_postulacion

# De donde se puede postular con este flujo. Cada una tiene su propia forma de
# acusar recibo; sin acuse no se puede verificar, y sin verificar no se apunta.
BOLSAS = {
    "occ": {
        "dominio": "occ.com.mx",
        "via": "portal-occ",
        # El acuse de OCC llega de su dominio de envios masivos.
        "acuse": 'from:(occmundial.com.mx OR occ.com.mx) subject:(postulacion OR postulación OR postulaste)',
    },
    "indeed": {
        "dominio": "indeed.com",
        "via": "portal-indeed",
        "acuse": 'from:indeed.com subject:(postulacion OR postulación OR "application" OR enviada)',
    },
    "computrabajo": {
        "dominio": "computrabajo",
        "via": "portal-computrabajo",
        "acuse": 'from:computrabajo subject:(postulacion OR postulación OR candidatura)',
    },
}

DIAS_SIN_REPETIR_EMPRESA = 7


def _id(*partes: str) -> str:
    return hashlib.sha1("|".join(partes).encode()).hexdigest()[:16]


def _normalizar(texto: str) -> str:
    return re.sub(r"\s+", " ", (texto or "").lower()).strip()


def elegir(bolsa: str | None = None, limite: int = 1) -> list[dict]:
    """La siguiente vacante a la que postular, por puntuacion.

    Excluye lo ya aplicado y las empresas a las que se escribio hace menos de
    una semana: insistirle a la misma empresa cada dia no da mas opciones, da
    menos, porque quema el unico contacto que habia.
    """
    dominios = ([BOLSAS[bolsa]["dominio"]] if bolsa
                else [b["dominio"] for b in BOLSAS.values()])
    corte = (dt.date.today() - dt.timedelta(days=DIAS_SIN_REPETIR_EMPRESA)).isoformat()

    condicion = " OR ".join("v.url LIKE ?" for _ in dominios)
    parametros = [f"%{d}%" for d in dominios] + [corte]

    with conexion() as con:
        filas = con.execute(f"""
            SELECT v.id, v.titulo, v.empresa, v.url, v.ubicacion, v.score,
                   v.modalidad, v.descripcion
            FROM vacantes v
            WHERE ({condicion})
              AND v.score >= 40 AND v.elegible_mx = 1 AND v.area != 'fuera'
              AND (v.nivel IS NULL OR v.nivel != 'excluido')
              AND (v.ver_estado IS NULL OR v.ver_estado != 'cerrada')
              AND (v.aplicada IS NULL OR v.aplicada = 0)
              AND v.descartada_motivo IS NULL
              AND v.id NOT IN (SELECT vacante_id FROM candidaturas
                               WHERE vacante_id IS NOT NULL)
              AND LOWER(v.empresa) NOT IN (
                    SELECT LOWER(c.asunto) FROM candidaturas c
                    WHERE c.enviada >= ?)
            ORDER BY v.score DESC
            LIMIT ?""", (*parametros, limite)).fetchall()
    return [dict(f) for f in filas]


# Lo que descalifica una vacante DESPUES de abrirla. El pipeline clasifica por
# el resumen; aqui se lee el anuncio entero, que es donde estan los requisitos
# que nadie pone en el titulo.
#
# Estan como texto y no como codigo porque los anuncios mexicanos escriben lo
# mismo de diez maneras, y un fallo aqui no es "un falso positivo": es
# alguien perdiendo la manana en una vacante imposible, o peor, postulando a
# algo que exige lo que no tiene y quedando fichado como el que no lee.
FUERA_DE_ALCANCE = {
    "experiencia": [
        r"\b([2-9]|1[0-9])\s*(\+|o mas|o más)?\s*a[nñ]os de experiencia",
        r"experiencia (minima|mínima) de\s*([2-9]|1[0-9])",
    ],
    "titulacion": [
        r"titulad[oa] (obligatorio|indispensable)",
        r"(con|debe tener) c[eé]dula profesional",
        r"pasante titulad",
        # Campo estructurado de OCC, y por eso el mas fiable de todos: la
        # propia bolsa lo pone en "Educacion minima requerida". Su valor
        # hermano, "Universitario sin titulo", es el que si sirve.
        r"educaci[oó]n m[ií]nima requerida:?\s*universitario titulado",
        r"(licenciatura|ingenier[ií]a) (concluida|terminada|titulad)",
    ],
    # Solo se aplica si `perfil.POSTULACION['carta_de_la_universidad']` es
    # False: sin carta de la facultad ni convenio, estas vacantes no son
    # viables. El semestre exigido no se enumera aqui: se compara en
    # `evaluar()` contra `perfil.POSTULACION['semestre']`.
    "carta": [
        r"carta (de presentaci[oó]n|compromiso) de la (universidad|instituci[oó]n)",
        r"convenio de pr[aá]cticas profesionales",
        r"(debe|deber[aá]) estar (realizando|liberando) (su )?servicio social",
    ],
    # Solo si `perfil.POSTULACION['requiere_practicas_obligatorias']` es False.
    # Un anuncio lo puso en mayusculas la primera linea: "POSTULATE UNICAMENTE
    # SI REQUIERES REALIZAR PRACTICAS". Si no se requieren, postular ahi es
    # hacer perder el tiempo a los dos.
    "solo_practicas_obligatorias": [
        r"[uú]nicamente si requieres realizar pr[aá]cticas",
        r"solo si (necesitas|requieres) (liberar|realizar) (tus )?pr[aá]cticas",
    ],
    # "Remote" casi nunca significa "desde donde quieras". Un internship se
    # anunciaba como Remote y el formulario exigia, en campo obligatorio, "full
    # authorization to work in the United States without employer
    # sponsorship". Quien vive en Mexico necesita patrocinio: responder que si
    # seria mentir y responder que no descarta al instante.
    #
    # El clasificador las marcaba `elegible_mx=1` porque el titulo dice Remote.
    # Esto lee el cuerpo, que es donde esta la verdad.
    "sin_autorizacion": [
        r"authorization to work in the united states",
        r"authorized to work in the (united states|u\.?s\.?)",
        r"without (employer )?(visa )?sponsorship",
        r"(does not|do not|cannot) (offer|provide) (visa )?sponsorship",
        r"must be (legally )?(authorized|eligible) to work in the u",
        r"us work authorization required",
        # "Werkstudent" no es un sinonimo aleman de "becario": es una figura
        # legal que exige estar matriculado en una universidad ALEMANA y tener
        # permiso de residencia. Una universidad mexicana no sirve.
        #
        # Se buscaba "immatrikuliert", pero muchos anuncios no lo escriben: el
        # de Meierhofer (Leipzig) no lo llevaba y se colaba en la cola diaria.
        # La palabra del puesto es la señal fiable.
        r"werkstudent",
        r"immatrikuliert",
        r"eingeschriebene[rn]? student",
        r"duales? studium",
    ],
    # Sin sueldo no sirve (ver `salario_esperado_mxn` en perfil.py). Y el dato casi nunca
    # esta en el campo de salario, sino escondido en la descripcion.
    "sin_pago": [
        r"apoyo econ[oó]mico:?\s*no\b",
        r"sin apoyo econ[oó]mico",
        r"pr[aá]cticas no remunerad",
        r"no remunerad[ao]",
        r"sin goce de sueldo",
        r"beca(rio)? no remunerad",
    ],
}

# Que la oferta este en otra ciudad Y sea presencial es el descarte mas comun,
# y el que mas veces erro el clasificador. Las ciudades "lejos" dependen de la
# zona base (ver `areas.py`); sin zona base no hay ninguna.
def ciudades_lejos() -> list[str]:
    return areas.zona()["ciudades_lejos"]


# Semestres escritos con letra ("octavo semestre"), sobre texto sin acentos.
ORDINALES = {"primer": 1, "primero": 1, "segundo": 2, "tercer": 3, "tercero": 3,
             "cuarto": 4, "quinto": 5, "sexto": 6, "septimo": 7, "octavo": 8,
             "noveno": 9, "decimo": 10}


def tope_anios() -> int:
    """Anios de experiencia admitidos: los que declara el perfil, minimo 1.

    Sin dato se queda en 1, que es el alcance del sistema: practicas y primer
    empleo.
    """
    anios = POSTULACION.get("anios_experiencia")
    return max(1, int(anios)) if isinstance(anios, (int, float)) else 1


def _anios_de(fragmento: str) -> int:
    numero = re.search(r"\d+", fragmento)
    return int(numero.group(0)) if numero else 99


def _aplica_categoria(etiqueta: str) -> bool:
    """¿Esta categoria de descarte le aplica a quien usa el sistema?

    Las que dependen de su situacion solo descartan si perfil.py la declara:

      titulacion                    si `titulado` es False
      carta                         si `carta_de_la_universidad` es False
      solo_practicas_obligatorias   si `requiere_practicas_obligatorias` es False
      sin_autorizacion              salvo `CANDIDATO['requiere_patrocinio_visa']` False
      sin_pago                      si hay `salario_esperado_mxn`

    `experiencia` se mira siempre, pero contra `tope_anios()`.
    """
    from perfil import CANDIDATO
    p = POSTULACION
    if etiqueta == "titulacion":
        return p.get("titulado") is False
    if etiqueta == "carta":
        return p.get("carta_de_la_universidad") is False
    if etiqueta == "solo_practicas_obligatorias":
        return p.get("requiere_practicas_obligatorias") is False
    if etiqueta == "sin_autorizacion":
        return CANDIDATO.get("requiere_patrocinio_visa") is not False
    if etiqueta == "sin_pago":
        return p.get("salario_esperado_mxn") is not None
    return True


def evaluar(texto: str, ubicacion: str = "") -> list[str]:
    """Motivos por los que esta vacante NO sirve. Lista vacia = adelante.

    Recibe el texto del anuncio tal como se ve en el navegador, no el resumen
    que guardo el pipeline: la diferencia entre los dos es justo donde estan
    los descartes.
    """
    import unicodedata
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    motivos = []

    for etiqueta, patrones in FUERA_DE_ALCANCE.items():
        # Las categorias que dependen del perfil solo se aplican si el perfil
        # lo declara explicitamente. Un perfil sin rellenar (None) no descarta
        # nada: descartar por no saber es inventar.
        if not _aplica_categoria(etiqueta):
            continue
        for p in patrones:
            m = re.search(p, t)
            if not m:
                continue
            if etiqueta == "experiencia" and _anios_de(m.group(0)) <= tope_anios():
                continue
            motivos.append(f"{etiqueta}: coincide con «{p}»")
            break

    # El semestre se compara, no se enumera: una lista escrita a mano dejaba
    # pasar el 7 ("7o semestre") y habria que reescribirla cada seis meses. Sale
    # de `perfil.POSTULACION`, asi que se corrige sola al avanzar de semestre.
    # Sin semestre en el perfil no se compara nada.
    suyo = POSTULACION.get("semestre") or 0
    # Ojo con «7°»: el simbolo de grado (U+00B0) y el ordinal masculino
    # (U+00BA) NO son la letra "o", y `normalize` no los convierte. "7° semestre"
    # se colaba entero por eso, que es la clase de fallo que no da error.
    exigidos = [int(m.group(1)) for m in re.finditer(
        r"\b(\d{1,2})\s*(?:vo|no|mo|er|o|a|°|º)?\.?\s*semestre", t)]
    exigidos += [ORDINALES[m.group(1)] for m in re.finditer(
        r"\b(" + "|".join(ORDINALES) + r")\s+semestre", t)]
    if suyo:
        for exigido in exigidos:
            if 1 <= exigido <= 12 and exigido > suyo:
                motivos.append(f"semestre: piden {exigido}o y el perfil va por {suyo}o")
                break

    # Presencial fuera de la zona base: solo descarta si perfil.py dice que no
    # hay mudanza posible.
    presencial = "presencial" in t and "desde casa" not in t and "remoto" not in t
    if presencial and POSTULACION.get("disponibilidad_mudanza") is False:
        for ciudad in ciudades_lejos():
            if ciudad in t or ciudad in (ubicacion or "").lower():
                motivos.append(f"presencial en {ciudad}: exige mudarse")
                break
    return motivos


def esta_viva(texto: str) -> bool:
    """¿La oferta sigue aceptando postulaciones?

    OCC devuelve un 404 limpio cuando cierra una vacante. Indeed no: sirve la
    pagina entera con la descripcion intacta y un aviso arriba. Quien mire el
    codigo de estado vera 200 y creera que esta viva, asi que hay que leer el
    texto. Sigue valiendo la regla de la casa: solo el cierre explicito del
    portal cuenta, nunca un 403 ni un 429.
    """
    t = (texto or "").lower()
    muertas = ("este empleo caduc", "esta vacante ha expirado", "ya no acepta postulaciones",
               "no podemos encontrar la vacante", "esta oferta ya no est",
               "el empleo ya no est", "this job has expired")
    return not any(m in t for m in muertas)


def encaje(texto: str) -> dict:
    """Cuanto de lo que pide el anuncio esta DEMOSTRADO en el perfil.

    Es la otra mitad del criterio, y la que de verdad importa. `evaluar` dice
    cuando NO tiene sentido postular; esto dice cuando SI: no basta con que la
    vacante no te descalifique, tiene que ser una donde tu CV destaque o al
    menos este a la altura de lo que piden.

    Se mide contra `HABILIDADES` de perfil.py, que trae el peso de cada una:
    lo que se puede demostrar con un entregable pesa mas que lo que se conoce
    de oidas. Mandar el CV a una vacante donde solo coincide lo barato gasta
    una bala y no gana nada.

    Con `HABILIDADES` vacio no se puede medir nada, y eso se dice
    ("sin-habilidades") en vez de descartar la vacante por floja.
    """
    from nucleo import normalizar, terminos_presentes
    from perfil import HABILIDADES

    if not HABILIDADES:
        return {"habilidades": [], "peso": 0, "fuertes": [],
                "veredicto": "sin-habilidades"}

    t = normalizar(texto or "")
    presentes = terminos_presentes(t, tuple(HABILIDADES))
    peso = sum(HABILIDADES.get(h, 0) for h in presentes)
    fuertes = sorted((h for h in presentes if HABILIDADES.get(h, 0) >= 8),
                     key=lambda h: -HABILIDADES[h])
    return {"habilidades": presentes, "peso": peso, "fuertes": fuertes,
            "veredicto": ("destaca" if fuertes and peso >= 20
                          else "equivalente" if peso >= 10
                          else "flojo")}


def cerrar(vacante_id: str, motivo: str = "404 en el portal") -> None:
    """Marca la vacante como cerrada y retira su candidatura en borrador.

    Solo se llama cuando el portal devuelve 404/410 abriendo la oferta en el
    navegador. Es la unica señal que este proyecto acepta como cierre: un 403
    o un 429 significan "no me dejan mirar", no "ya no existe", y marcarlas
    por eso quitaria oportunidades reales.

    Se comprueba en el navegador y no desde Python a proposito: OCC responde
    403 a las peticiones directas, asi que un script nunca sabria distinguir
    una vacante muerta de un bloqueo antibot.
    """
    with conexion() as con:
        con.execute("UPDATE vacantes SET ver_estado='cerrada', ver_metodo='portal', "
                    "ver_detalle=?, ver_fecha=? WHERE id=?",
                    (motivo, ahora_iso(), vacante_id))
        con.execute("DELETE FROM candidaturas WHERE vacante_id=? AND estado='borrador'",
                    (vacante_id,))


def descartar(vacante_id: str, motivo: str) -> None:
    """La oferta esta viva pero no sirve. Se anota el porque y no vuelve.

    Nace de abrir la primera candidata de OCC y encontrarse que el anuncio
    decia "Ciudad de Mexico, presencial" mientras la base la tenia en Nuevo
    Leon. El clasificador se equivoco, y sin dejar rastro del descarte esa
    misma vacante volveria a salir la primera manana tras manana.

    El motivo se guarda en texto y no como codigo: sirve para detectar
    patrones de fallo del clasificador cuando se acumulen unos cuantos.
    """
    with conexion() as con:
        con.execute("UPDATE vacantes SET descartada_motivo=?, descartada_fecha=? "
                    "WHERE id=?", (motivo, ahora_iso(), vacante_id))
        con.execute("DELETE FROM candidaturas WHERE vacante_id=? AND estado='borrador'",
                    (vacante_id,))


# El carril: las areas PRIORITARIAS de las activas (ver `areas.py` y
# `ULTRACHAMBA_AREAS`). En tecnologia, `ti-general` queda fuera por defecto a
# proposito: un puesto generico paga las facturas pero no construye el perfil
# que se persigue, y cada postulacion gastada ahi es una que no se manda donde
# importa. Se cambia con la marca `prioritaria` del area.
def areas_suyas() -> tuple[str, ...]:
    return tuple(areas.valores_prioritarios())


# EL UNICO SITIO donde se define "esta vacante es viable para el perfil".
#
# Existia por duplicado: `ranking()` aqui y `elegir()` en cola.py, con
# criterios distintos. La cola diaria llego a proponer dos vacantes con "+2
# anios de experiencia" en el anuncio, porque su filtro no miraba esa columna.
#
# Dos definiciones de la misma decision acaban contradiciendose. Esta se
# importa desde los dos sitios; si cambia un criterio, cambia en uno solo. La
# parte geografica sale de la zona base (`areas.sql_viable_zona()`) y solo se
# aplica si el perfil declara que no hay mudanza posible; el tope de anios sale
# de `anios_experiencia`; y el descarte por titulo solo se aplica si el perfil
# declara que no hay titulo.
_SQL_NO_TITULADO = ("AND LOWER(COALESCE(req_educacion,'')) NOT LIKE '%titulado%'"
                    if POSTULACION.get("titulado") is False else "")
_SQL_ZONA = (areas.sql_viable_zona()
             if POSTULACION.get("disponibilidad_mudanza") is False else "1=1")

SQL_VIABLE = f"""
      (ver_estado IS NULL OR ver_estado != 'cerrada')
  AND (aplicada IS NULL OR aplicada = 0)
  AND descartada_motivo IS NULL
  AND elegible_mx = 1
  AND (anios_exigidos IS NULL OR anios_exigidos <= {tope_anios()})
  {_SQL_NO_TITULADO}
  AND {_SQL_ZONA}
"""


def ranking(bolsa: str | None = None, limite: int = 15,
            areas_objetivo: tuple[str, ...] | None = None,
            solo_bolsas: bool = False) -> list[dict]:
    """Ordena las vacantes por ENCAJE, no por puntuacion del clasificador.

    Con `solo_bolsas=False` (por defecto) entran TODAS las fuentes.

    Ceguera detectada preguntando "¿y las remotas?". Este modulo nacio para
    OCC e Indeed y filtraba por sus
    dominios, asi que de las 57 vacantes remotas de su carril **solo veia 2**.
    Las otras 55 --Greenhouse, Lever, Ashby, iCIMS, SuccessFactors, LinkedIn--
    no existian para el sistema.

    Importa mas de lo que parece: el mercado presencial de una zona se puede
    agotar en una tarde (una sola vacante viable), mientras el remoto ni se
    habia mirado.

    Aviso al usarlas: en esas fuentes no hay boton "Postularme" de una bolsa,
    sino el ATS de cada empresa. Muchos exigen CREAR CUENTA, y eso este
    sistema no lo hace nunca; ahi llega hasta dejar el formulario preparado.

    Nace de un dato incomodo del 24 de agosto de 2026: de las seis mejores por
    puntuacion, cinco eran inservibles (dos cerradas, una en CDMX presencial,
    otra en Guadalajara pidiendo 7o semestre, otra sin sueldo y una que pedia
    +3 anios de experiencia). La puntuacion mide "se parece a lo que busca",
    no "puede postular y ademas destaca".

    Aprovecha la descripcion que ya esta en la base: filtrar mil anuncios aqui
    cuesta segundos, y abrir mil paginas en el navegador costaria una tarde.
    Lo que se abre despues es solo la lista corta, y ahi se comprueba de nuevo
    contra el anuncio en vivo, porque la descripcion guardada puede estar
    recortada.
    """
    areas_objetivo = tuple(areas_objetivo or areas_suyas())
    dominios = ([BOLSAS[bolsa]["dominio"]] if bolsa
                else [b["dominio"] for b in BOLSAS.values()])
    condicion = (" OR ".join("url LIKE ?" for _ in dominios)
                 if (solo_bolsas or bolsa) else "1=1")
    en_areas, _ = areas.sql_in("area", list(areas_objetivo))

    with conexion() as con:
        filas = [dict(f) for f in con.execute(f"""
            SELECT id, titulo, empresa, url, ubicacion, score, descripcion
            FROM vacantes
            WHERE score >= 40 AND elegible_mx = 1
              AND {en_areas}
              AND ({condicion})
              -- Lo que la base YA sabe y el filtro de texto no puede ver,
              -- porque `descripcion` se guarda recortada a 8.000 caracteres y
              -- los requisitos suelen ir al final. Sin estas tres lineas el
              -- ranking se llenaba de "Lider SOC" y "Consultant Mid level" en
              -- Ciudad de Mexico: puestos reales, pero no los suyos.
              AND nivel IN ('practicas', 'junior')
              AND (anios_exigidos IS NULL OR anios_exigidos <= {tope_anios()})
              -- La ficha manda sobre la tarjeta. `ubicacion_ficha` sale del
              -- JSON-LD de la propia bolsa; `ubicacion` sale de raspar la
              -- tarjeta del listado y durante meses dijo "Nuevo Leon, Mexico"
              -- por defecto. De 12 vacantes enriquecidas, 11 decian Nuevo Leon
              -- y NINGUNA estaba en Nuevo Leon. El criterio de zona vive en
              -- `areas.sql_viable_zona()`, y solo si no hay mudanza posible.
              AND {_SQL_ZONA}
              -- "Universitario titulado" es el descarte mas limpio que existe:
              -- lo etiqueta la propia bolsa. Solo si el perfil no es titulado.
              {_SQL_NO_TITULADO}
              AND (ver_estado IS NULL OR ver_estado != 'cerrada')
              AND (aplicada IS NULL OR aplicada = 0)
              AND descartada_motivo IS NULL
              AND id NOT IN (SELECT vacante_id FROM candidaturas
                             WHERE vacante_id IS NOT NULL)""",
            [*areas_objetivo, *([f"%{d}%" for d in dominios]
                       if (solo_bolsas or bolsa) else [])])]

    salida = []
    for v in filas:
        campos = {k: v[k] for k in
                  ("id", "titulo", "empresa", "url", "ubicacion", "score")}
        desc = v.get("descripcion") or ""

        # Sin descripcion NO se descarta. Exigirla dejaba fuera 143 de 215
        # vacantes viables el 24-ago-2026 -- dos de cada tres -- y sin avisar,
        # que es la peor manera de perderlas. Lo que no se puede evaluar se
        # marca para abrirlo en el navegador, no se tira.
        if len(desc) < 200:
            salida.append({**campos, "habilidades": [], "peso": 0, "fuertes": [],
                           "veredicto": "sin-descripcion"})
            continue

        texto = f"{v['titulo']} {desc}"
        if not esta_viva(texto):
            continue
        if evaluar(texto, v.get("ubicacion") or ""):
            continue
        e = encaje(texto)
        if e["veredicto"] == "flojo":
            continue
        salida.append({**campos, **e})

    # La ubicacion generica no es una ubicacion. Medido el 24-ago-2026: 443 de
    # las 776 vacantes de OCC (57%) dicen exactamente "Nuevo Leon, Mexico",
    # que es el valor del FILTRO DE BUSQUEDA, no donde esta el trabajo. Las
    # tres que se abrieron con esa etiqueta estaban en Ciudad de Mexico,
    # Guadalajara y Aguascalientes.
    #
    # No se descartan --a veces si estan en Monterrey-- pero van despues: una
    # oferta que dice "Apodaca, Nuevo Leon" ya esta verificada por el anuncio,
    # y abrir esas primero sube el acierto sin perder nada.
    generica = ("nuevo leon, mexico", "nuevo león, méxico", "mexico", "méxico", "")

    def fiable(v) -> int:
        return 0 if (v.get("ubicacion") or "").strip().lower() not in generica else 1

    orden = {"destaca": 0, "equivalente": 1, "sin-descripcion": 2, "sin-habilidades": 2}
    salida.sort(key=lambda x: (orden[x["veredicto"]], fiable(x), -x["peso"], -x["score"]))
    return salida[:limite]


def paquete(vacante: dict) -> dict:
    """Todo lo necesario para rellenar el formulario, y lo que falta.

    Devolver los huecos junto al resto es deliberado: quien lo lea ve de una
    vez si puede seguir o si tiene que preguntar antes de abrir el navegador.
    """
    url = vacante.get("url") or ""
    bolsa = next((n for n, b in BOLSAS.items() if b["dominio"] in url), None)

    from pathlib import Path
    raiz = Path(__file__).resolve().parent.parent
    pdfs = sorted(raiz.glob("*CV*.pdf")) or sorted(raiz.glob("*.pdf"))

    return {
        "vacante": {k: vacante.get(k) for k in
                    ("id", "titulo", "empresa", "url", "ubicacion", "score", "modalidad")},
        "bolsa": bolsa,
        "via": BOLSAS[bolsa]["via"] if bolsa else "portal",
        "cv": str(pdfs[0]) if pdfs else None,
        "respuestas": {k: v for k, v in POSTULACION.items() if v is not None},
        "faltan": huecos_de_postulacion(),
    }


def registrar(vacante: dict, via: str) -> str:
    """Anota la candidatura como borrador. Enviada solo la marca el acuse."""
    ident = _id("portal", vacante["id"])
    ahora = ahora_iso()
    with conexion() as con:
        con.execute("""
            INSERT INTO candidaturas (id, vacante_id, via, asunto, estado,
                                      notas, creada, actualizada)
            VALUES (?,?,?,?,'borrador',?,?,?)
            ON CONFLICT(id) DO UPDATE SET actualizada=excluded.actualizada""",
            (ident, vacante["id"], via, vacante.get("empresa") or "",
             f"postulacion por portal: {vacante.get('url','')[:120]}", ahora, ahora))
    return ident


def confirmar() -> list[dict]:
    """Busca en el correo los acuses de las bolsas y marca lo confirmado.

    Esta es la unica prueba que el sistema acepta de que una postulacion
    existe. Pulsar Enviar y ver un "gracias" en pantalla no basta: ya hubo
    tres ocasiones en este proyecto en que algo parecia hecho y no lo estaba.
    """
    import correo_gmail as gmail
    import seguimiento as seg

    if not gmail.puede_leer():
        raise SystemExit("falta el permiso de lectura: python correo_gmail.py --ampliar")

    s = gmail._servicio()
    confirmadas = []

    with conexion() as con:
        pendientes = [dict(r) for r in con.execute(
            "SELECT id, asunto, notas, via, vacante_id FROM candidaturas "
            "WHERE estado='pendiente-acuse' AND via LIKE 'portal-%'")]
        if not pendientes:
            return []

        for nombre, b in BOLSAS.items():
            r = s.users().messages().list(
                userId="me", q=f'{b["acuse"]} newer_than:30d', maxResults=40).execute()
            for m in r.get("messages", []):
                d = s.users().messages().get(
                    userId="me", id=m["id"], format="metadata",
                    metadataHeaders=["Subject", "From"]).execute()
                texto = _normalizar(seg._cabeceras(d).get("subject", "") + " " +
                                    (d.get("snippet") or ""))
                for c in pendientes:
                    empresa = _normalizar(c["asunto"])
                    # El acuse nombra la empresa o el puesto; con la empresa
                    # basta y es lo que menos varia entre plantillas.
                    if empresa and len(empresa) > 3 and empresa in texto:
                        fecha = seg._fecha(d["internalDate"])[:10]
                        con.execute(
                            "UPDATE candidaturas SET estado='enviada', enviada=?, "
                            "hilo_gmail=COALESCE(hilo_gmail, ?), actualizada=? WHERE id=?",
                            (fecha, d["threadId"], ahora_iso(), c["id"]))
                        con.execute("UPDATE vacantes SET aplicada=1 WHERE id=?",
                                    (c.get("vacante_id"),)) if c.get("vacante_id") else None
                        confirmadas.append({"id": c["id"], "empresa": c["asunto"],
                                            "bolsa": nombre, "fecha": fecha})
                        pendientes.remove(c)
                        break
    return confirmadas


def _imprimir(p: dict) -> None:
    v = p["vacante"]
    print("=" * 70)
    print(f"  {v['titulo']}")
    print(f"  {v['empresa']}  |  {v['ubicacion']}  |  puntuacion {v['score']:.0f}")
    print(f"  {v['url']}")
    print(f"  bolsa: {p['bolsa']}   via: {p['via']}")
    print("=" * 70)
    print("  CV a adjuntar:", p["cv"] or "NO ENCONTRADO")
    print("  Respuestas que el sistema puede dar solo:")
    for k, val in p["respuestas"].items():
        print(f"    {k:28} {val}")
    if p["faltan"]:
        print()
        print("  FALTAN (no se inventan; decidelas tu una vez y quedan guardadas):")
        for k in p["faltan"]:
            print(f"    - {k}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Postular por las bolsas")
    ap.add_argument("--siguiente", action="store_true")
    ap.add_argument("--occ", action="store_true")
    ap.add_argument("--indeed", action="store_true")
    ap.add_argument("--confirmar", action="store_true")
    ap.add_argument("--n", type=int, default=1)
    a = ap.parse_args()

    bolsa = "occ" if a.occ else "indeed" if a.indeed else None

    if a.confirmar:
        hechas = confirmar()
        if not hechas:
            print("sin acuses nuevos")
        for c in hechas:
            print(f"  CONFIRMADA {c['fecha']} | {c['bolsa']:6} | {c['empresa']}")
    elif a.siguiente:
        elegidas = elegir(bolsa, a.n)
        if not elegidas:
            print("no hay vacantes pendientes en esa bolsa")
        for v in elegidas:
            p = paquete(v)
            _imprimir(p)
            print("\n  registrada como borrador:", registrar(v, p["via"]))
    else:
        faltan = huecos_de_postulacion()
        print("listo para postular." if not faltan
              else f"faltan datos en perfil.py: {', '.join(faltan)}")
