"""
Correos en frio: escribirle a una persona, no postular a una vacante.

En que se diferencia del generador de postulaciones. `generador_correos.py`
responde a un anuncio: el lector espera ese correo. Aqui NADIE lo espera, y
eso cambia todas las reglas:

  - **Corto o muerto.** Quien decide contrataciones decide en diez segundos si
    sigue leyendo. Maximo ~120 palabras de cuerpo; cada frase que no aporta,
    resta.
  - **El asunto no puede parecer spam.** Nada de "Oportunidad", "Candidato
    disponible" ni mayusculas. Funciona lo concreto: que es y que pide.
  - **Un solo pedido, y pequeño.** No se pide trabajo: se piden 15 minutos o
    una referencia. A un desconocido no se le pide un contrato; se le pide
    algo que pueda dar sin pensarlo dos veces.
  - **Por que ELLOS, demostrado.** La primera linea tiene que probar que no es
    un correo en masa: nombra algo de la empresa (sus vacantes, sus
    herramientas) que solo sabe quien la miro de verdad. El dato sale de la
    tabla `empresas`, que lo dedujo de sus propios anuncios.

Y la regla que manda sobre todas: **ningun hecho que no este en `perfil.py`**.
Un dato inventado no se corrige despues: quema al candidato con esa empresa
para siempre.

Uso:
    python correos_frios.py                      # borradores para los objetivos con contacto
    python correos_frios.py --empresa "Nombre"
"""
from __future__ import annotations

import argparse

import areas
from almacen import conexion
from perfil import CANDIDATO, LOGROS, POSTULACION


def _logros() -> list[str]:
    """Logros del perfil: primero los de las areas activas, luego los generales."""
    salida: list[str] = []
    for clave in areas.claves_activas():
        salida += LOGROS.get(clave, [])
    return salida + list(LOGROS.get("general", []))


def _angulo(empresa: dict) -> str:
    """Que historia contar segun que hace la empresa.

    No es lo mismo escribirle a quien decide en una empresa con vacantes de tus
    areas que a una camara o asociacion, que presenta pero no contrata.
    """
    sector = (empresa.get("sector") or "").lower()
    if any(x in sector for x in ("cluster", "asociacion", "camara", "comunidad")):
        return "presentacion"
    if empresa.get("vacantes_ciber"):
        return "area"
    return "general"


def _gancho(empresa: dict, angulo: str) -> str:
    """La primera linea: la prueba de que este correo no es en masa."""
    nombre = empresa.get("nombre_limpio") or empresa.get("nombre") or "su empresa"
    stack = [s for s in (empresa.get("stack") or "").split(",") if s][:3]

    if angulo == "presentacion":
        return (f"Sigo el trabajo de {nombre} conectando a las empresas de su "
                "sector, y por eso le escribo a usted.")
    if angulo == "area" and stack:
        return (f"Vi que {nombre} esta creciendo su equipo (sus vacantes nombran "
                f"{', '.join(stack)}), y por eso le escribo a usted y no a un "
                "buzon generico.")
    if angulo == "area":
        return (f"Vi que {nombre} tiene operacion propia en mi area, y por eso le "
                "escribo a usted directamente.")
    return (f"Investigue que empresas de {areas.zona()['corta']} tienen operacion "
            f"real en mi area, y {nombre} esta en mi lista corta.")


