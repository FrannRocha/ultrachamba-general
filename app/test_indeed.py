"""
Prueba real de la fuente Indeed. `python test_indeed.py`

No hay simulacros: hace peticiones de verdad a la API y falla si Indeed está
caído o bloqueando. Esa es la idea. Un colector de vacantes solo se puede
validar contra el sitio real, y el modo en que estas fuentes se rompen no es
lanzando excepciones — es respondiendo 200 con cero resultados, o poblando la
mitad de los campos. Por eso el test mide CONTENIDO y no solo que no reviente.

SIN `INDEED_API_KEY` NO SE EJECUTA: imprime "NO EJECUTADO" y sale con código 0.
Una fuente sin configurar no es un fallo del código, y mandar peticiones que
responderían 401 no prueba nada (ver `.env.example`).

Comprueba cinco cosas, en este orden:

  1. Que la API responde y con qué códigos HTTP.
  2. Que el parser saca vacantes y con los campos poblados.
  3. Que esas vacantes son de México y, si hay zona base, de esa zona.
  4. Que el diccionario que produce encaja con `nucleo.vacante()` sin
     adaptadores, y que los nombres de `extra` son los que lee `analisis.py`.
  5. Que `peticiones()` no miente: o sirve para la excavadora, o devuelve cero
     y lo dice.

La corrida es pequeña a propósito (4 consultas, 2 páginas): basta para separar
"funciona" de "no funciona" y no castiga la clave de API. Las consultas y la
zona salen de la configuración activa (`ULTRACHAMBA_AREAS`, `ULTRACHAMBA_ZONA`).

Uso:
    python test_indeed.py            # corrida normal
    python test_indeed.py --amplio   # 10 consultas, para mirar cobertura
"""
from __future__ import annotations

import re
import sys
import time

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

import areas  # noqa: E402
import fuentes_indeed as indeed  # noqa: E402
from nucleo import normalizar, vacante  # noqa: E402

# Consultas de la prueba: las primeras de las áreas activas, sin barrerlas todas.
CONSULTAS = indeed.consultas_por_defecto()[:4]
CONSULTAS_AMPLIO = indeed.consultas_por_defecto()[:10]

# Zonas: la primera ubicación de la zona base, si la hay, y la búsqueda
# nacional (que trae el remoto).
UBICACIONES = [u for u in indeed.ubicaciones_por_defecto() if u[0]][:1] + [("", 0)]

RX_MX = re.compile(r"mexic|m[eé]xic|\bmx\b|cdmx|jalisco|quer[eé]taro|nuevo le")
RX_PRACTICAS = re.compile(r"practicant|becari|pasant|intern\b|internship|trainee|"
                          r"aprendiz|residencia profesional|estudiante")
RX_JUNIOR = re.compile(r"\bjr\.?\b|junior|entry.?level|nivel inicial|"
                       r"reci[eé]n egresad|\bi\b$|auxiliar|asistente")

VERDE, ROJO, AMBAR, FIN = "\033[92m", "\033[91m", "\033[93m", "\033[0m"


def _sin_color() -> bool:
    return not sys.stdout.isatty()


def marca(ok: bool, texto: str) -> str:
    """Una línea de resultado. Sin color si la salida va a un archivo."""
    simbolo = "OK  " if ok else "FALLA"
    if _sin_color():
        return f"  [{simbolo}] {texto}"
    color = VERDE if ok else ROJO
    return f"  {color}[{simbolo}]{FIN} {texto}"


def titulo(t: str) -> None:
    print(f"\n{'=' * 74}\n{t}\n{'=' * 74}")


def _pct(parte: int, total: int) -> str:
    return f"{100 * parte / total:.0f}%" if total else "n/a"


