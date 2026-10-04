"""
Sincroniza el corpus de vacantes con Google Drive, para que NotebookLM se
actualice solo.

Como funciona el truco. NotebookLM no tiene API publica, asi que no se le
puede subir nada por programa. Pero desde el 26 de mayo de 2026 mantiene una
**conexion viva con Google Drive**: cuando una fuente del cuaderno es un
documento nativo de Workspace, NotebookLM relee el original cada pocos minutos
por su cuenta. Entonces el camino es:

    excavadora -> exportar_corpus -> ESTE MODULO actualiza el Doc en Drive
                                  -> NotebookLM lo absorbe solo

Nadie pulsa nada. Lo unico que hay que respetar es que el documento sea un
Google Doc nativo: un .txt subido a Drive **no** se sincroniza nunca.

Requisito que solo puede cumplir el usuario: unas credenciales OAuth de
escritorio (`credenciales_drive.json`). Ver README, seccion 5.3.

Permisos. Se pide el alcance MINIMO, `drive.file`: solo da acceso a los
archivos que crea este propio programa. No puede leer ni tocar el resto del
Drive de la cuenta aunque quisiera.

Uso:
    python sincronizar_drive.py            # regenera el corpus y lo sube
    python sincronizar_drive.py --estado   # que documentos existen ya
    python sincronizar_drive.py --minimo 10  # solo sube si hay >=10 nuevas
"""
from __future__ import annotations

import argparse
import io
import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
DATOS = RAIZ / "datos"
CREDENCIALES = DATOS / "credenciales_drive.json"
TOKEN = DATOS / "token_drive.json"
REGISTRO = DATOS / "drive_documentos.json"

# Que se sube al cuaderno.
#
#   area-*                 vacantes, un archivo por area activa: el corpus
#                          grande, lo que ninguna ventana de contexto puede
#                          leer entero. Es la razon de ser de NotebookLM.
#   proyecto-guia-*        el README: como se usa el sistema, consultable
#                          desde el movil.
#
# Fuera se queda, a proposito, `proyecto-codigo-fuente`: medio mega de Python.
# Quien necesita leer el codigo lo tiene en el disco; en un cuaderno solo diluye
# las citas.
#
# La leccion que obliga a regenerarlos SIEMPRE (ver `sincronizar`): estos
# archivos llegaron a estar congelados semanas sin que nada avisara, porque se
# generaban a mano y nadie los volvia a generar.
PREFIJOS = ("area-", "proyecto-guia-")

ALCANCE = ["https://www.googleapis.com/auth/drive.file"]
# Nombre propio de esta copia. Si la misma cuenta de Google autoriza otra copia
# del sistema, cada una crea su carpeta: con el mismo nombre serian carpetas
# homonimas e indistinguibles al enlazarlas como fuentes.
CARPETA = "Ultrachamba general - corpus"

# Un Google Doc admite algo mas de un millon de caracteres. Se deja margen y
# se corta SIEMPRE en el limite de una vacante, nunca a mitad de un anuncio:
# una ficha partida en dos documentos produciria citas sin sentido.
MAXIMO = 900_000
SEPARADOR = "=" * 80


def _servicio():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    cred = None
    if TOKEN.exists():
        cred = Credentials.from_authorized_user_file(str(TOKEN), ALCANCE)
    if not cred or not cred.valid:
        renovado = False
        if cred and cred.expired and cred.refresh_token:
            try:
                cred.refresh(Request())
                renovado = True
            except Exception as ex:
                # Revocado o caducado del todo: refrescar no sirve, hay que
                # volver a pedir consentimiento. Ver la cabecera de este bloque.
                print(f"  el token de Drive ya no vale ({ex}); pidiendo autorizacion de nuevo")
                cred = None
        if not renovado:
            if not CREDENCIALES.exists():
                raise SystemExit(
                    f"Falta {CREDENCIALES}.\n"
                    "Es el archivo de credenciales OAuth de escritorio que se\n"
                    "descarga de Google Cloud Console. Ver README, seccion 5.3\n"
                    "(Gmail y Google Drive).")
            flujo = InstalledAppFlow.from_client_secrets_file(str(CREDENCIALES), ALCANCE)
            cred = flujo.run_local_server(port=0)
        TOKEN.write_text(cred.to_json(), encoding="utf-8")
    return build("drive", "v3", credentials=cred)