def generar_frio(empresa: dict, contacto: dict) -> dict:
    """Devuelve {'asunto', 'cuerpo', 'avisos'} para un contacto concreto."""
    angulo = _angulo(empresa)
    logros = _logros()
    nombre_e = empresa.get("nombre_limpio") or empresa.get("nombre") or ""
    # Solo el nombre de pila: el nombre completo es la firma de un correo en
    # masa, que es exactamente lo que este correo debe no parecer, y ademas
    # evita adivinar el genero por el apellido.
    pila = (contacto.get("nombre") or "").strip().split(" ")[0]
    trato = f"Estimado/a {pila}" if pila else "Estimado equipo"
    etiquetas = ", ".join(areas.AREAS[c]["etiqueta"].lower() for c in areas.claves_activas())

    # Un solo pedido, pequeño. A una asociacion se le pide difusion; a los
    # demas, quince minutos o que digan a quien si.
    if angulo == "presentacion":
        pedido = ("¿Habria forma de que mi perfil llegue a las empresas que reciben "
                  "practicantes? Adjunto CV; con una linea suya me basta.")
    else:
        pedido = ("¿Tendria 15 minutos en las proximas semanas para platicarme "
                  "como se entra a un equipo como el suyo? Y si usted no es la "
                  "persona indicada, le agradeceria que me diga quien si.")

    carrera = POSTULACION.get("carrera")
    titulado = POSTULACION.get("titulado") is True
    if carrera:
        verbo = "Soy egresado/a de" if titulado else "Estudio"
        presentacion = f"{verbo} {carrera} y busco practicas o mi primer empleo en {etiquetas}."
    else:
        presentacion = f"Busco practicas o mi primer empleo en {etiquetas}."
    if logros:
        # "Sin experiencia formal" solo si perfil.py lo dice (0 anios): con el
        # dato vacio, afirmarlo seria inventar.
        inicio = (" Sin experiencia formal todavia, pero con trabajo que se puede revisar: "
                  if POSTULACION.get("anios_experiencia") == 0
                  else " Trabajo que se puede revisar: ")
        presentacion += f"{inicio}{'; '.join(logros[:2])}."

    firma = [CANDIDATO.get("nombre") or "", CANDIDATO.get("linkedin") or "",
             " · ".join(x for x in (CANDIDATO.get("github"), CANDIDATO.get("telefono")) if x)]
    cuerpo = (f"{trato}:\n\n{_gancho(empresa, angulo)}\n\n{presentacion}\n\n{pedido}"
              "\n\nSaludos,\n" + "\n".join(linea for linea in firma if linea))

    # Quien escribe, solo si perfil.py lo dice; sin carrera no se presupone nada.
    if carrera:
        prefijo = (f"Egresado/a de {carrera} — " if titulado
                   else f"Estudiante de {carrera} — ")
    else:
        prefijo = ""
    asunto = {
        "presentacion": f"{prefijo}busco llegar a las empresas de su red",
        "area": f"{prefijo}pregunta breve sobre {nombre_e}",
        "general": f"{prefijo}pregunta breve sobre practicas en {nombre_e}",
    }[angulo]
    asunto = asunto[:1].upper() + asunto[1:]

    avisos = []
    if "EJEMPLO" in (CANDIDATO.get("nombre") or ""):
        avisos.append("perfil.py sigue siendo la plantilla de EJEMPLO: rellenalo antes "
                      "de enviar nada.")
    if not logros:
        avisos.append("No hay LOGROS en perfil.py: el correo no puede mostrar trabajo "
                      "verificable, y en frio eso es casi todo.")
    if (contacto.get("correo_origen") or "") == "inferido-por-patron":
        avisos.append(
            "EL CORREO ES DEDUCIDO POR PATRON Y PUEDE REBOTAR. Si rebota, no "
            "reintentar variantes a ciegas: escribir por LinkedIn al perfil de "
            f"{contacto.get('nombre')} o por el formulario del sitio.")
    if not contacto.get("correo"):
        avisos.append("Sin correo: enviar por LinkedIn o el formulario del sitio.")
    if (contacto.get("confianza") or "") == "probable-caduco":
        avisos.append("El dato del puesto es viejo: CONFIRMAR que sigue en el "
                      "cargo antes de enviar, o el correo llega a la persona "
                      "equivocada y quema el intento.")
    if contacto.get("notas"):
        avisos.append(f"Contexto: {contacto['notas']}")

    return {"asunto": asunto, "cuerpo": cuerpo, "angulo": angulo,
            "avisos": avisos, "destinatario": contacto.get("correo") or "(sin correo)"}


def para_empresa(nombre: str) -> list[dict]:
    """Borradores para todos los contactos de una empresa."""
    with conexion() as con:
        filas = con.execute("""
            SELECT c.*, e.nombre AS e_nombre, e.nombre_limpio, e.sector,
                   e.stack, e.vacantes_ciber, e.via
            FROM contactos c JOIN empresas e ON e.id = c.empresa_id
            WHERE e.nombre LIKE ? OR e.nombre_limpio LIKE ?
            ORDER BY CASE c.confianza WHEN 'verificado' THEN 0
                     WHEN 'inferido' THEN 1 ELSE 2 END""",
            (f"%{nombre}%", f"%{nombre}%")).fetchall()
    salida = []
    for f in filas:
        d = dict(f)
        empresa = {k: d.get(k) for k in
                   ("nombre_limpio", "sector", "stack", "vacantes_ciber", "via")}
        empresa["nombre"] = d["e_nombre"]
        salida.append({**generar_frio(empresa, d), "contacto": d.get("nombre"),
                       "puesto": d.get("puesto"), "empresa": empresa["nombre_limpio"]})
    return salida


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--empresa", default=None)
    args = p.parse_args()

    if args.empresa:
        borradores = para_empresa(args.empresa)
    else:
        with conexion() as con:
            nombres = [r["nombre_limpio"] for r in con.execute("""
                SELECT DISTINCT e.nombre_limpio FROM contactos c
                JOIN empresas e ON e.id = c.empresa_id
                WHERE e.via != 'programa-formal' ORDER BY e.score DESC LIMIT 4""")]
        borradores = [b for n in nombres for b in para_empresa(n)[:1]]

    for b in borradores:
        print("=" * 72)
        print(f"PARA:    {b['contacto']} ({b['puesto']})")
        print(f"CORREO:  {b['destinatario']}")
        print(f"ASUNTO:  {b['asunto']}")
        print("-" * 72)
        print(b["cuerpo"])
        if b["avisos"]:
            print("-" * 72)
            for a in b["avisos"]:
                print(f"  !! {a}")
        print()