def main() -> int:
    if not indeed.activa():
        titulo("TEST DE LA FUENTE INDEED — NO EJECUTADO")
        print("  Falta INDEED_API_KEY (ver .env.example). Sin clave la API responde 401")
        print("  a todo, así que no se manda ninguna petición. No es un fallo del código.")
        return 0

    amplio = "--amplio" in sys.argv
    consultas = CONSULTAS_AMPLIO if amplio else CONSULTAS
    fallos: list[str] = []

    titulo("TEST DE LA FUENTE INDEED — peticiones reales, sin simulacros")
    print(f"  endpoint : {indeed.API}")
    print(f"  consultas: {len(consultas)} -> {', '.join(consultas)}")
    print(f"  zonas    : {', '.join(d or 'nacional' for d, _ in UBICACIONES)}")
    print(f"  paginas  : 2 por consulta y zona (tope {indeed.LIMITE} por pagina)")

    # ---------------------------------------------------------- 1. descarga --
    titulo("1. DESCARGA")
    t0 = time.time()
    vacantes, est = indeed.recolectar(
        consultas=consultas, ubicaciones=UBICACIONES, paginas=2, pausa=0.15,
    )
    segundos = time.time() - t0

    print(f"\n  URLs pedidas: {est['urls_pedidas']} en {segundos:.1f}s "
          f"({segundos / max(est['urls_pedidas'], 1):.2f}s por peticion)\n")
    print(f"  {'consulta':26} {'zona':18} {'pag':>3} {'HTTP':>5} {'vac':>4}  error")
    print(f"  {'-' * 26} {'-' * 18} {'-' * 3} {'-' * 5} {'-' * 4}  {'-' * 22}")
    for d in est["detalle"]:
        print(f"  {d['consulta'][:26]:26} {d['zona'][:18]:18} {d['pagina']:>3} "
              f"{d['http']:>5} {d['vacantes']:>4}  {d['error'][:22]}")

    print(f"\n  codigos HTTP observados: {est['codigos'] or 'ninguno'}")
    print(f"  HTTP 200 : {est['http_200']}/{est['urls_pedidas']} "
          f"({_pct(est['http_200'], est['urls_pedidas'])})")
    print(f"  otros    : {est['http_otros']}   errores de red: {est['errores_red']}"
          f"   errores GraphQL: {est['errores_graphql']}")

    ok_http = est["http_200"] == est["urls_pedidas"] and est["urls_pedidas"] > 0
    print(marca(ok_http, "todas las peticiones responden 200"))
    if not ok_http:
        fallos.append(
            f"HTTP: solo {est['http_200']} de {est['urls_pedidas']} dieron 200; "
            f"codigos {est['codigos']}"
        )

    ok_gql = est["errores_graphql"] == 0
    print(marca(ok_gql, "ninguna respuesta trae errores de GraphQL"))
    if not ok_gql:
        fallos.append(f"GraphQL: {est['errores_graphql']} respuestas con errores")

    # ---------------------------------------------------------- 2. extraccion --
    titulo("2. EXTRACCION")
    n = len(vacantes)
    print(f"  vacantes crudas : {est['vacantes_crudas']}")
    print(f"  vacantes unicas : {n}  "
          f"(se descartaron {est['vacantes_crudas'] - n} repetidas entre consultas)")

    ok_hay = n > 0
    print(marca(ok_hay, f"el parser extrae vacantes ({n})"))
    if not ok_hay:
        fallos.append("el parser devolvio CERO vacantes")
        # Sin vacantes no tiene sentido medir campos: se corta aquí.
        return veredicto(fallos, n, est)

    # --------------------------------------------------------- 3. los campos --
    titulo("3. CAMPOS POBLADOS")
    campos = {
        "titulo": lambda v: bool(v["titulo"]),
        "empresa": lambda v: bool(v["empresa"]),
        "url": lambda v: v["url"].startswith("http"),
        "ubicacion": lambda v: bool(v["ubicacion"]),
        "descripcion": lambda v: len(v["descripcion"]) > 200,
        "publicado": lambda v: bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", v["publicado"])),
        "salario": lambda v: bool(v["salario"]),
    }
    # Estos tienen que estar en casi todas; el salario y la empresa concreta no
    # siempre existen (hay vacantes confidenciales y sin sueldo publicado), así
    # que se les exige menos.
    minimos = {"titulo": 100, "empresa": 100, "url": 100, "ubicacion": 95,
               "descripcion": 90, "publicado": 90, "salario": 10}

    for campo, prueba in campos.items():
        con = sum(1 for v in vacantes if prueba(v))
        porcentaje = 100 * con / n
        ok = porcentaje >= minimos[campo]
        print(marca(ok, f"{campo:12} poblado en {con:4}/{n} ({porcentaje:5.1f}%) "
                        f"— minimo exigido {minimos[campo]}%"))
        if not ok:
            fallos.append(f"campo '{campo}' solo poblado en {porcentaje:.0f}% "
                          f"(se exige {minimos[campo]}%)")

    largos = sorted(len(v["descripcion"]) for v in vacantes)
    print(f"\n  longitud de descripcion: mediana {largos[len(largos) // 2]}, "
          f"minima {largos[0]}, maxima {largos[-1]} caracteres")

    # ------------------------------------------------------- 4. pertinencia --
    zona = areas.zona()
    hay_zona = bool(zona["subcadenas"])
    titulo(f"4. PERTINENCIA (zona base: {zona['etiqueta']})")
    en_zona = [v for v in vacantes if areas.en_zona(v["ubicacion"])]
    mx = [v for v in vacantes
          if RX_MX.search(normalizar(v["ubicacion"])) or areas.en_zona(v["ubicacion"])]
    practicas = [v for v in vacantes if RX_PRACTICAS.search(normalizar(v["titulo"]))]
    junior = [v for v in vacantes if RX_JUNIOR.search(normalizar(v["titulo"]))]
    inicial = {v["id"] for v in practicas} | {v["id"] for v in junior}
    remotas = [v for v in vacantes if v["extra"].get("remoto_flag")]
    con_practicas_atrib = [v for v in vacantes if v["extra"].get("practicas")]

    print(f"  en la zona base                             : {len(en_zona):4} "
          f"({_pct(len(en_zona), n)})")
    print(f"  ubicadas en Mexico                          : {len(mx):4} "
          f"({_pct(len(mx), n)})")
    print(f"  de practicas segun el titulo                : {len(practicas):4} "
          f"({_pct(len(practicas), n)})")
    print(f"  junior o nivel inicial segun el titulo      : {len(junior):4} "
          f"({_pct(len(junior), n)})")
    print(f"  practicas O junior (sin repetir)            : {len(inicial):4} "
          f"({_pct(len(inicial), n)})")
    print(f"  marcadas Home Office por Indeed             : {len(remotas):4} "
          f"({_pct(len(remotas), n)})")
    print(f"  con atributo de practicas de Indeed         : {len(con_practicas_atrib):4} "
          f"({_pct(len(con_practicas_atrib), n)})")

    if hay_zona:
        ok_zona = len(en_zona) >= 10
        print(marca(ok_zona, f"hay vacantes de la zona base ({len(en_zona)}, se exigen 10)"))
        if not ok_zona:
            fallos.append(f"solo {len(en_zona)} vacantes de la zona base")
    else:
        print("  (zona `nacional`: no hay zona base, no se exige un minimo por zona)")

    ok_ini = len(inicial) >= 10
    print(marca(ok_ini, f"hay vacantes de practicas o junior ({len(inicial)}, se exigen 10)"))
    if not ok_ini:
        fallos.append(f"solo {len(inicial)} vacantes de practicas o junior")

    # --------------------------------------------------------- 5. el formato --
    titulo("5. FORMATO: ¿ENCAJA CON EL RESTO DEL SISTEMA?")
    esperadas = set(vacante(titulo="x", empresa="y", url="z", fuente="w").keys())
    reales = set(vacantes[0].keys())
    ok_claves = reales == esperadas
    print(marca(ok_claves, "las claves son exactamente las de nucleo.vacante()"))
    if not ok_claves:
        fallos.append(f"claves distintas: sobran {reales - esperadas}, "
                      f"faltan {esperadas - reales}")

    ok_fuente = all(v["fuente"] == "indeed" for v in vacantes)
    print(marca(ok_fuente, "todas se identifican con fuente='indeed'"))
    if not ok_fuente:
        fallos.append("hay vacantes con la fuente mal puesta")

    ids = {v["id"] for v in vacantes}
    ok_ids = len(ids) == n
    print(marca(ok_ids, f"los ids no se repiten ({len(ids)} ids para {n} vacantes)"))
    if not ok_ids:
        fallos.append(f"ids repetidos: {n - len(ids)}")

    # La clasificacion geografica lee extra['remoto_flag']. Si esta fuente
    # escribiera otro nombre, la señal de home office se perderia en silencio:
    # el sistema seguiria funcionando y clasificando peor.
    ok_flag = all("remoto_flag" in v["extra"] for v in vacantes)
    print(marca(ok_flag, "extra['remoto_flag'] existe — es el nombre que lee analisis.py"))
    if not ok_flag:
        fallos.append("extra['remoto_flag'] ausente: analisis.py no vera el home office")

    ok_html = not any("<div" in v["descripcion"] or "&nbsp;" in v["descripcion"]
                      for v in vacantes)
    print(marca(ok_html, "las descripciones vienen sin HTML crudo"))
    if not ok_html:
        fallos.append("hay descripciones con HTML sin limpiar")

    # ------------------------------------------------ 6. via de la excavadora --
    titulo("6. VIA DE LA EXCAVADORA (peticiones + red.py)")
    ps = indeed.peticiones()
    soporta = indeed._red_soporta_cabeceras()
    print(f"  red.Peticion admite cabeceras por peticion: {'si' if soporta else 'NO'}")
    print(f"  peticiones() declara: {len(ps)} URLs")

    if soporta:
        ok_via = len(ps) > 0
        print(marca(ok_via, "la fuente esta activa para la excavadora"))
        if not ok_via:
            fallos.append("red.py admite cabeceras pero peticiones() devuelve cero")
    else:
        # Con red.py sin parchear, la unica respuesta correcta es cero. Declarar
        # peticiones que van a dar 401 es peor que no declarar ninguna.
        ok_via = len(ps) == 0
        print(marca(ok_via, "devuelve cero en vez de URLs que darian 401 "
                            "(fallo ruidoso, no silencioso)"))
        if not ok_via:
            fallos.append(f"peticiones() declara {len(ps)} URLs que responderan 401 "
                          f"porque red.py no manda la cabecera indeed-api-key")
        print("  NOTA: para activarla hay que anadir `cabeceras` a red.Peticion. "
              "Ver el docstring de peticiones().")

    # ------------------------------------------------------------- ejemplos --
    titulo("EJEMPLOS REALES (6 de la zona base, o los primeros que haya)")
    muestra = (en_zona or vacantes)[:6]
    for i, v in enumerate(muestra, 1):
        etiquetas = []
        if v["extra"].get("remoto_flag"):
            etiquetas.append("home-office")
        if v["extra"].get("hibrido"):
            etiquetas.append("hibrido")
        if v["extra"].get("practicas"):
            etiquetas.append("practicas")
        print(f"\n  {i}. {v['titulo']}")
        print(f"     empresa   : {v['empresa']}")
        print(f"     ubicacion : {v['ubicacion']}")
        print(f"     publicado : {v['publicado'] or '(sin fecha)'}"
              f"   salario: {v['salario'] or '(no publicado)'}")
        print(f"     url       : {v['url']}")
        print(f"     descripcion: {len(v['descripcion'])} caracteres"
              f"{'   [' + ', '.join(etiquetas) + ']' if etiquetas else ''}")
        print(f"     inicio    : {v['descripcion'][:110]}...")

    return veredicto(fallos, n, est)


