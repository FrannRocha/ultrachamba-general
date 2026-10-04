"""
Detección de vacantes fantasma: anuncios publicados que no contratan a nadie.

Por qué importa. Entre el 18% y el 27% de los anuncios en línea son fantasma;
Greenhouse midió entre 18% y 22% en su propia plataforma. Postular a una es
tiempo perdido sin respuesta, y es lo que más desmoraliza en una búsqueda.

Por qué lo podemos hacer nosotros y casi nadie más. Las dos señales más
fuertes son la **antigüedad del anuncio** y su **historial de republicación**,
y los portales no las muestran: OCC no dice "esta lleva ocho meses aquí". Pero
esta base guarda cada avistamiento por corrida desde el primer día, así que la
antigüedad real y los ciclos de desaparición-reaparición se calculan solos.
Ese historial es el activo; esto solo lo lee.

Devuelve un riesgo de 0 a 100 con sus motivos, nunca un veredicto opaco: la
idea es que quien lo usa pueda discrepar mirando las razones.

Aviso honesto sobre la madurez de la señal: el historial de republicación
necesita semanas de corridas para valer. Hoy la señal fuerte es la antigüedad.
"""
from __future__ import annotations

import re
from collections import Counter

from almacen import conexion

# Nombres que ocultan al empleador. No prueban nada por sí solos, pero son un
# patrón conocido de anuncios de captación: recogen currículums sin que haya
# una vacante concreta detrás.
EMPRESAS_ANONIMAS = re.compile(
    r"^(confidencial|empresa confidencial|importante empresa|"
    r"recomendada|empresa del sector|reclutadora|consultora|"
    r"empresa l[ií]der|importante grupo|nuestro cliente|cliente confidencial)",
    re.I,
)

# Bolsas de trabajo y agencias: publican por volumen para varios clientes.
# No es fraude, pero baja la probabilidad de que ESA vacante concreta exista
# tal como se describe.
AGENCIAS = re.compile(
    r"(manpower|adecco|randstad|kelly services|olx|computrabajo|"
    r"staffing|headhunt|reclutamiento|bolsa de trabajo|outsourcing|"
    r"human capital|talent solutions|allied universal)",
    re.I,
)

# Calibrado con datos reales de esta base. Se encontraron practicas publicadas
# hace 229, 436 y hasta 997 dias, y un "Auditor TI Jr" con 3.672 dias — diez
# años. Un anuncio de practicas que lleva mas de un año abierto no esta
# contratando a nadie, asi que la antiguedad extrema basta por si sola para
# marcarlo como riesgo alto; no hace falta que se acumule con otras señales.
UMBRALES = [
    (365, 55, "lleva mas de un año publicada"),
    (180, 40, "muy antigua"),
    (90, 25, "antigua"),
    (45, 12, "algo antigua"),
]

# Medido en la base: 1.023 de 2.228 vacantes (46%) no traen fecha de publicacion,
# porque muchas fuentes simplemente no la dan. Sin fecha, la señal mas fuerte no
# aplica y la vacante sale con riesgo bajo aunque lleve años abierta: eso es una
# falsa tranquilidad, no una ausencia de riesgo.
#
# El respaldo sale del propio historial: si esta base la ve desde hace N dias,
# lleva **al menos** N dias publicada. Es una cota inferior, asi que nunca
# exagera. Hoy el historial es de dos dias y esto no suma un solo punto; en unas
# semanas de corridas se vuelve la señal principal para esas 1.023. Se deja
# escrito ahora para que empiece a acumular desde ya.


def _dias(publicado: str | None) -> int | None:
    if not publicado:
        return None
    from datetime import date, datetime
    try:
        d = datetime.strptime(str(publicado)[:10], "%Y-%m-%d").date()
        return (date.today() - d).days
    except Exception:
        return None


