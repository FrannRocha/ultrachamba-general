"""
Exporta las vacantes a texto plano para subirlas a NotebookLM.

Para que sirve. El panel responde preguntas de filtro ("dame las de mi zona
sin mudanza"), pero no responde preguntas transversales sobre el CONTENIDO de
los anuncios: que piden de verdad, que se repite, que es indispensable y que
solo "deseable". Eso exige leer 1.990 descripciones, que no caben en la
memoria de trabajo de ningun agente de golpe.

NotebookLM si puede: se le suben estos archivos y responde CITANDO el anuncio
concreto del que sale cada afirmacion. La diferencia con contar palabras
—que este sistema ya hace en `medir_habilidades()`— es que distingue
"indispensable" de "deseable" y entiende la frase alrededor del termino.

Privacidad. Aqui NO va nada del perfil. NotebookLM exige compartir el
cuaderno con "cualquiera con el enlace", asi que solo se exporta texto que ya
era publico: anuncios de empleo publicados en internet. El CV, el correo y el
telefono NO se suben nunca.

Uso:
    python exportar_corpus.py            # todas las areas
    python exportar_corpus.py --minimo 55
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import areas
from almacen import conexion

SALIDA = Path(__file__).resolve().parent.parent / "corpus-notebooklm"

# Un archivo por area: NotebookLM cita la fuente, y separarlas hace que la cita
# diga ya de que familia venia el anuncio. Los grupos salen de las areas
# activas (`areas.grupos_corpus()`) y sus archivos empiezan por `area-`.

# Sin descripcion no hay nada que leer: esas vacantes solo aportarian ruido.
MINIMO_DESCRIPCION = 200

# Tope por descripcion. Existe por una razon muy concreta: NotebookLM enlaza
# cada fuente por identificador, asi que cada documento que se añade al corpus
# hay que enlazarlo A MANO en el cuaderno. Manteniendo el corpus dentro de los
# documentos ya enlazados, la sincronizacion sigue siendo automatica de
# verdad; si crece, deja de serlo hasta que alguien entre a la interfaz.
#
# Que se pierde: la mediana de descripcion son 3.250 caracteres, asi que la
# mitad de los anuncios no se toca. Lo que se recorta de los largos es la cola
# —beneficios, texto legal de igualdad de oportunidades, "sobre nosotros"—,
# nunca los requisitos, que van siempre arriba. Se corta en frase completa
# para que no queden citas partidas a media palabra.
MAXIMO_DESCRIPCION = 4000


def _campo(v: dict, clave: str, por_defecto: str = "no indicado") -> str:
    valor = (v.get(clave) or "").strip()
    return valor or por_defecto


def _recortar(texto: str, tope: int = MAXIMO_DESCRIPCION) -> str:
    """Corta en la ultima frase completa antes del tope.

    Cortar a media palabra produciria citas mutiladas en NotebookLM, que es
    justo lo que hace inutil una cita. Se busca hacia atras el final de frase
    mas cercano; si no hay ninguno razonable, se corta en el ultimo espacio.
    """
    texto = (texto or "").strip()
    if len(texto) <= tope:
        return texto
    recorte = texto[:tope]
    for marca in (". ", ".\n", "; ", " - ", " · "):
        pos = recorte.rfind(marca)
        if pos > tope * 0.6:          # solo si no amputa mas de la cuenta
            return recorte[:pos + 1].rstrip() + " […]"
    pos = recorte.rfind(" ")
    return (recorte[:pos] if pos > 0 else recorte).rstrip() + " […]"


def _ficha(v: dict) -> str:
    """Un bloque por vacante, con encabezado para que la cita sea legible."""
    anios = ""
    try:
        datos = json.loads(v.get("anios_exigidos") or "null")
        if isinstance(datos, dict) and datos.get("minimo") is not None:
            anios = f"\nAÑOS DE EXPERIENCIA EXIGIDOS: {datos['minimo']}"
    except (json.JSONDecodeError, TypeError):
        pass

    return f"""
