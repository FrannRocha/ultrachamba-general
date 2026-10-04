"""
Pruebas de regresión del clasificador.

Cada caso salió de un fallo real observado en una corrida del pipeline.
Si alguna vuelve a romperse, el dashboard estaría mintiendo.

Los casos son del área de tecnología en la zona de Monterrey, de donde
salieron; se fijan aquí para que no dependan de tu `.env`. Los de las demás
áreas y los de la zona `nacional` están en `test_areas.py`.
"""
import os

os.environ["ULTRACHAMBA_AREAS"] = "tecnologia"
os.environ["ULTRACHAMBA_ZONA"] = "monterrey"

import analisis  # noqa: E402
from analisis import analizar  # noqa: E402
from nucleo import vacante  # noqa: E402

# El caso de límites de palabra necesita dos habilidades declaradas, y
# perfil.py llega vacío en esta versión. Solo cambia la memoria de esta
# ejecución, nunca el archivo.
analisis.HABILIDADES.update({"bec": 7, "phishing": 7})

CASOS = [
    # (titulo, ubicacion, descripcion, nivel_esperado, elegible_esperado, nota)
    ("Internal Audit Senior Associate, Operations", "Remote - USA", "",
     "excluido", False, "'intern' NO debe casar dentro de 'internal'"),
    ("Lead, IT Audit and Technology Risk", "San Francisco, California", "",
     "excluido", False, "puesto de liderazgo"),
    ("International Security Analyst", "Remote - USA", "",
     "medio", False, "'intern' NO debe casar dentro de 'international'"),
    ("Governance, Risk, and Compliance Intern", "San Francisco, California", "",
     "practicas", False, "practicas real, pero presencial en el extranjero"),
    ("Security Engineering Intern", "Remote - United States", "",
     "practicas", False, "remoto cerrado a EEUU"),
    ("Insider Risk Analyst - SkillBridge Intern", "Remote - USA", "",
     "practicas", False, "programa militar de EEUU, remoto cerrado"),
    ("Penetration Tester", "Mexico, Remote", "",
     "medio", True, "remoto que nombra Mexico"),
    ("Backend Engineer, AI Security", "Anywhere in the World", "",
     "medio", True, "remoto genuinamente abierto"),
    ("Practicante de Ciberseguridad", "Apodaca, Nuevo Leon",
     "Buscamos practicante para apoyar en seguridad de la informacion",
     "practicas", True, "el objetivo ideal: practicas presenciales en el AMM"),
    ("Analista de Ciberseguridad Junior", "Monterrey, Nuevo Leon", "",
     "junior", True, "junior en Monterrey"),
    ("Cibersecurity Trainee 2026", "Benito Juarez, Ciudad de Mexico", "",
     "practicas", True, "practicas en CDMX: elegible pero exige mudarse"),
    ("Security Analyst", "Remote", "Must be authorized to work in the United States",
     "medio", False, "bloqueo declarado en la descripcion"),
    ("SOC Analyst Tier 1", "Remote - LATAM", "",
     "junior", True, "remoto abierto a LatAm"),
    ("Senior Security Engineer", "Remote - Global", "",
     "excluido", True, "elegible pero fuera de nivel"),

    # --- Fugas detectadas leyendo el TOP 20 de una corrida real -------------
    # SkillBridge es un programa de transicion militar de EEUU. Lo que importa
    # aqui es que la geografia lo bloquee; el nivel exacto da igual.
    ("Site Reliability Engineer Federal - SkillBridge", "Remote - Virginia, USA", "",
     "medio", False, "estado de EEUU dentro de un remoto cerrado"),
    ("Governance, Risk, and Compliance Intern (Fall)", "San Francisco, California",
     "We are a global company building the future of work worldwide",
     "practicas", False, "'global' en la descripcion no abre una vacante de San Francisco"),
    ("Working Student - Privacy Engineering", "Munich, Bayern, Germany",
     "We are a global team",
     "practicas", False, "presencial en Alemania pese al 'global' del texto"),
    ("Security Operations Analyst - Ireland", "Ireland", "",
     "medio", False, "presencial en Irlanda"),
    # "Graduate <puesto>" al estilo britanico es un rol de recien egresado,
    # no unas practicas: 'junior' es la clasificacion correcta.
    ("Graduate Data Scientist - Cyber Analytics", "Cheltenham", "",
     "junior", False, "ciudad del Reino Unido"),
    ("Becario de Auditoria Fiscal y Analisis de Balances", "Monterrey, Nuevo Leon",
     "Apoyo en revision de balances contables y declaraciones fiscales",
     "practicas", True, "es contabilidad, NO ciberseguridad: debe quedar fuera del area"),
    ("Becario de Actuaria y analisis de riesgos", "Monterrey, Nuevo Leon",
     "Calculo actuarial de siniestros y reservas tecnicas de seguros",
     "practicas", True, "riesgo actuarial, NO ciberseguridad"),
    ("Practicante Control Interno Tecnologia de la Informacion", "Monterrey, Nuevo Leon",
     "Apoyo en auditoria de controles ITGC sobre sistemas",
     "practicas", True, "auditoria SI de TI: debe contar como ciberseguridad"),
]