def senales(v: dict, contexto: dict | None = None) -> dict:
    """Calcula el riesgo de que la vacante sea fantasma.

    `contexto` trae datos agregados de toda la base para no recalcularlos por
    vacante: cuántas publica cada empresa y cuántas veces se repite un título.
    """
    ctx = contexto or {}
    riesgo = 0
    motivos: list[str] = []

    # 1. Antiguedad. La senal mas fuerte y la que los portales no muestran.
    dias = _dias(v.get("publicado"))
    # Sin fecha de la fuente se usa desde cuando la ve esta base, que es una cota
    # inferior: si la vemos desde hace N dias, lleva al menos N dias abierta.
    observados = _dias(v.get("visto_desde"))
    cota = dias if dias is not None else observados
    antiguedad_desconocida = dias is None

    puntuo = False
    if cota is not None:
        for limite, puntos, etiqueta in UMBRALES:
            if cota >= limite:
                riesgo += puntos
                puntuo = True
                motivos.append(
                    f"{etiqueta}: lleva {cota} dias publicada" if not antiguedad_desconocida
                    else f"{etiqueta}: lleva al menos {cota} dias abierta (la vemos desde entonces)")
                break

    # Si la fuente no dio fecha y lo que llevamos observado aun no alcanza para
    # decir nada, hay que decirlo: "sin señales" no es lo mismo que "recien
    # publicada", y callarlo seria una falsa tranquilidad. No suma riesgo porque
    # no es evidencia de nada; es la ausencia de evidencia.
    if antiguedad_desconocida and not puntuo:
        motivos.append(
            "la fuente no dice cuando se publico" + (
                f"; solo consta que sigue abierta desde hace {observados} dias"
                if observados is not None else ""))

    # 2. Ciclos de reaparicion: desaparecio de las fuentes y volvio. Un anuncio
    #    que se republica sin cambios es el patron clasico del anuncio fantasma.
    ciclos = v.get("ciclos_reaparicion", 0)
    if ciclos >= 2:
        riesgo += 26
        motivos.append(f"republicada {ciclos} veces tras desaparecer")
    elif ciclos == 1:
        riesgo += 13
        motivos.append("desaparecio y volvio a aparecer una vez")

    # 3. Empleador oculto.
    empresa = (v.get("empresa") or "").strip()
    if EMPRESAS_ANONIMAS.match(empresa):
        riesgo += 20
        motivos.append(f"no dice que empresa es ('{empresa[:34]}')")
    elif AGENCIAS.search(empresa):
        riesgo += 9
        motivos.append("publicada por una agencia o bolsa, no por el empleador")

    # 4. El mismo puesto repetido por la misma empresa. Distinto de que una
    #    empresa grande publique mucho: eso es normal. Repetir el MISMO titulo
    #    es sintoma de anuncio permanente.
    clave = _clave_titulo(v)
    repes = ctx.get("titulos_repetidos", {}).get(clave, 0)
    if repes >= 3:
        riesgo += 17
        motivos.append(f"la misma empresa publica este puesto {repes} veces")

    # 5. Volumen desproporcionado de una misma empresa.
    n_emp = ctx.get("por_empresa", {}).get(empresa, 0)
    if n_emp >= 25 and not EMPRESAS_ANONIMAS.match(empresa):
        riesgo += 6
        motivos.append(f"{empresa[:26]} tiene {n_emp} anuncios abiertos a la vez")

    # 6. Descripcion ausente: sin texto no hay puesto definido.
    if len((v.get("descripcion") or "").strip()) < 120:
        riesgo += 8
        motivos.append("descripcion casi vacia")

    riesgo = max(0, min(100, riesgo))
    if riesgo >= 55:
        nivel = "alto"
    elif riesgo >= 30:
        nivel = "medio"
    else:
        nivel = "bajo"
    return {"riesgo_fantasma": riesgo, "nivel_fantasma": nivel,
            "motivos_fantasma": motivos, "dias_publicada": dias}


def _clave_titulo(v: dict) -> str:
    from nucleo import normalizar
    return re.sub(r"[^a-z0-9]", "", normalizar(f"{v.get('empresa','')}|{v.get('titulo','')}"))


def construir_contexto() -> dict:
    """Agregados de toda la base, calculados una sola vez por corrida."""
    with conexion() as con:
        filas = con.execute("SELECT id, empresa, titulo FROM vacantes").fetchall()
    por_empresa = Counter((f["empresa"] or "").strip() for f in filas)
    titulos = Counter(
        _clave_titulo({"empresa": f["empresa"], "titulo": f["titulo"]}) for f in filas
    )
    return {"por_empresa": dict(por_empresa),
            "titulos_repetidos": {k: n for k, n in titulos.items() if n > 1}}