def _registro() -> dict:
    if REGISTRO.exists():
        return json.loads(REGISTRO.read_text(encoding="utf-8"))
    return {}


def _guardar_registro(reg: dict) -> None:
    DATOS.mkdir(exist_ok=True)
    REGISTRO.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8")


def _partir(texto: str) -> list[str]:
    """Parte en trozos que quepan en un Google Doc, cortando entre vacantes."""
    if len(texto) <= MAXIMO:
        return [texto]
    bloques = texto.split(f"\n{SEPARADOR}\n")
    cabecera, fichas = bloques[0], bloques[1:]
    trozos, actual = [], cabecera
    for ficha in fichas:
        candidato = f"{actual}\n{SEPARADOR}\n{ficha}"
        if len(candidato) > MAXIMO and actual != cabecera:
            trozos.append(actual)
            actual = f"{cabecera}\n{SEPARADOR}\n{ficha}"
        else:
            actual = candidato
    trozos.append(actual)
    return trozos


def _carpeta(servicio) -> str:
    reg = _registro()
    if reg.get("_carpeta"):
        return reg["_carpeta"]
    creada = servicio.files().create(
        body={"name": CARPETA, "mimeType": "application/vnd.google-apps.folder"},
        fields="id").execute()
    reg["_carpeta"] = creada["id"]
    _guardar_registro(reg)
    return creada["id"]


def _subir(servicio, nombre: str, texto: str, carpeta: str, reg: dict) -> dict:
    """Crea el Doc la primera vez; despues REEMPLAZA su contenido.

    Reemplazar es lo importante: el documento conserva su identificador, y por
    tanto la fuente que NotebookLM ya tiene enlazada sigue siendo la misma. Si
    en vez de eso se creara un documento nuevo cada vez, el cuaderno seguiria
    leyendo el viejo para siempre.
    """
    from googleapiclient.http import MediaIoBaseUpload

    medio = MediaIoBaseUpload(
        io.BytesIO(texto.encode("utf-8")), mimetype="text/plain", resumable=False)

    if nombre in reg:
        archivo = servicio.files().update(
            fileId=reg[nombre], media_body=medio,
            fields="id,webViewLink,modifiedTime").execute()
        archivo["accion"] = "actualizado"
    else:
        archivo = servicio.files().create(
            body={"name": nombre, "parents": [carpeta],
                  # Esto es lo que convierte el texto en Doc NATIVO, que es
                  # el unico formato que NotebookLM sincroniza solo.
                  "mimeType": "application/vnd.google-apps.document"},
            media_body=medio, fields="id,webViewLink,modifiedTime").execute()
        archivo["accion"] = "creado"
        reg[nombre] = archivo["id"]
    return archivo


def _cambios_desde_ultima() -> int:
    """Cuanto ha cambiado el corpus desde la corrida anterior: ALTAS + BAJAS.

    Antes solo contaba altas, y ese era un fallo silencioso de los peores: una
    corrida donde se cerraran 40 vacantes y aparecieran 3 no superaba el minimo,
    no subia nada, y NotebookLM seguia citando 40 anuncios muertos. Una vacante
    que desaparece es tan relevante como una que aparece: mas, incluso, porque
    mandar a alguien a una puerta cerrada le cuesta tiempo real.
    """
    try:
        from almacen import conexion
        with conexion() as con:
            corridas = [r["id"] for r in con.execute(
                "SELECT id FROM corridas WHERE guardadas > 0 ORDER BY id DESC LIMIT 2")]
            if len(corridas) < 2:
                return 10**6          # sin historial, se sube siempre
            ult, prev = corridas[0], corridas[1]
            altas = con.execute("""
                SELECT COUNT(*) n FROM vacantes WHERE score >= 40
                  AND id IN (SELECT vacante_id FROM avistamientos WHERE corrida_id=?)
                  AND id NOT IN (SELECT vacante_id FROM avistamientos WHERE corrida_id=?)
                """, (ult, prev)).fetchone()["n"]
            bajas = con.execute("""
                SELECT COUNT(*) n FROM vacantes WHERE score >= 40
                  AND id IN (SELECT vacante_id FROM avistamientos WHERE corrida_id=?)
                  AND id NOT IN (SELECT vacante_id FROM avistamientos WHERE corrida_id=?)
                """, (prev, ult)).fetchone()["n"]
            return altas + bajas
    except Exception:
        return 10**6


