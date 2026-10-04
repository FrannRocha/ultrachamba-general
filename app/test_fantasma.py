"""
Pruebas del detector de vacantes fantasma.

Cada caso viene de un fallo real encontrado con datos de esta base, no de
casos inventados. Correr con:

    python test_fantasma.py
"""
from __future__ import annotations

import sys
from datetime import date, timedelta

import fantasma


def hace(dias: int) -> str:
    return (date.today() - timedelta(days=dias)).isoformat()


FALLOS: list[str] = []


def revisar(nombre: str, condicion: bool, detalle: str = "") -> None:
    if condicion:
        print(f"  ok   {nombre}")
    else:
        print(f"  FALLA {nombre}" + (f" — {detalle}" if detalle else ""))
        FALLOS.append(nombre)


def base(**extra) -> dict:
    v = {"id": "x", "titulo": "Security Intern", "empresa": "Acme",
         "descripcion": "d" * 400, "publicado": hace(3), "ciclos_reaparicion": 0}
    v.update(extra)
    return v


def prueba_umbrales() -> None:
    """El fallo original: la primera calibracion daba 34 puntos a "muy antigua"
    y NINGUNA vacante llegaba a riesgo alto, ni siquiera una de 1.437 dias."""
    print("\numbrales de antiguedad")
    revisar("una practica de mas de un año es riesgo alto por si sola",
            fantasma.senales(base(publicado=hace(400)))["nivel_fantasma"] == "alto",
            f"dio {fantasma.senales(base(publicado=hace(400)))}")
    revisar("caso real de 1437 dias (Binance) es alto",
            fantasma.senales(base(publicado=hace(1437)))["riesgo_fantasma"] >= 55)
    revisar("recien publicada no acumula riesgo",
            fantasma.senales(base(publicado=hace(2)))["riesgo_fantasma"] == 0)
    revisar("el riesgo crece con la antiguedad, nunca al reves",
            all(fantasma.senales(base(publicado=hace(a)))["riesgo_fantasma"]
                <= fantasma.senales(base(publicado=hace(b)))["riesgo_fantasma"]
                for a, b in [(10, 60), (60, 100), (100, 200), (200, 400)]))


def prueba_antiguedad_desconocida() -> None:
    """1.023 de 2.228 vacantes no traen fecha. Salian con riesgo 0 y sin decir
    nada, lo que se lee como "recien publicada" cuando en realidad es "no se
    sabe". Ausencia de evidencia no es evidencia de ausencia."""
    print("\nantiguedad desconocida")
    s = fantasma.senales(base(publicado=None, visto_desde=hace(1)))
    revisar("sin fecha de la fuente, se avisa explicitamente",
            any("no dice cuando se publico" in m for m in s["motivos_fantasma"]),
            str(s["motivos_fantasma"]))
    revisar("no se sube el riesgo por no saber la fecha",
            s["riesgo_fantasma"] == 0, f"dio {s['riesgo_fantasma']}")

    # Cuando el historial ya es largo, la cota observada sustituye a la fecha.
    s2 = fantasma.senales(base(publicado=None, visto_desde=hace(200)))
    revisar("con historial largo, lo observado puntua como antiguedad",
            s2["riesgo_fantasma"] >= 40, f"dio {s2['riesgo_fantasma']}")
    revisar("y se dice que es una cota, no una fecha de publicacion",
            any("al menos" in m for m in s2["motivos_fantasma"]),
            str(s2["motivos_fantasma"]))

    # La fecha de la fuente manda sobre lo observado.
    s3 = fantasma.senales(base(publicado=hace(5), visto_desde=hace(900)))
    revisar("si la fuente da fecha, esa manda sobre lo observado",
            s3["riesgo_fantasma"] == 0, f"dio {s3['riesgo_fantasma']}")


def prueba_republicacion() -> None:
    print("\nrepublicacion")
    revisar("republicarse varias veces suma riesgo",
            fantasma.senales(base(ciclos_reaparicion=3))["riesgo_fantasma"] > 0)
    revisar("mas ciclos, mas riesgo",
            fantasma.senales(base(ciclos_reaparicion=3))["riesgo_fantasma"]
            > fantasma.senales(base(ciclos_reaparicion=1))["riesgo_fantasma"])


