"""
Exporta la documentacion y el codigo del proyecto a texto plano para NotebookLM.

Para que sirve. Una sesion nueva no puede leer todo el codigo, y aunque
pudiera, gastaria el contexto entero en eso. Subido a NotebookLM se le puede
preguntar "que hace el modulo Y" y responde **citando el archivo concreto**.

Complementa al panel y al README; no los sustituye. Es una copia de solo
lectura para consultar.

Datos personales. Los datos de contacto de `perfil.CANDIDATO` (correo,
telefono, nombre, perfiles) se enmascaran en todo lo exportado: no aportan
nada a ninguna pregunta que se le vaya a hacer al cuaderno, y evitan dejarlos
en un servicio externo. Los patrones se construyen desde `perfil.py`, asi que
protegen a quien tenga el perfil rellenado, no a una persona concreta.

Uso:
    python exportar_proyecto.py
"""
from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "corpus-notebooklm"


def _personales() -> list[tuple[re.Pattern, str]]:
    """Patrones de los datos de contacto del perfil, y su reemplazo.

    Se enmascara el dato, no la linea entera: asi el texto sigue leyendose
    igual y se ve que ahi habia un contacto.
    """
    from perfil import CANDIDATO

    salida: list[tuple[re.Pattern, str]] = []
    correo = (CANDIDATO.get("correo") or "").strip()
    if correo:
        salida.append((re.compile(re.escape(correo), re.I), "[correo omitido]"))
    digitos = re.sub(r"\D", "", CANDIDATO.get("telefono") or "")
    if len(digitos) >= 8:
        # Los ultimos diez digitos, admitiendo espacios o guiones entre ellos.
        salida.append((re.compile(r"[\s-]?".join(digitos[-10:])), "[telefono omitido]"))
    for clave, reemplazo in (("nombre", "[nombre omitido]"),
                             ("linkedin", "[perfil omitido]"),
                             ("github", "[perfil omitido]")):
        valor = (CANDIDATO.get(clave) or "").strip()
        if valor and "EJEMPLO" not in valor:
            salida.append((re.compile(re.escape(valor), re.I), reemplazo))
    # La CURP es el identificador con el que en Mexico se abre practicamente
    # cualquier tramite: no puede acabar en un documento que se comparte por
    # enlace. El patron es el formato oficial, no una CURP concreta.
    salida.append((re.compile(r"\b[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]{2}\b"), "[CURP omitida]"))
    return salida


GRUPOS = [
    ("proyecto-guia-del-sistema", "Guia de uso del sistema ULTRA CHAMBA",
     ["README.md"]),
    ("proyecto-codigo-fuente", "Codigo fuente completo", ["app/*.py"]),
]


def _limpiar(texto: str, patrones: list[tuple[re.Pattern, str]]) -> str:
    for patron, reemplazo in patrones:
        texto = patron.sub(reemplazo, texto)
    return texto


def _recolectar(patrones: list[str]) -> list[Path]:
    vistos: list[Path] = []
    for patron in patrones:
        for ruta in sorted(RAIZ.glob(patron)):
            if ruta.is_file() and ruta not in vistos:
                vistos.append(ruta)
    return vistos


def exportar() -> dict:
    SALIDA.mkdir(exist_ok=True)
    resumen = {}
    personales = _personales()

    for nombre, titulo, patrones in GRUPOS:
        archivos = _recolectar(patrones)
        if not archivos:
            continue

        partes = [
            f"{titulo.upper()}\n"
            f"Parte del proyecto ULTRA CHAMBA (version general, para cualquier carrera).\n"
            f"{len(archivos)} archivos. Cada bloque empieza con 'ARCHIVO:' y su "
            f"ruta real dentro del proyecto, para que cualquier respuesta pueda "
            f"rastrearse hasta el archivo concreto.\n"
            f"Los datos de contacto del perfil estan omitidos a proposito.\n"
        ]
        for ruta in archivos:
            rel = ruta.relative_to(RAIZ).as_posix()
            try:
                contenido = ruta.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                contenido = ruta.read_text(encoding="latin-1")
            partes.append(
                f"\n{'=' * 80}\nARCHIVO: {rel}\n{'-' * 80}\n{_limpiar(contenido, personales)}\n")

        cuerpo = "".join(partes)
        destino = SALIDA / f"{nombre}.txt"
        destino.write_text(cuerpo, encoding="utf-8")
        resumen[nombre] = {"archivos": len(archivos), "palabras": len(cuerpo.split()),
                           "kb": round(len(cuerpo.encode("utf-8")) / 1024)}

    return resumen


def comprobar_fugas() -> list[str]:
    """Ultima red: busca los datos de contacto del perfil en lo ya escrito."""
    fugas = []
    patrones = _personales()
    for txt in SALIDA.glob("*.txt"):
        contenido = txt.read_text(encoding="utf-8")
        for patron, reemplazo in patrones:
            if patron.search(contenido):
                fugas.append(f"{txt.name}: {reemplazo}")
    return fugas


if __name__ == "__main__":
    res = exportar()
    print(f"corpus del proyecto en {SALIDA}")
    for nombre, r in res.items():
        print(f"  {nombre:30} {r['archivos']:4} archivos  "
              f"{r['palabras']:8,} palabras  {r['kb']:5} KB")

    fugas = comprobar_fugas()
    if fugas:
        print("\n!! SE ESCAPARON DATOS PERSONALES:")
        for f in fugas:
            print(f"   {f}")
        raise SystemExit(1)
    print("\ncomprobado: ningun dato de contacto del perfil en la salida")