# Casos que ademas comprueban el AREA, no solo nivel y elegibilidad.
CASOS_AREA = [
    ("Becario de Auditoria Fiscal y Analisis de Balances", "Monterrey, Nuevo Leon",
     "Apoyo en revision de balances contables y declaraciones fiscales", "fuera"),
    ("Becario de Actuaria y analisis de riesgos", "Monterrey, Nuevo Leon",
     "Calculo actuarial de siniestros y reservas tecnicas de seguros", "fuera"),
    ("Practicante Control Interno Tecnologia de la Informacion", "Monterrey, Nuevo Leon",
     "Apoyo en auditoria de controles ITGC sobre sistemas", "ciberseguridad"),
    ("Becario Ciberseguridad", "Nuevo Leon, Mexico", "", "ciberseguridad"),
    ("AI Safety Red Team Intern", "Remote - Global",
     "Testing guardrails and prompt injection against our LLM", "ciber-ia"),
    ("Becario de Auditoria Fiscal y Analisis de Bases de Datos", "Monterrey, Nuevo Leon",
     "", "fuera"),
    ("Practicante de Seguridad Industrial", "Monterrey, Nuevo Leon", "", "fuera"),
    ("Becario de Seguridad Patrimonial", "Monterrey, Nuevo Leon", "", "fuera"),
]

# 'bec' es Business Email Compromise. Nunca debe casar dentro de 'becario':
# eso inflaba el score de toda vacante escrita en espanol.
CASOS_HABILIDADES = [
    ("Becario de Contabilidad", "becario para el area de becas y becarios", []),
    ("Analista BEC y phishing", "prevencion de BEC y phishing", ["bec", "phishing"]),
]


def main() -> int:
    fallos = 0
    print(f"{'RESULTADO':10} {'NIVEL':10} {'ELEG':6} {'MUD':4} {'SCORE':6}  CASO")
    print("-" * 100)
    for titulo, ubic, desc, nivel_esp, eleg_esp, nota in CASOS:
        v = analizar(
            vacante(titulo=titulo, empresa="Prueba", url="https://ejemplo.com",
                    fuente="test", ubicacion=ubic, descripcion=desc)
        )
        ok_nivel = v["nivel"] == nivel_esp
        ok_eleg = v["elegible_mx"] == eleg_esp
        ok = ok_nivel and ok_eleg
        if not ok:
            fallos += 1
        marca = "OK" if ok else "FALLO"
        print(
            f"{marca:10} {v['nivel']:10} {str(v['elegible_mx']):6} "
            f"{str(v.get('requiere_mudanza', False))[:4]:4} {v['score']:6.1f}  {titulo[:44]}"
        )
        if not ok_nivel:
            print(f"           -> nivel esperado '{nivel_esp}', obtenido '{v['nivel']}' | {nota}")
        if not ok_eleg:
            print(f"           -> elegible esperado {eleg_esp}, obtenido {v['elegible_mx']} | {nota}")
            print(f"           -> motivos: {v['motivos']}")

    print("\nAREA")
    print("-" * 100)
    for titulo, ubic, desc, area_esp in CASOS_AREA:
        v = analizar(
            vacante(titulo=titulo, empresa="Prueba", url="https://ejemplo.com",
                    fuente="test", ubicacion=ubic, descripcion=desc)
        )
        ok = v["area"] == area_esp
        if not ok:
            fallos += 1
        print(f"{'OK' if ok else 'FALLO':10} area={v['area']:16} esperado={area_esp:16} {titulo[:40]}")

    print("\nHABILIDADES (limites de palabra)")
    print("-" * 100)
    from analisis import medir_habilidades
    from nucleo import normalizar
    for titulo, desc, esperadas in CASOS_HABILIDADES:
        _, hallazgos = medir_habilidades(normalizar(f"{titulo} {desc}"))
        ok = set(hallazgos) == set(esperadas)
        if not ok:
            fallos += 1
        print(f"{'OK' if ok else 'FALLO':10} {str(hallazgos)[:44]:44} esperado={esperadas} | {titulo[:34]}")

    total = len(CASOS) + len(CASOS_AREA) + len(CASOS_HABILIDADES)
    print("-" * 100)
    print(f"{total - fallos}/{total} casos correctos")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