def veredicto(fallos: list[str], n: int, est: dict) -> int:
    titulo("VEREDICTO")
    if not fallos:
        print(f"  FUNCIONA\n")
        print(f"  Evidencia: {est['http_200']} de {est['urls_pedidas']} peticiones "
              f"respondieron HTTP 200, sin errores de GraphQL,")
        print(f"  y de ellas salieron {n} vacantes unicas con los campos poblados "
              f"y en el formato de nucleo.vacante().")
        print(f"  Codigos observados: {est['codigos']}")
        return 0

    print(f"  NO FUNCIONA\n")
    print(f"  Evidencia — {len(fallos)} comprobacion(es) fallidas:")
    for f in fallos:
        print(f"    - {f}")
    print(f"\n  Codigos HTTP observados : {est['codigos'] or 'ninguno'}")
    print(f"  Peticiones enviadas     : {est['urls_pedidas']}")
    print(f"  Errores de red          : {est['errores_red']}")
    print(f"  Errores de GraphQL      : {est['errores_graphql']}")
    print(f"  Vacantes obtenidas      : {n}")
    if est["detalle"]:
        print(f"\n  Primeras respuestas no-200:")
        malas = [d for d in est["detalle"] if d["http"] != 200][:8]
        for d in malas or [{"consulta": "(ninguna)", "zona": "", "http": "-", "error": ""}]:
            print(f"    HTTP {d['http']} | {d['consulta']} / {d['zona']} | {d['error']}")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrumpido")
        sys.exit(130)
