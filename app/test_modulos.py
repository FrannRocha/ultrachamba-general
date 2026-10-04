"""
Prueba consolidada de los tres modulos de correccion.

Cada caso salio de un fallo real observado en el panel:
  - vacantes presenciales en otros estados sin marcar que exigen mudanza
  - vacantes que piden anos de experiencia que el perfil no tiene
  - vacantes de otros rubros coladas como si fueran de seguridad

Los casos son del area de tecnologia en la zona de Monterrey, que es de donde
salieron. Se fijan aqui para que no dependan de tu `.env`; los de las demas
areas y los de la zona `nacional` estan en `test_areas.py`.
"""
import os

os.environ["ULTRACHAMBA_AREAS"] = "tecnologia"
os.environ["ULTRACHAMBA_ZONA"] = "monterrey"

from dominio import clasificar_dominio  # noqa: E402
from experiencia import anos_exigidos
from geo import clasificar_geo

# (ubicacion, descripcion, elegible, mudanza)
CASOS_GEO = [
    ("Apodaca, Nuevo Leon", "", True, False),
    ("Monterrey, Nuevo Leon", "", True, False),
    ("San Pedro Garza Garcia, Nuevo Leon", "", True, False),
    ("Alvaro Obregon, Ciudad de Mexico", "", True, True),
    ("Benito Juarez, Ciudad de Mexico", "", True, True),
    ("Mexico CIty", "", True, True),
    ("Naucalpan de Juarez, Estado de Mexico", "", True, True),
    ("Toluca, Estado de Mexico", "", True, True),
    ("Tlalpan, Ciudad de Mexico", "", True, True),
    ("Guadalajara, Jalisco", "", True, True),
    ("Remote - USA", "", False, False),
    ("Remote - Virginia, USA", "", False, False),
    ("U.S. or Mexico Remote", "", True, False),
    ("Anywhere in the World", "", True, False),
    ("Remote - LATAM", "", True, False),
    ("San Francisco, California", "", False, False),
    ("Munich, Bayern, Germany", "", False, False),
    ("Ireland", "", False, False),
    ("Remote", "must be authorized to work in the United States", False, False),
]

# (texto, minimo_esperado, alcanzable_esperado)
CASOS_EXP = [
    ("5+ years of experience in security engineering", 5, False),
    ("Minimum of 3 years of relevant experience", 3, False),
    ("We require at least 4 years' experience", 4, False),
    ("3-5 years of experience", 3, False),
    ("0-2 years of experience", None, True),
    ("Experiencia minima de 3 anos", 3, False),
    ("Al menos 2 anos de experiencia", None, True),
    ("De 3 a 5 anos de experiencia comprobable", 3, False),
    ("No prior experience required", None, True),
    ("Buscamos practicante, sin experiencia previa", None, True),
    ("0-2 years of customer service and 5+ years of security engineering", 5, False),
    ("Our product roadmap covers the next 3 years", None, True),
    ("In the last 2 years we grew 300%", None, True),
    ("nearly 20 years of industry contributions", None, True),
    ("Estudiante de ultimos semestres", None, True),
    ("", None, True),
]

# (titulo, area_esperada)
CASOS_DOM = [
    ("Influencer Strategist (Contract)", "fuera"),
    ("Mortgage Processor/Underwriter - Remote", "fuera"),
    ("Mac MSP Help Desk Guru (work from home)", "ti-general"),
    ("Becario de Auditoria Fiscal y Analisis de Bases de Datos", "fuera"),
    ("Becario de Actuaria y analisis de riesgos", "fuera"),
    ("Lider de capacitacion", "fuera"),
    ("Practicante de Seguridad Industrial", "fuera"),
    ("Becario de Seguridad Patrimonial", "fuera"),
    ("Practicante de Ciberseguridad", "ciberseguridad"),
    ("Becario Ciberseguridad", "ciberseguridad"),
    ("PRACTICANTE CONTROL INTERNO TECNOLOGIA DE LA INFORMACION", "ciberseguridad"),
    ("Operador SOC Jr. / Analista SOC Jr.", "ciberseguridad"),
    ("Practicante de Inteligencia Artificial", "ia"),
    ("Practicante de Ciencia de Datos", "ia"),
    ("AI Safety Red Team Intern", "ciber-ia"),
    ("Practicante Sistemas", "ti-general"),
    ("Analista de Ciberseguridad Junior", "ciberseguridad"),
]


def main() -> int:
    fallos = 0

    print("GEOGRAFIA")
    print("-" * 92)
    for ubic, desc, eleg_esp, mud_esp in CASOS_GEO:
        r = clasificar_geo(ubic, "Analista", desc)
        ok = r["elegible_mx"] == eleg_esp and r["requiere_mudanza"] == mud_esp
        fallos += not ok
        print(f"  {'OK ' if ok else 'FALLO':6} eleg={str(r['elegible_mx']):5} mud={str(r['requiere_mudanza']):5} "
              f"mod={r['modalidad'][:10]:10} | {ubic[:40]}")
        if not ok:
            print(f"         esperado eleg={eleg_esp} mud={mud_esp} | motivos={r['motivos'][:2]}")

    print("\nEXPERIENCIA")
    print("-" * 92)
    for texto, min_esp, alc_esp in CASOS_EXP:
        r = anos_exigidos("Analista de Seguridad", texto)
        ok = r["alcanzable"] == alc_esp and (min_esp is None or r["minimo"] == min_esp)
        fallos += not ok
        print(f"  {'OK ' if ok else 'FALLO':6} min={str(r['minimo']):5} alcanzable={str(r['alcanzable']):5} | {texto[:56]}")
        if not ok:
            print(f"         esperado min={min_esp} alcanzable={alc_esp} | evidencia='{r.get('evidencia','')[:60]}'")

    print("\nDOMINIO")
    print("-" * 92)
    for titulo, area_esp in CASOS_DOM:
        r = clasificar_dominio(titulo, "")
        ok = r["area"] == area_esp
        fallos += not ok
        print(f"  {'OK ' if ok else 'FALLO':6} {r['area']:15} esperado={area_esp:15} | {titulo[:46]}")

    total = len(CASOS_GEO) + len(CASOS_EXP) + len(CASOS_DOM)
    print("-" * 92)
    print(f"{total - fallos}/{total} casos correctos")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