================================================================================
VACANTE: {_campo(v, 'titulo', 'sin titulo')}
EMPRESA: {_campo(v, 'empresa')}
UBICACION: {_campo(v, 'ubicacion')}
MODALIDAD: {_campo(v, 'modalidad')}
NIVEL: {_campo(v, 'nivel')}
AREA: {_campo(v, 'area')}
PUBLICADA: {_campo(v, 'publicado', 'la fuente no lo dice')}
FUENTE: {_campo(v, 'fuente')}
SALARIO: {_campo(v, 'salario', 'no publicado')}
ENLACE: {_campo(v, 'url')}{anios}
--------------------------------------------------------------------------------
{_recortar(v.get('descripcion') or '')}
"""


def exportar(minimo_score: float = 40.0) -> dict:
    SALIDA.mkdir(exist_ok=True)
    resumen = {}

    with conexion() as con:
        columnas = {r[1] for r in con.execute("PRAGMA table_info(vacantes)")}
        campos = [c for c in ("id", "titulo", "empresa", "ubicacion", "modalidad",
                              "nivel", "area", "publicado", "fuente", "url",
                              "salario", "descripcion", "score", "anios_exigidos", "ver_estado")
                  if c in columnas]
        # Sin esto, un cambio de nombre de columna vacia el campo en silencio y
        # el corpus sale con 1.266 enlaces "no indicado", como ya paso una vez.
        faltan = {"titulo", "empresa", "url", "descripcion"} - set(campos)
        assert not faltan, f"la tabla vacantes no tiene estas columnas: {faltan}"
        filas = con.execute(f"""
            SELECT {', '.join(campos)} FROM vacantes
            WHERE score >= ? AND elegible_mx = 1 AND area != 'fuera'
              AND (nivel IS NULL OR nivel != 'excluido')
            ORDER BY score DESC""", (minimo_score,)).fetchall()

    porarea: dict[str, list[dict]] = {}
    for f in filas:
        v = dict(f)
        if len((v.get("descripcion") or "").strip()) < MINIMO_DESCRIPCION:
            continue
        porarea.setdefault(v["area"], []).append(v)

    for nombre, titulo, valores in areas.grupos_corpus():
        vacantes = [v for a in valores for v in porarea.get(a, [])]
        if not vacantes:
            continue
        # La cabecera decia "todas verificadas como abiertas", y era falso: el
        # SELECT filtra por score, elegibilidad, area y nivel, NUNCA por estado
        # de verificacion. NotebookLM cita esa frase textualmente porque esta
        # escrita en su fuente, asi que afirmaba una frescura que nadie
        # respaldaba. Ahora se dice lo que de verdad se sabe, y se estampa la
        # fecha para que cualquier respuesta delate su propia antiguedad.
        from datetime import datetime
        sellado = datetime.now().strftime("%Y-%m-%d %H:%M")
        vivas = sum(1 for v in vacantes if (v.get("ver_estado") or "") == "viva")
        cabecera = f"""{titulo.upper()}
Corpus generado por ULTRA CHAMBA para consulta en NotebookLM.
INSTANTANEA DEL {sellado}. Si hoy es mucho despues de esa fecha, estos datos
estan viejos y hay que decirlo al responder.

{len(vacantes)} vacantes seleccionadas por encajar con el perfil (puntuacion,
area, nivel y elegibilidad desde Mexico). De ellas, {vivas} tienen su ficha
comprobada como abierta en la fecha de arriba; el resto NO se ha comprobado, y
una vacante puede cerrarse en cualquier momento sin aviso.

Cada bloque empieza con "VACANTE:" e incluye empresa, ubicacion y enlace, para
que cualquier respuesta pueda rastrearse hasta el anuncio real.

Todo este texto proviene de anuncios de empleo publicados en internet. No
contiene datos personales de nadie.
"""
        cuerpo = cabecera + "".join(_ficha(v) for v in vacantes)
        destino = SALIDA / f"{nombre}.txt"
        destino.write_text(cuerpo, encoding="utf-8")
        palabras = len(cuerpo.split())
        resumen[nombre] = {"vacantes": len(vacantes), "palabras": palabras,
                           "archivo": str(destino)}
        # NotebookLM admite 500.000 palabras por fuente en la cuenta gratuita.
        if palabras > 480_000:
            resumen[nombre]["aviso"] = "cerca del limite de NotebookLM: conviene partirlo"

    return resumen


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--minimo", type=float, default=40.0,
                   help="score minimo para incluir la vacante (por defecto 40)")
    args = p.parse_args()

    res = exportar(args.minimo)
    total_v = sum(r["vacantes"] for r in res.values())
    total_p = sum(r["palabras"] for r in res.values())
    print(f"corpus en {SALIDA}")
    for nombre, r in res.items():
        aviso = f"  <- {r['aviso']}" if "aviso" in r else ""
        print(f"  {nombre:32} {r['vacantes']:5} vacantes  {r['palabras']:8,} palabras{aviso}")
    print(f"  {'TOTAL':32} {total_v:5} vacantes  {total_p:8,} palabras")