# Nombre anterior, conservado por si algo externo lo llama.
_nuevas_desde_ultima = _cambios_desde_ultima


def sincronizar(minimo_nuevas: int = 0, regenerar: bool = True) -> dict:
    if minimo_nuevas > 0:
        nuevas = _cambios_desde_ultima()
        if nuevas < minimo_nuevas:
            return {"omitido": True, "nuevas": nuevas,
                    "motivo": f"solo {nuevas} cambios (altas+bajas), el minimo es {minimo_nuevas}"}

    if regenerar:
        import exportar_corpus
        exportar_corpus.exportar()
        # Y tambien la boveda y el perfil. Si esto no se regenera aqui, vuelve
        # a pasar lo del 17 de agosto: el cuaderno sigue contestando con un
        # texto viejo y nadie se entera, porque una respuesta desactualizada
        # no se distingue de una correcta.
        import exportar_proyecto
        exportar_proyecto.exportar()
        fugas = exportar_proyecto.comprobar_fugas()
        if fugas:
            raise SystemExit(
                "ABORTADO: datos personales en el corpus antes de subirlo:\n  "
                + "\n  ".join(fugas))

    from exportar_corpus import SALIDA
    servicio = _servicio()
    carpeta = _carpeta(servicio)
    reg = _registro()
    resultados = []

    for archivo in sorted(SALIDA.glob("*.txt")):
        if not archivo.name.startswith(PREFIJOS):
            continue
        texto = archivo.read_text(encoding="utf-8")
        trozos = _partir(texto)
        for i, trozo in enumerate(trozos, 1):
            # El nombre NO puede llevar el total de trozos. Se llamaban
            # "area-ti-general (1 de 3)", y al crecer el corpus a 5 trozos los
            # nombres cambiaban: se creaban documentos nuevos y los viejos
            # quedaban vivos en Drive, todavia enlazados como fuentes en
            # NotebookLM, sirviendo vacantes obsoletas mezcladas con las buenas.
            # Asi se acumularon 13 documentos donde hacian falta 8.
            # El identificador debe ser estable aunque cambie el numero de partes.
            nombre = f"{archivo.stem} parte {i}"
            subido = _subir(servicio, nombre, trozo, carpeta, reg)
            resultados.append({"nombre": nombre, "accion": subido["accion"],
                               "enlace": subido.get("webViewLink"),
                               "caracteres": len(trozo)})

    # Los documentos registrados que esta corrida no ha actualizado ya no
    # forman parte del corpus: si siguen enlazados en NotebookLM, contestaria
    # con datos viejos sin que nadie lo note. Se avisa por nombre; el borrado
    # se deja al humano porque puede haber fuentes enlazadas a mano.
    vigentes = {d["nombre"] for d in resultados}
    huerfanos = [k for k in reg if not k.startswith("_") and k not in vigentes]

    _guardar_registro(reg)
    return {"omitido": False, "documentos": resultados, "huerfanos": huerfanos,
            "carpeta": f"https://drive.google.com/drive/folders/{carpeta}"}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--estado", action="store_true",
                   help="muestra los documentos ya creados y no sube nada")
    p.add_argument("--minimo", type=int, default=0,
                   help="no subir si hay menos de N vacantes nuevas")
    p.add_argument("--sin-regenerar", action="store_true",
                   help="usa el corpus que ya esta en disco")
    args = p.parse_args()

    if args.estado:
        reg = _registro()
        docs = {k: v for k, v in reg.items() if not k.startswith("_")}
        if not docs:
            print("todavia no hay documentos en Drive")
        for nombre, ident in docs.items():
            print(f"  {nombre:44} https://docs.google.com/document/d/{ident}")
        print(f"\nnuevas desde la corrida anterior: {_nuevas_desde_ultima()}")
        raise SystemExit(0)

    res = sincronizar(args.minimo, regenerar=not args.sin_regenerar)
    reg_final = _registro()
    if res.get("omitido"):
        print(f"no se subio nada: {res['motivo']}")
    else:
        for d in res["documentos"]:
            print(f"  {d['accion']:11} {d['nombre']:44} {d['caracteres']:>9,} caracteres")
        print(f"\ncarpeta en Drive: {res['carpeta']}")
        print("NotebookLM releera estos documentos solo, en unos minutos.")