def prueba_empleador_oculto() -> None:
    print("\nempleador oculto")
    revisar("'Empresa Confidencial' suma riesgo",
            fantasma.senales(base(empresa="Empresa Confidencial"))["riesgo_fantasma"] > 0)
    revisar("una agencia suma menos que un anonimo",
            fantasma.senales(base(empresa="Manpower"))["riesgo_fantasma"]
            < fantasma.senales(base(empresa="Confidencial"))["riesgo_fantasma"])
    revisar("una empresa normal no suma nada por su nombre",
            fantasma.senales(base(empresa="Banorte"))["riesgo_fantasma"] == 0)


def prueba_no_inventa() -> None:
    """Un detector que siempre encuentra algo no sirve de nada."""
    print("\ncontrol negativo")
    limpia = base(publicado=hace(1), empresa="Kavak", descripcion="d" * 900)
    s = fantasma.senales(limpia, {})
    revisar("una vacante sana da riesgo 0 y cero motivos",
            s["riesgo_fantasma"] == 0 and not s["motivos_fantasma"],
            f"dio {s}")
    revisar("el riesgo nunca se sale de 0..100",
            all(0 <= fantasma.senales(base(publicado=hace(4000),
                                           empresa="Confidencial", descripcion="",
                                           ciclos_reaparicion=9))["riesgo_fantasma"] <= 100
                for _ in [0]))


def prueba_motivos_auditables() -> None:
    """Quien usa el sistema tiene que poder discrepar: todo riesgo lleva motivo."""
    print("\nmotivos auditables")
    casos = [base(publicado=hace(500)), base(empresa="Confidencial"),
             base(ciclos_reaparicion=2), base(descripcion="")]
    revisar("nunca hay riesgo sin motivo que lo explique",
            all(not (fantasma.senales(c)["riesgo_fantasma"] > 0
                     and not fantasma.senales(c)["motivos_fantasma"]) for c in casos))


def prueba_contra_la_base_real() -> None:
    """Comprueba que lo guardado en la base coincide con lo que calcula el
    modulo hoy. Si alguien cambia los umbrales y no recalcula, esto lo detecta."""
    print("\ncoherencia con la base guardada")
    try:
        from almacen import conexion
        import json
        with conexion() as con:
            filas = con.execute("""
                SELECT id, titulo, empresa, publicado, descripcion,
                       riesgo_fantasma, motivos_fantasma
                FROM vacantes WHERE riesgo_fantasma IS NOT NULL LIMIT 300""").fetchall()
    except Exception as e:                       # sin base, el resto igual vale
        print(f"  (se omite: no se pudo abrir la base — {e})")
        return
    if not filas:
        print("  (se omite: la base no tiene riesgo calculado todavia)")
        return
    ctx = fantasma.construir_contexto()
    ciclos = fantasma.ciclos_por_vacante()
    desde = fantasma.primer_avistamiento()
    descuadres = 0
    for f in filas:
        v = dict(f)
        v["ciclos_reaparicion"] = ciclos.get(v["id"], 0)
        v["visto_desde"] = desde.get(v["id"])
        if fantasma.senales(v, ctx)["riesgo_fantasma"] != v["riesgo_fantasma"]:
            descuadres += 1
    revisar(f"lo guardado coincide con lo calculado ({len(filas)} revisadas)",
            descuadres == 0,
            f"{descuadres} descuadran — hay que correr 'python fantasma.py'")


if __name__ == "__main__":
    print("PRUEBAS DEL DETECTOR DE VACANTES FANTASMA")
    for p in (prueba_umbrales, prueba_antiguedad_desconocida, prueba_republicacion,
              prueba_empleador_oculto, prueba_no_inventa, prueba_motivos_auditables,
              prueba_contra_la_base_real):
        p()
    print()
    if FALLOS:
        print(f"FALLARON {len(FALLOS)}: " + ", ".join(FALLOS))
        sys.exit(1)
    print("todo en orden")
