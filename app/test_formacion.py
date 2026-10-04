"""
Casos del carril de formacion. Se ejecutan; no son documentacion.

POR QUE ESTE ARCHIVO EXISTE. Los dos filtros de este carril --el de
elegibilidad y el de ruido-- son filtros de DESCARTE, y un filtro de descarte
falla en silencio: no lanza error, simplemente esconde algo bueno. La cicatriz
29 lo dice entero: "promocion" tambien significa generacion de egresados en
Mexico, y ese filtro tiraba la convocatoria de MEXIA sin que nadie se enterara.

Por eso la mitad de los casos de aqui son CONTROLES NEGATIVOS: cosas que TIENEN
que sobrevivir al filtro. Ya sirvieron una vez el mismo dia en que se
escribieron -- una regla de "titulo demasiado corto" tiraba "Cybersecurity", el
enlace al Google Cybersecurity Certificate.

    python test_formacion.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

# Las reglas de este carril dependen del area, la zona y el perfil. Los casos
# se escribieron para tecnologia, la zona de Monterrey y un perfil de
# estudiante; se fijan aqui para que el resultado no dependa de tu `.env` ni de
# tu `perfil.py`. Solo cambia la memoria de esta ejecucion, nunca un archivo.
os.environ["ULTRACHAMBA_AREAS"] = "tecnologia"
os.environ["ULTRACHAMBA_ZONA"] = "monterrey"

import perfil                                           # noqa: E402

perfil.POSTULACION.update({
    "semestre": 5, "nivel_estudios": "Licenciatura en curso", "titulado": False,
    "anios_experiencia": 0, "disponibilidad_mudanza": False,
    "carta_de_la_universidad": False, "institucion_publica": True,
})

from formacion import ESTADOS_CUENTAN, evaluar          # noqa: E402
from fuentes_cursos import buscar_cierre, es_ruido      # noqa: E402

fallos: list[str] = []
hechos = 0


def caso(descripcion: str, obtenido, esperado) -> None:
    global hechos
    hechos += 1
    if obtenido != esperado:
        fallos.append(f"{descripcion}\n      esperado: {esperado!r}\n      obtenido: {obtenido!r}")


def elegibilidad(**campos) -> int | None:
    return evaluar(campos)[0]


# ---------------------------------------------------------------------------
# ELEGIBILIDAD: lo que debe quedar FUERA
# ---------------------------------------------------------------------------
caso("exige no estar estudiando -> fuera (es el caso de Jovenes Construyendo el Futuro)",
     elegibilidad(nombre="Beca de capacitacion",
                  requisitos="Ser joven de 18 a 29 anos y no estar estudiando"),
     0)

caso("pide titulo y cedula -> fuera (el perfil de prueba va por 5o semestre)",
     elegibilidad(nombre="Diplomado en seguridad",
                  requisitos="Dirigido a titulados con cedula profesional"),
     0)

caso("estancia posdoctoral -> fuera (nivel posgrado)",
     elegibilidad(nombre="Estancias Posdoctorales por Mexico",
                  institucion="Secihti"),
     0)

caso("estancia sabatica -> fuera",
     elegibilidad(nombre="Estancias Sabaticas", institucion="Secihti"), 0)

caso("rotaciones medicas -> fuera (otro campo del saber)",
     elegibilidad(nombre="Rotaciones Medicas y Estancias Tecnicas",
                  institucion="Secihti"),
     0)

caso("presencial en otra ciudad -> fuera (no puede mudarse)",
     elegibilidad(nombre="Bootcamp de ciberseguridad", modalidad="presencial",
                  sede="Ciudad de Mexico"),
     0)

caso("lista carreras y ninguna es afin -> fuera",
     elegibilidad(nombre="Curso de residuos", carreras="Medicina, Enfermeria, Nutricion"),
     0)

# ---------------------------------------------------------------------------
# ELEGIBILIDAD: CONTROLES NEGATIVOS -- esto NO se puede descartar
# ---------------------------------------------------------------------------
caso("CONTROL: IA aplicada a la salud SIGUE siendo suya (lleva 'salud' dentro)",
     elegibilidad(nombre="Machine Learning aplicado a la salud",
                  descripcion="Curso en linea de aprendizaje automatico",
                  modalidad="linea", gratis="total") != 0,
     True)

caso("CONTROL: ciberseguridad en el sector juridico sigue siendo suya",
     elegibilidad(nombre="Ciberseguridad para el sector juridico",
                  modalidad="linea", gratis="total") != 0,
     True)

caso("CONTROL: 'titulados Y estudiantes' no descarta a un estudiante",
     elegibilidad(nombre="Curso abierto",
                  requisitos="Dirigido a titulados y estudiantes de ingenieria",
                  modalidad="linea", gratis="total") != 0,
     True)

caso("CONTROL: presencial en Monterrey no descarta",
     elegibilidad(nombre="Taller de redes", modalidad="presencial-mty",
                  sede="Monterrey, Nuevo Leon", gratis="total") != 0,
     True)

# ---------------------------------------------------------------------------
# ELEGIBILIDAD: lo que debe quedar DENTRO, y lo que no se puede saber
# ---------------------------------------------------------------------------
caso("admite estudiantes de universidades publicas -> dentro (el perfil de prueba estudia en una)",
     elegibilidad(nombre="Programa de innovacion",
                  requisitos="Estudiantes de universidades publicas"),
     1)

caso("lista carreras afines -> dentro",
     elegibilidad(nombre="Programa de becas",
                  carreras="Ingenieria en Sistemas Computacionales y areas afines"),
     1)

caso("en linea y gratis sin requisitos escritos -> dentro",
     elegibilidad(nombre="Curso de Python", modalidad="linea", gratis="total"),
     1)

caso("pide promedio minimo -> NO SE SABE (el promedio no esta en perfil.py)",
     elegibilidad(nombre="Beca de excelencia",
                  requisitos="Promedio minimo de 9.0 y carta de motivos"),
     None)

caso("pide rango de edad -> NO SE SABE (la edad no esta en perfil.py)",
     elegibilidad(nombre="Programa joven",
                  requisitos="Jovenes entre 18 y 24 anos"),
     None)

caso("pide carta de la universidad -> NO SE SABE (hoy no la tiene)",
     elegibilidad(nombre="Practicas de verano",
                  requisitos="Carta de la universidad que avale al estudiante"),
     None)

caso("la ficha no dice nada -> NO SE SABE, nunca un 'no' inventado",
     elegibilidad(nombre="Programa sin descripcion"),
     None)

# ---------------------------------------------------------------------------
# DE UN TITULO NO SE DEDUCE QUIEN PUEDE ENTRAR
#
# El fallo que encontro el `jefe` el 4-sep-2026: los candidatos del vigilante
# heredaban `modalidad` y `gratis` de la constante SEMILLAS, asi que un curso
# INVENTADO salia "cabe" en once de las doce semillas. Estos casos son el
# control que faltaba -- si alguien vuelve a hacer que un titulo solo baste
# para decir que si, fallan aqui.
# ---------------------------------------------------------------------------
caso("un candidato del que solo tenemos el titulo NO es elegible: es 'por confirmar'",
     elegibilidad(nombre="Xyzzy Programa Zeta", origen="semilla:fortinet",
                  modalidad="linea", gratis="total", publico="abierto"),
     None)

caso("...y eso vale igual para uno que suena perfecto",
     elegibilidad(nombre="Becas Nacionales", origen="semilla:conahcyt",
                  modalidad="linea", gratis="beca", publico="estudiantes"),
     None)

caso("pero si el TITULO ya dice que no, se descarta sin abrir la pagina",
     elegibilidad(nombre="Estancias Posdoctorales por Mexico",
                  origen="semilla:conahcyt", modalidad="linea", gratis="beca"),
     0)

caso("CONTROL: si SI se leyeron los requisitos, el veredicto vuelve a ser firme",
     elegibilidad(nombre="Programa X", origen="semilla:conahcyt",
                  requisitos="Dirigido a estudiantes de universidades publicas",
                  modalidad="linea", gratis="total"),
     1)

# ---------------------------------------------------------------------------
# LO QUE PERFIL.PY NO DICE NO DESCARTA
#
# En la version general el perfil llega vacio. Un bloqueo que depende de un
# dato ausente deja el veredicto "por confirmar"; nunca un "no" inventado.
# ---------------------------------------------------------------------------
def con_perfil(cambios: dict, **campos):
    """Evalua con el perfil de prueba alterado, y lo restaura siempre."""
    previo = {k: perfil.POSTULACION.get(k) for k in cambios}
    perfil.POSTULACION.update(cambios)
    try:
        return evaluar(campos)[0]
    finally:
        perfil.POSTULACION.update(previo)


def con_areas(valor: str, **campos):
    """Evalua con otras areas activas, y restaura las del test."""
    previo = os.environ["ULTRACHAMBA_AREAS"]
    os.environ["ULTRACHAMBA_AREAS"] = valor
    try:
        return evaluar(campos)[0]
    finally:
        os.environ["ULTRACHAMBA_AREAS"] = previo


caso("perfil sin 'titulado': pedir titulo queda POR CONFIRMAR",
     con_perfil({"titulado": None}, nombre="Diplomado en seguridad",
                requisitos="Dirigido a titulados con cedula profesional"),
     None)
caso("perfil sin semestre ni nivel: 'no estar estudiando' queda POR CONFIRMAR",
     con_perfil({"semestre": None, "nivel_estudios": None, "titulado": None},
                nombre="Beca de capacitacion",
                requisitos="Ser joven y no estar estudiando"),
     None)
caso("perfil sin 'disponibilidad_mudanza': presencial lejos queda POR CONFIRMAR",
     con_perfil({"disponibilidad_mudanza": None}, nombre="Bootcamp de ciberseguridad",
                modalidad="presencial", sede="Ciudad de Mexico"),
     None)
caso("perfil sin 'institucion_publica': exigirla queda POR CONFIRMAR",
     con_perfil({"institucion_publica": None, "semestre": None, "nivel_estudios": None},
                nombre="Programa publico", requisitos="Solo universidades publicas"),
     None)
caso("CONTROL: a quien ya se titulo, 'no estar estudiando' no le descarta",
     con_perfil({"titulado": True, "semestre": None,
                 "nivel_estudios": "Licenciatura terminada"},
                nombre="Beca de capacitacion", requisitos="no estar estudiando",
                modalidad="linea", gratis="total") != 0,
     True)

# El mismo curso cambia de veredicto con el area: lo ajeno depende de areas.py.
caso("tecnologia: un diplomado de derecho es de otro campo",
     con_areas("tecnologia", nombre="Diplomado en derecho corporativo",
               modalidad="linea", gratis="total"),
     0)
caso("derecho: el mismo diplomado es de su area",
     con_areas("derecho", nombre="Diplomado en derecho corporativo",
               modalidad="linea", gratis="total") != 0,
     True)
caso("salud: unas rotaciones medicas ya no son 'otro campo'",
     con_areas("salud", nombre="Rotaciones Medicas y Estancias Tecnicas",
               institucion="Secihti") != 0,
     True)

# ---------------------------------------------------------------------------
# FILTRO DE RUIDO
# ---------------------------------------------------------------------------
caso("un correo no es un curso", es_ruido("innovationcampus@udem.edu.mx")[0], True)
caso("un directorio de centros no es un curso",
     es_ruido("Authorized Training Center")[0], True)
caso("una portada no es un curso", es_ruido("Overview")[0], True)
caso("una demo comercial no es un curso", es_ruido("FREE PRODUCT DEMO")[0], True)

caso("un encabezado de seccion no es un curso", es_ruido("Cursos")[0], True)
caso("...ni aunque este en ingles", es_ruido("Training")[0], True)

caso("CONTROL: 'Cybersecurity' SOBREVIVE (es el certificado de Google)",
     es_ruido("Cybersecurity")[0], False)
caso("CONTROL: 'IT Support' sobrevive (10 caracteres, y es pista de Google)",
     es_ruido("IT Support")[0], False)
caso("CONTROL: 'Becas Nacionales' no cae por llevar 'becas' dentro",
     es_ruido("Becas Nacionales")[0], False)
caso("CONTROL: un titulo compuesto con 'training' sobrevive",
     es_ruido("Free Training & On-demand Labs")[0], False)
caso("CONTROL: una convocatoria de ingreso a un programa sobrevive",
     es_ruido("Convocatoria de Ingreso al Programa")[0], False)
caso("CONTROL: formacion gratuita de fabricante sobrevive",
     es_ruido("Free Training & On-demand Labs")[0], False)
caso("CONTROL: 'Becas Nacionales' sobrevive",
     es_ruido("Becas Nacionales")[0], False)

# ---------------------------------------------------------------------------
# FECHAS DE CIERRE: una fecha suelta no es un plazo
# ---------------------------------------------------------------------------
caso("cierre declarado en espanol",
     buscar_cierre("Las inscripciones cierran el 18 de septiembre de 2026."),
     "2026-09-18")
caso("fecha limite en formato corto",
     buscar_cierre("Fecha limite: 30/09/2026 a las 23:59"),
     "2026-09-30")
caso("CONTROL: una fecha de publicacion NO es un cierre",
     buscar_cierre("Publicado el 3 de agosto de 2026 por la coordinacion."),
     None)
caso("CONTROL: sin ano no se adivina (en septiembre, 'febrero' es del ano que viene)",
     buscar_cierre("El registro estara abierto hasta el 15 de febrero."),
     None)

# ---------------------------------------------------------------------------
# LA METRICA: lista blanca, cicatriz 26
# ---------------------------------------------------------------------------
caso("un borrador NO cuenta como inscripcion enviada",
     "borrador" in ESTADOS_CUENTAN, False)
caso("una aprobada tampoco: aprobar no es haber salido",
     "aprobada" in ESTADOS_CUENTAN, False)
caso("una inscrita si cuenta", "inscrita" in ESTADOS_CUENTAN, True)


# ---------------------------------------------------------------------------
# EL CICLO COMPLETO, contra la base de verdad.
#
# Se hace con un curso ficticio que se borra al terminar, y no con uno real,
# por una razon que no es de estilo: marcar "inscrita" una inscripcion que
# nadie hizo mete una mentira en la unica fuente de verdad, y la metrica
# de este carril es justo ese numero. Un test que ensucia el dato que mide no
# es un test.
# ---------------------------------------------------------------------------
def probar_ciclo() -> None:
    from almacen import conexion
    from formacion import (aprobar, cifras, marcar_enviada, pendientes,
                           preparar, rechazar)
    from nucleo import ahora_iso

    ID = "zzz-test-ciclo"
    with conexion() as con:
        con.execute("""INSERT OR REPLACE INTO cursos
            (id, nombre, institucion, url, area, modalidad, gratis,
             convocatoria, estado_revision, elegible, primera_vez, ultima_vez)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ID, "Curso de prueba del ciclo", "Ninguna", "https://example.org",
             "ia", "linea", "total", "abierta", "aceptado", 1,
             ahora_iso(), ahora_iso()))
    try:
        antes = cifras()["inscripciones_enviadas"]

        p = preparar(ID, via="formulario")
        caso("preparar deja un borrador", p.get("estado"), "borrador")
        iid = p["id"]

        caso("un borrador NO mueve la metrica",
             cifras()["inscripciones_enviadas"], antes)
        caso("y aparece esperando el visto bueno",
             any(x["id"] == iid for x in pendientes()), True)

        caso("aprobar lo deja aprobada", aprobar(iid).get("estado"), "aprobada")
        caso("aprobar TAMPOCO mueve la metrica: aprobar no es haber salido",
             cifras()["inscripciones_enviadas"], antes)

        caso("aprobar dos veces no cuela (el cerrojo del UPDATE)",
             "error" in aprobar(iid), True)

        caso("marcar enviada si la mueve",
             marcar_enviada(iid, "folio de prueba").get("estado"), "inscrita")
        caso("la metrica sube exactamente uno",
             cifras()["inscripciones_enviadas"], antes + 1)

        caso("un rechazo sin motivo se rechaza a si mismo",
             "error" in rechazar(iid, "   "), True)
    finally:
        with conexion() as con:
            con.execute("DELETE FROM inscripciones WHERE curso_id=?", (ID,))
            con.execute("DELETE FROM cursos WHERE id=?", (ID,))


probar_ciclo()


if __name__ == "__main__":
    print(f"\n{hechos} casos del carril de formacion")
    if fallos:
        print(f"\nFALLARON {len(fallos)}:\n")
        for f in fallos:
            print("  -", f)
        sys.exit(1)
    print("todos pasan\n")
