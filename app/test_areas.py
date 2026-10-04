"""
Casos de la adaptacion por area y por zona. Se ejecutan; no son documentacion.

    python test_areas.py

POR QUE EXISTE. Cambiar de area no puede ser solo cambiar las busquedas: si el
clasificador siguiera siendo el de tecnologia, una persona de contabilidad
veria sus vacantes marcadas "fuera" y el panel pareceria funcionar sin
funcionar. Estos casos comprueban las dos mitades a la vez --lo que se busca y
como se clasifica-- con varias areas no informaticas, ademas de la zona
`nacional` y de los errores de configuracion. No hacen peticiones de red.
"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

import areas                              # noqa: E402
from analisis import analizar             # noqa: E402
from nucleo import normalizar, vacante    # noqa: E402

fallos: list[str] = []
hechos = 0


def caso(descripcion: str, obtenido, esperado) -> None:
    global hechos
    hechos += 1
    if obtenido != esperado:
        fallos.append(f"{descripcion}\n      esperado: {esperado!r}\n      obtenido: {obtenido!r}")


@contextmanager
def entorno(areas_activas: str, zona: str = "monterrey"):
    """Fija areas y zona solo dentro del bloque, y restaura lo que hubiera."""
    previo = {k: os.environ.get(k) for k in ("ULTRACHAMBA_AREAS", "ULTRACHAMBA_ZONA")}
    os.environ["ULTRACHAMBA_AREAS"] = areas_activas
    os.environ["ULTRACHAMBA_ZONA"] = zona
    try:
        yield
    finally:
        for clave, valor in previo.items():
            if valor is None:
                os.environ.pop(clave, None)
            else:
                os.environ[clave] = valor


def analizada(titulo: str, descripcion: str = "",
              ubicacion: str = "Monterrey, Nuevo Leon") -> dict:
    return analizar(vacante(titulo=titulo, empresa="Prueba", url="https://example.com",
                            fuente="test", ubicacion=ubicacion, descripcion=descripcion))


def lanza_error(funcion) -> bool:
    try:
        funcion()
    except ValueError:
        return True
    return False


# ---------------------------------------------------------------------------
# 1. EL CLASIFICADOR SIGUE AL AREA
#
# El mismo anuncio cambia de area segun la configuracion. El caso de auditoria
# fiscal es el de `test_analisis.py`: con tecnologia debe quedar fuera, y con
# contabilidad tiene que ser suyo.
# ---------------------------------------------------------------------------
AUDITORIA = ("Becario de Auditoria Fiscal y Analisis de Balances",
             "Apoyo en revision de balances contables y declaraciones fiscales")
CIBER = ("Practicante de Ciberseguridad",
         "Buscamos practicante para apoyar en seguridad de la informacion")

with entorno("tecnologia"):
    caso("tecnologia: el becario de auditoria fiscal queda fuera",
         analizada(*AUDITORIA)["area"], "fuera")
    caso("tecnologia: el practicante de ciberseguridad es suyo",
         analizada(*CIBER)["area"], "ciberseguridad")

with entorno("contabilidad-finanzas"):
    caso("contabilidad: el mismo becario de auditoria fiscal es de su area",
         analizada(*AUDITORIA)["area"], "contabilidad-finanzas")
    caso("contabilidad: un auxiliar contable es de su area",
         analizada("Auxiliar contable")["area"], "contabilidad-finanzas")
    caso("contabilidad: el practicante de ciberseguridad queda fuera",
         analizada(*CIBER)["area"], "fuera")

with entorno("recursos-humanos"):
    caso("recursos humanos: un practicante de reclutamiento es de su area",
         analizada("Practicante de Reclutamiento y Seleccion")["area"], "recursos-humanos")
    caso("recursos humanos: un auxiliar contable queda fuera",
         analizada("Auxiliar contable")["area"], "fuera")

with entorno("salud"):
    caso("salud: un auxiliar de enfermeria es de su area",
         analizada("Auxiliar de enfermeria")["area"], "salud")

with entorno("todas"):
    caso("todas: el becario de auditoria fiscal es de contabilidad",
         analizada(*AUDITORIA)["area"], "contabilidad-finanzas")
    caso("todas: un guardia de seguridad sigue fuera (oficio sin area)",
         analizada("Guardia de seguridad")["area"], "fuera")

# Titulos reales que la corrida de validacion del 13-sep-2026 dejaba fuera de
# su propia area. Si alguien quita esos terminos, fallan aqui.
with entorno("recursos-humanos"):
    caso("recursos humanos: 'HR Intern' en ingles es de su area",
         analizada("HR Intern")["area"], "recursos-humanos")
    caso("recursos humanos: 'Intern, General HR' tambien",
         analizada("Intern, General HR")["area"], "recursos-humanos")
    caso("recursos humanos: 'Talent Intern' tambien",
         analizada("Talent Intern")["area"], "recursos-humanos")
with entorno("contabilidad-finanzas"):
    caso("contabilidad: 'Practicante de nóminas' (plural y con tilde) es de su area",
         analizada("Practicante de nóminas")["area"], "contabilidad-finanzas")
    caso("contabilidad: 'Controlling Intern' es de su area",
         analizada("Controlling Intern")["area"], "contabilidad-finanzas")

# ---------------------------------------------------------------------------
# 2. LO QUE SE BUSCA SIGUE AL AREA
# ---------------------------------------------------------------------------
with entorno("tecnologia"):
    li_tec = areas.busquedas_linkedin()
    rx_tec = areas.regex_prefiltro_titulo()
with entorno("contabilidad-finanzas"):
    li_con = areas.busquedas_linkedin()
    occ_con = areas.consultas_occ()
    rx_con = areas.regex_prefiltro_titulo()
    remotive_con = areas.categorias_remotive()
    indeed_con = areas.consultas_indeed()
with entorno("salud"):
    occ_sal = areas.consultas_occ()
    rx_sal = areas.regex_prefiltro_titulo()


def palabras(busquedas) -> set[str]:
    return {normalizar(p) for p, *_ in busquedas}


caso("LinkedIn: contabilidad busca contabilidad",
     any("contab" in p for p in palabras(li_con)), True)
caso("LinkedIn: contabilidad no busca ciberseguridad",
     any("ciberseg" in p for p in palabras(li_con)), False)
caso("LinkedIn: tecnologia no busca contabilidad",
     any("contab" in p for p in palabras(li_tec)), False)
caso("OCC: contabilidad y salud no comparten ninguna consulta",
     set(occ_con) & set(occ_sal), set())
caso("OCC: contabilidad no pide consultas de ciberseguridad",
     any("ciberseg" in q for q in occ_con), False)
caso("prefiltro: contabilidad deja pasar 'auxiliar contable'",
     bool(rx_con.search("auxiliar contable")), True)
caso("prefiltro: salud deja pasar 'enfermera de piso'",
     bool(rx_sal.search("enfermera de piso")), True)
caso("prefiltro: tecnologia no deja pasar 'enfermera de piso'",
     bool(rx_tec.search("enfermera de piso")), False)
caso("Remotive: contabilidad no pide la categoria de software",
     "software-dev" in remotive_con, False)
caso("Indeed: las consultas de contabilidad hablan de contabilidad",
     any("contab" in normalizar(q) for q in indeed_con), True)

# ---------------------------------------------------------------------------
# 3. LA ZONA
# ---------------------------------------------------------------------------
GUADALAJARA = ("Analista contable junior", "", "Guadalajara, Jalisco")

with entorno("contabilidad-finanzas", "monterrey"):
    v = analizada(*GUADALAJARA)
    caso("monterrey: una vacante presencial en Guadalajara exige mudarse",
         bool(v.get("requiere_mudanza")), True)
    caso("monterrey: Apodaca esta en la zona", areas.en_zona("Apodaca, Nuevo Leon"), True)
    caso("monterrey: LinkedIn busca en Monterrey",
         any("Monterrey" in u for _, u, _, _ in areas.busquedas_linkedin()), True)

with entorno("contabilidad-finanzas", "nacional"):
    v = analizada(*GUADALAJARA)
    caso("nacional: la misma vacante no exige mudarse",
         bool(v.get("requiere_mudanza")), False)
    caso("nacional: y sigue siendo elegible desde Mexico", v["elegible_mx"], True)
    caso("nacional: Monterrey ya no cuenta como 'en tu zona'",
         areas.en_zona("Monterrey, Nuevo Leon"), False)
    caso("nacional: LinkedIn ya no busca en Monterrey",
         any("Monterrey" in u for _, u, _, _ in areas.busquedas_linkedin()), False)

with entorno("derecho,salud", "nacional"):
    ctx = areas.contexto_panel()
    caso("panel: con la zona nacional no hay regex de zona", ctx["zona"]["regex"], "")
    caso("panel: el contexto trae las areas pedidas",
         {a["clave"] for a in ctx["areas"]}, {"derecho", "salud"})
    caso("panel: dos areas no son 'todas'", ctx["todas"], False)

# ---------------------------------------------------------------------------
# 4. UNA CONFIGURACION MAL ESCRITA PARA EL PROGRAMA, NO SE IGNORA
# ---------------------------------------------------------------------------
with entorno("contabilidad"):          # la clave es contabilidad-finanzas
    caso("un area mal escrita lanza un error claro", lanza_error(areas.claves_activas), True)
with entorno("todas", "guadalajara"):
    caso("una zona desconocida tambien", lanza_error(areas.zona), True)

# ---------------------------------------------------------------------------
# 5. CURSOS
# ---------------------------------------------------------------------------
with entorno("contabilidad-finanzas"):
    caso("cursos: contabilidad pesa lo general, no la nube",
         areas.pesos_cursos(), {"general": 20})
with entorno("tecnologia"):
    caso("cursos: tecnologia conserva el peso de la nube", areas.pesos_cursos().get("nube"), 30)


if __name__ == "__main__":
    print(f"\n{hechos} casos de areas y zonas")
    if fallos:
        print(f"\nFALLARON {len(fallos)}:\n")
        for f in fallos:
            print("  -", f)
        sys.exit(1)
    print("todos pasan\n")