def ciclos_por_vacante() -> dict[str, int]:
    """Cuenta cuantas veces cada vacante desaparecio y volvio.

    Se mira la secuencia de corridas en las que se vio: cada hueco intermedio
    es un ciclo. Una vacante vista en las corridas 1, 2 y 4 tiene un hueco.
    """
    with conexion() as con:
        corridas = [r["id"] for r in con.execute(
            "SELECT id FROM corridas WHERE guardadas > 0 ORDER BY id")]
        vistas = con.execute(
            "SELECT vacante_id, corrida_id FROM avistamientos ORDER BY vacante_id, corrida_id"
        ).fetchall()
    if len(corridas) < 3:
        return {}   # con menos de tres corridas no hay huecos que medir
    orden = {c: i for i, c in enumerate(corridas)}
    por_vacante: dict[str, list[int]] = {}
    for r in vistas:
        if r["corrida_id"] in orden:
            por_vacante.setdefault(r["vacante_id"], []).append(orden[r["corrida_id"]])
    salida = {}
    for vid, indices in por_vacante.items():
        indices.sort()
        huecos = sum(1 for a, b in zip(indices, indices[1:]) if b - a > 1)
        if huecos:
            salida[vid] = huecos
    return salida


def primer_avistamiento() -> dict[str, str]:
    """Desde cuando ve esta base cada vacante, en fecha ISO.

    Es el respaldo para las 1.023 vacantes cuya fuente no dice cuando se
    publicaron: si la vemos desde hace N dias, lleva al menos N dias abierta.
    """
    with conexion() as con:
        filas = con.execute("""
            SELECT a.vacante_id AS id, MIN(c.inicio) AS desde
            FROM avistamientos a JOIN corridas c ON c.id = a.corrida_id
            GROUP BY a.vacante_id""").fetchall()
    return {f["id"]: f["desde"] for f in filas if f["desde"]}


def analizar_base() -> dict:
    """Calcula el riesgo para toda la base y lo guarda."""
    from nucleo import log
    ctx = construir_contexto()
    ciclos = ciclos_por_vacante()
    desde = primer_avistamiento()
    with conexion() as con:
        con.execute("ALTER TABLE vacantes ADD COLUMN riesgo_fantasma INTEGER"
                    ) if not _tiene_columna(con, "riesgo_fantasma") else None
        con.execute("ALTER TABLE vacantes ADD COLUMN motivos_fantasma TEXT"
                    ) if not _tiene_columna(con, "motivos_fantasma") else None
        filas = con.execute(
            "SELECT id, titulo, empresa, publicado, descripcion FROM vacantes").fetchall()

    import json
    resultados = []
    for f in filas:
        v = dict(f)
        v["ciclos_reaparicion"] = ciclos.get(v["id"], 0)
        v["visto_desde"] = desde.get(v["id"])
        s = senales(v, ctx)
        resultados.append((s["riesgo_fantasma"],
                           json.dumps(s["motivos_fantasma"], ensure_ascii=False), v["id"]))

    with conexion() as con:
        con.executemany(
            "UPDATE vacantes SET riesgo_fantasma=?, motivos_fantasma=? WHERE id=?",
            resultados)

    conteo = Counter("alto" if r[0] >= 55 else "medio" if r[0] >= 30 else "bajo"
                     for r in resultados)
    log(f"riesgo fantasma: {dict(conteo)}")
    return dict(conteo)


def _tiene_columna(con, nombre: str) -> bool:
    return any(r[1] == nombre for r in con.execute("PRAGMA table_info(vacantes)"))


if __name__ == "__main__":
    import json
    print(json.dumps(analizar_base(), ensure_ascii=False))
    with conexion() as con:
        print("\nMAS SOSPECHOSAS (riesgo alto, y que estarian en el panel):")
        for r in con.execute("""
            SELECT titulo, empresa, score, riesgo_fantasma, motivos_fantasma, publicado
            FROM vacantes
            WHERE riesgo_fantasma >= 55 AND score >= 40
              AND (nivel IS NULL OR nivel != 'excluido')
            ORDER BY score DESC LIMIT 12"""):
            print(f"  fit {r['score']:5} · riesgo {r['riesgo_fantasma']:3} | "
                  f"{r['titulo'][:44]:44} | {(r['empresa'] or '')[:24]}")
            for m in json.loads(r["motivos_fantasma"] or "[]")[:2]:
                print(f"        - {m}")
