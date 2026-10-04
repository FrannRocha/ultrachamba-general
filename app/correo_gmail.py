"""
Deja el correo como BORRADOR en el Gmail de quien usa el sistema, listo para enviar.

Por que borrador y no envio directo. Lo que se busca es "ver la vacante y dar
enviar", y eso es exactamente lo que consigue un borrador: abre Gmail, lee lo
que dice, y pulsa Enviar. La diferencia con enviarlo desde aqui no es tecnica,
es de control: el correo sale de SU cuenta cuando la persona lo decide, con la
oportunidad de cambiar una frase si quiere. Un sistema que manda correos solo
en nombre de alguien es un sistema del que hay que desconfiar; uno que los
deja escritos y esperando es una herramienta.

Ademas resuelve el problema practico: hoy hay que copiar el texto del panel y
pegarlo. Copiar y pegar no es "dar enviar".

Permisos. Se piden dos: `gmail.compose` (crear y modificar borradores) y
`gmail.readonly` (leer, para saber si contestaron y cuanto lleva en silencio).
NO se pide `gmail.send`.

Aviso honesto, porque en la pantalla de consentimiento confunde: Google
etiqueta `compose` como "gestionar borradores y ENVIAR correos". Es su texto
estandar —no existe una variante de solo-borrador—, asi que el permiso
concedido lo permitiria aunque este modulo no llame nunca a `send()`. La
garantia es el codigo, no la etiqueta.

Hay que autorizarlo una vez: `credenciales_drive.json` sirve, pero el token es
aparte (`token_gmail.json`) para no tocar el de Drive. Ampliar permisos exige
rehacer el flujo entero (`--ampliar` tira el token viejo a proposito).

Uso:
    python correo_gmail.py --probar    # crea un borrador de prueba
"""
from __future__ import annotations

import argparse
import base64
import json
from email.message import EmailMessage
from pathlib import Path

from perfil import CANDIDATO

RAIZ = Path(__file__).resolve().parent
DATOS = RAIZ / "datos"
CREDENCIALES = DATOS / "credenciales_drive.json"      # las mismas de Drive
TOKEN = DATOS / "token_gmail.json"                    # token propio, aparte

# Solo crear borradores. NO se pide `gmail.send`: el sistema no debe poder
# mandar un correo por su cuenta ni por error.
ALCANCE = ["https://www.googleapis.com/auth/gmail.compose",
           "https://www.googleapis.com/auth/gmail.readonly"]

# EL ENVIO, y por que existe habiendo dicho que no.
#
# El diseno original decia "el Enviar final lo pulsa la persona" y era
# correcto mientras alguien estaba delante del ordenador. Despues se pidio otra
# cosa distinta y explicita -- poder dar el visto bueno desde el telefono y que
# el sistema envie -- porque los borradores se acumulaban sin salir.
#
# La garantia no desaparece, cambia de sitio: antes era "el sistema no puede
# enviar"; ahora es "el sistema solo puede enviar lo que la persona APROBO, una
# por una". Para que un correo salga hacen falta TRES cosas a la vez:
#
#   1. el token con `gmail.send` (se pide aparte, con `--permitir-envio`)
#   2. el interruptor `datos/permitir_envio.json`, puesto a mano
#   3. una candidatura en estado 'aprobada', que solo llega ahi por un gesto
#      en el panel
#
# Y cada envio queda escrito en `datos/envios.log`, que es la diferencia entre
# un sistema que manda correos y uno del que se puede saber que mando.
ALCANCE_ENVIO = ALCANCE + ["https://www.googleapis.com/auth/gmail.send"]
INTERRUPTOR = DATOS / "permitir_envio.json"
BITACORA_ENVIOS = DATOS / "envios.log"


def puede_leer() -> bool:
    """¿El token autorizado incluye lectura? El de solo-compose no la tiene."""
    if not TOKEN.exists():
        return False
    dado = set(json.loads(TOKEN.read_text(encoding="utf-8")).get("scopes") or [])
    return "https://www.googleapis.com/auth/gmail.readonly" in dado


def disponible() -> bool:
    """¿Esta ya autorizado? El panel lo usa para saber que boton enseñar."""
    return TOKEN.exists()


def _servicio(alcance: list[str] | None = None):
    alcance = alcance or ALCANCE
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    cred = None
    if TOKEN.exists():
        cred = Credentials.from_authorized_user_file(str(TOKEN), alcance)
        # Un token emitido con MENOS permisos de los que ahora se piden se ve
        # "valido" y luego falla al usarlo con un 403 confuso. Se tira y se
        # vuelve a pedir autorizacion, que es un clic.
        if cred and not set(alcance).issubset(set(cred.scopes or [])):
            cred = None
    if not cred or not cred.valid:
        if cred and cred.expired and cred.refresh_token:
            cred.refresh(Request())
        else:
            if not CREDENCIALES.exists():
                raise SystemExit(
                    f"Falta {CREDENCIALES}. Es el archivo de credenciales OAuth "
                    "que ya se usa para Drive.")
            flujo = InstalledAppFlow.from_client_secrets_file(str(CREDENCIALES), alcance)
            cred = flujo.run_local_server(port=0)
        TOKEN.write_text(cred.to_json(), encoding="utf-8")
    return build("gmail", "v1", credentials=cred)


def _mensaje(destinatario: str, asunto: str, cuerpo: str,
             adjuntar_cv: bool) -> tuple[str, int]:
    """Arma el correo y lo devuelve ya codificado, con cuantos adjuntos lleva."""
    msg = EmailMessage()
    msg["To"] = destinatario or ""
    msg["Subject"] = asunto
    msg["From"] = CANDIDATO["correo"]
    msg.set_content(cuerpo)

    # El CV va adjunto si esta a mano: un correo de candidatura sin CV obliga
    # al que lo recibe a pedirlo, y ese paso extra pierde candidatos.
    if adjuntar_cv:
        # Se busca por patron y no por nombre exacto para que renombrar el CV
        # no rompa el adjunto en silencio.
        pdfs = sorted(RAIZ.parent.glob("*CV*.pdf")) or sorted(RAIZ.parent.glob("*.pdf"))
        if pdfs:
            cv = pdfs[0]
            msg.add_attachment(cv.read_bytes(), maintype="application",
                               subtype="pdf", filename=cv.name)

    # Se cuenta ANTES de serializar: `bool(iter_attachments())` es siempre
    # True porque un generador vacio tambien es un objeto, asi que el panel
    # anunciaba "con el CV adjunto" incluso cuando no habia PDF ninguno.
    n_adjuntos = len(list(msg.iter_attachments()))

    return base64.urlsafe_b64encode(msg.as_bytes()).decode(), n_adjuntos


def _resultado(borrador: dict, n_adjuntos: int) -> dict:
    return {
        "id": borrador["id"],
        "mensaje_id": borrador["message"]["id"],
        # El ancla del seguimiento. Sin esto el hilo se pierde: ver cabecera.
        "hilo": borrador["message"].get("threadId"),
        # Enlace que abre ese borrador concreto en Gmail.
        "enlace": f"https://mail.google.com/mail/u/0/#drafts?compose={borrador['message']['id']}",
        "con_cv": n_adjuntos > 0,
    }


def crear_borrador(destinatario: str, asunto: str, cuerpo: str,
                   adjuntar_cv: bool = True) -> dict:
    """Crea el borrador y devuelve su identificador y enlace directo."""
    crudo, n = _mensaje(destinatario, asunto, cuerpo, adjuntar_cv)
    b = _servicio().users().drafts().create(
        userId="me", body={"message": {"raw": crudo}}).execute()
    return _resultado(b, n)


def actualizar_borrador(ident: str, destinatario: str, asunto: str, cuerpo: str,
                        adjuntar_cv: bool = True) -> dict | None:
    """Reescribe un borrador que ya existe. None si Gmail ya no lo tiene.

    Existe por un fallo que se colo el mismo dia que se puso el antiduplicado:
    al pulsar dos veces se devolvia el borrador VIEJO, asi que un correo
    corregido despues (por ejemplo al quitar el "[Nombre]" del saludo) se
    quedaba con el texto caducado esperando a que lo enviaran. Un borrador
    obsoleto es peor que un duplicado: el duplicado se ve.
    """
    from googleapiclient.errors import HttpError
    crudo, n = _mensaje(destinatario, asunto, cuerpo, adjuntar_cv)
    try:
        b = _servicio().users().drafts().update(
            userId="me", id=ident, body={"message": {"raw": crudo}}).execute()
    except HttpError as ex:
        if ex.resp.status in (403, 404):
            return None
        raise
    return _resultado(b, n)


def mensajes(consulta: str, limite: int = 10) -> list[dict]:
    """Busca con la sintaxis de Gmail y devuelve lo esencial de cada correo.

    Lo justo para saber si hubo respuesta y cuanto lleva esperando, sin volcar
    la bandeja entera. El cuerpo se pide aparte y solo cuando hace falta.

    `lista_baja` sale de la cabecera `List-Unsubscribe`, y es la forma barata y
    fiable de distinguir CORRESPONDENCIA de DIFUSION. Se anadio el 27-ago-2026
    porque `tramites.py` mezclaba la convocatoria de un programa de formacion
    con boletines de bolsas de trabajo: filtrar por palabras no separaba los
    dos --"curso", "oportunidad" y "vacante" salen en ambos--, y esta cabecera
    si: un boletin la lleva SIEMPRE porque la ley se lo exige, y la
    coordinacion de un programa que te escribe a ti no la lleva nunca.
    """
    s = _servicio()
    r = s.users().messages().list(userId="me", q=consulta, maxResults=limite).execute()
    salida = []
    for m in r.get("messages", []):
        d = s.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["From", "To", "Subject", "Date",
                             "List-Unsubscribe", "Precedence"]).execute()
        h = {x["name"]: x["value"] for x in d["payload"]["headers"]}
        # Las cabeceras llegan con la caja que puso el remitente ("List-Unsubscribe",
        # "LIST-UNSUBSCRIBE"), asi que se comparan en minusculas o se pierden unas
        # cuantas en silencio.
        bajas = {k.lower(): v for k, v in h.items()}
        salida.append({"id": m["id"], "hilo": d.get("threadId"),
                       "de": h.get("From", ""), "para": h.get("To", ""),
                       "asunto": h.get("Subject", ""), "fecha": h.get("Date", ""),
                       "resumen": d.get("snippet", ""),
                       "lista_baja": bool(bajas.get("list-unsubscribe")
                                          or bajas.get("precedence", "").lower()
                                          in ("bulk", "list", "junk")),
                       "etiquetas": d.get("labelIds", [])})
    return salida


def puede_enviar() -> tuple[bool, str]:
    """¿Estan las tres llaves puestas? Devuelve (si/no, por que no).

    Se devuelve el motivo y no solo un booleano porque "no puedo enviar" tiene
    tres causas distintas y cada una se arregla de otra forma. Un False pelado
    obliga a adivinar cual es, y adivinar acaba en "vuelve a autorizar" cuando
    lo que faltaba era el interruptor.
    """
    if not TOKEN.exists():
        return False, "Gmail no esta autorizado (`python correo_gmail.py --ampliar`)."
    try:
        dado = set(json.loads(TOKEN.read_text(encoding="utf-8")).get("scopes") or [])
    except (ValueError, OSError):
        return False, "El token de Gmail no se puede leer."
    if "https://www.googleapis.com/auth/gmail.send" not in dado:
        return False, ("El token no incluye permiso de ENVIO. Autoriza con "
                       "`python correo_gmail.py --permitir-envio`.")
    if not INTERRUPTOR.exists():
        return False, ("El envio automatico esta apagado. Enciendelo con "
                       "`python correo_gmail.py --activar-envio`.")
    try:
        if not json.loads(INTERRUPTOR.read_text(encoding="utf-8")).get("activo"):
            return False, "El interruptor de envio existe pero esta en 'activo: false'."
    except (ValueError, OSError):
        return False, "El interruptor de envio no se puede leer."
    return True, ""


def _anotar_envio(datos: dict) -> None:
    """Deja constancia de cada envio, pase lo que pase despues.

    Se escribe ANTES de que nadie pueda decidir que el envio "no conto". Un
    sistema que manda correos en nombre de alguien tiene que poder decir
    exactamente que mando, a quien y cuando, sin depender de que la base se
    haya actualizado bien.
    """
    try:
        BITACORA_ENVIOS.parent.mkdir(parents=True, exist_ok=True)
        with BITACORA_ENVIOS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(datos, ensure_ascii=False) + chr(10))
    except OSError:
        pass


def enviar(destinatario: str, asunto: str, cuerpo: str,
           adjuntar_cv: bool = True, hilo: str = "",
           motivo: str = "aprobada en el panel") -> dict:
    """Manda el correo de verdad. Solo si `puede_enviar()` da luz verde.

    `hilo` hace que la respuesta salga DENTRO de la conversacion existente en
    vez de abrir una nueva: insistir sobre el mismo hilo se lee como
    seguimiento, y empezar de cero se lee como otro desconocido escribiendo.
    """
    ok, porque = puede_enviar()
    if not ok:
        raise PermissionError(porque)

    crudo, n = _mensaje(destinatario, asunto, cuerpo, adjuntar_cv)
    peticion = {"raw": crudo}
    if hilo:
        peticion["threadId"] = hilo
    r = _servicio(ALCANCE_ENVIO).users().messages().send(
        userId="me", body=peticion).execute()

    salida = {"id": r["id"], "hilo": r.get("threadId"), "con_cv": n > 0,
              "destino": destinatario, "asunto": asunto}
    _anotar_envio({"cuando": __import__("datetime").datetime.now().isoformat(
        timespec="seconds"), "motivo": motivo, **salida})
    return salida


def enviar_borrador(ident: str) -> dict:
    """Manda un borrador que ya existe en Gmail, tal y como esta.

    Es la via preferida cuando el borrador ya se creo: lo que sale es
    EXACTAMENTE lo que la persona pudo leer antes de aprobar, byte a byte. Si en
    vez de esto se recompusiera el mensaje, lo aprobado y lo enviado podrian
    diferir sin que nadie lo notara.
    """
    ok, porque = puede_enviar()
    if not ok:
        raise PermissionError(porque)
    r = _servicio(ALCANCE_ENVIO).users().drafts().send(
        userId="me", body={"id": ident}).execute()
    salida = {"id": r["id"], "hilo": r.get("threadId"), "borrador": ident}
    _anotar_envio({"cuando": __import__("datetime").datetime.now().isoformat(
        timespec="seconds"), "motivo": "borrador aprobado", **salida})
    return salida


def ultimo_del_hilo(hilo: str) -> dict | None:
    """El mensaje mas reciente de un hilo, con las mismas claves que `mensajes`.

    Hace falta cuando ya se tiene el identificador del hilo y no una consulta:
    la sintaxis `q` de Gmail no sabe buscar por hilo. Lo usa `tramites.py` para
    releer un hilo ya guardado y decidir, con `lista_baja`, si era un boletin
    que se colo antes de que existiera ese filtro.
    """
    s = _servicio()
    try:
        h = s.users().threads().get(
            userId="me", id=hilo, format="metadata",
            metadataHeaders=["From", "To", "Subject", "Date",
                             "List-Unsubscribe", "Precedence"]).execute()
    except Exception:
        return None
    msgs = h.get("messages") or []
    if not msgs:
        return None
    d = max(msgs, key=lambda m: int(m.get("internalDate", 0)))
    cab = {x["name"]: x["value"] for x in d["payload"]["headers"]}
    bajas = {k.lower(): v for k, v in cab.items()}
    return {"id": d["id"], "hilo": hilo, "de": cab.get("From", ""),
            "para": cab.get("To", ""), "asunto": cab.get("Subject", ""),
            "fecha": cab.get("Date", ""), "resumen": d.get("snippet", ""),
            "lista_baja": bool(bajas.get("list-unsubscribe")
                               or bajas.get("precedence", "").lower()
                               in ("bulk", "list", "junk")),
            "etiquetas": d.get("labelIds", [])}


def texto_de(ident: str) -> str:
    """El cuerpo en texto plano de un correo concreto."""
    d = _servicio().users().messages().get(
        userId="me", id=ident, format="full").execute()
    trozos: list[str] = []

    def recorrer(parte: dict) -> None:
        if parte.get("mimeType") == "text/plain" and parte["body"].get("data"):
            trozos.append(base64.urlsafe_b64decode(
                parte["body"]["data"]).decode("utf-8", "replace"))
        for hijo in parte.get("parts", []):
            recorrer(hijo)

    recorrer(d["payload"])
    return chr(10).join(trozos)


def crear_respuesta(hilo: str, cuerpo: str, adjuntar_cv: bool = False,
                    ident: str | None = None,
                    tambien_a: list[str] | None = None) -> dict:
    """Deja un borrador DENTRO de un hilo que ya existe.

    Con `ident` REESCRIBE ese borrador en vez de crear otro. Corregir un
    correo antes de mandarlo es lo normal, y sin esto cada correccion dejaba
    una copia mas en la bandeja: el mismo fallo que ya se pago una vez.

    Insistir en un correo nuevo es empezar de cero: quien lo lee no ve el
    historial, no encuentra el folio que ya diste y responde otra vez la
    plantilla. Una respuesta en el hilo llega con todo lo anterior debajo.

    No basta con pasar el `threadId`: sin las cabeceras `In-Reply-To` y
    `References` los clientes de correo lo enganchan mal y a veces lo sacan
    del hilo. Se toman del ULTIMO mensaje, que es a lo que se contesta.
    """
    s = _servicio()
    h = s.users().threads().get(userId="me", id=hilo, format="metadata",
                                metadataHeaders=["Message-ID", "Subject", "From",
                                                 "To", "References"]).execute()
    # Los BORRADORES del hilo no cuentan. Parece un detalle y no lo es: al
    # corregir un borrador, el ultimo mensaje del hilo pasa a ser ese mismo
    # borrador, que va DE la propia cuenta -- asi que el destinatario se
    # deducia de su propio "From" y el correo se dirigia a si mismo. Se detecto
    # con un escrito ya redactado, a un clic de mandarlo al propio buzon.
    reales = [m for m in h["messages"] if "DRAFT" not in (m.get("labelIds") or [])]
    ultimo = sorted(reales, key=lambda m: int(m["internalDate"]))[-1]
    cab = {x["name"].lower(): x["value"] for x in ultimo["payload"]["headers"]}

    # A quien se contesta: si el ultimo mensaje lo mandamos nosotros, el
    # destinatario sigue siendo su "To"; si lo mandaron ellos, su "From".
    nuestro = "SENT" in (ultimo.get("labelIds") or [])
    destino = cab.get("to" if nuestro else "from", "")

    asunto = cab.get("subject", "")
    if not asunto.lower().startswith("re:"):
        asunto = "Re: " + asunto

    # Cuando la organizacion da varios buzones --hay programas que dan dos-- hay
    # que escribir a todos EN EL MISMO correo, no mandar dos copias sueltas.
    # Un hilo con ambos en el "Para" deja claro que es una sola gestion; dos
    # correos separados parecen dos personas insistiendo y se contestan peor.
    # Se evita duplicar el destinatario que ya venia del hilo.
    todos = [destino] + [d for d in (tambien_a or [])
                         if d and d.lower() not in (destino or "").lower()]

    msg = EmailMessage()
    msg["To"] = ", ".join(todos)
    msg["Subject"] = asunto
    msg["From"] = CANDIDATO["correo"]
    if mid := cab.get("message-id"):
        msg["In-Reply-To"] = mid
        msg["References"] = (cab.get("references", "") + " " + mid).strip()
    msg.set_content(cuerpo)

    if adjuntar_cv:
        pdfs = sorted(RAIZ.parent.glob("*CV*.pdf")) or sorted(RAIZ.parent.glob("*.pdf"))
        if pdfs:
            msg.add_attachment(pdfs[0].read_bytes(), maintype="application",
                               subtype="pdf", filename=pdfs[0].name)
    n = len(list(msg.iter_attachments()))

    peticion = {"message": {
        "raw": base64.urlsafe_b64encode(msg.as_bytes()).decode(),
        "threadId": hilo}}
    if ident:
        b = s.users().drafts().update(userId="me", id=ident, body=peticion).execute()
    else:
        b = s.users().drafts().create(userId="me", body=peticion).execute()
    return {**_resultado(b, n), "para": ", ".join(todos), "asunto": asunto}


def borrador_existente(ident: str) -> dict | None:
    """¿Sigue vivo ese borrador? Devuelve su enlace, o None si ya no esta.

    Existe porque el panel anotaba el borrador en `candidaturas.notas` pero
    nadie leia la nota antes de crear otro: dos clicks = dos borradores al
    mismo destinatario, que es justo la clase de ruido que hace desconfiar
    de la herramienta. Si se borro a mano, se crea uno nuevo.
    """
    from googleapiclient.errors import HttpError
    try:
        b = _servicio().users().drafts().get(
            userId="me", id=ident, format="minimal").execute()
    except HttpError as ex:
        if ex.resp.status in (403, 404):
            return None
        raise
    return {"id": b["id"], "mensaje_id": b["message"]["id"],
            "enlace": f"https://mail.google.com/mail/u/0/#drafts?compose={b['message']['id']}"}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--probar", action="store_true")
    p.add_argument("--ampliar", action="store_true",
                   help="reautoriza añadiendo el permiso de lectura")
    p.add_argument("--buscar", help="busca en el correo (sintaxis de Gmail)")
    p.add_argument("--permitir-envio", action="store_true",
                   help="pide a Google el permiso de ENVIO (rehace el flujo)")
    p.add_argument("--activar-envio", action="store_true",
                   help="enciende el interruptor de envio automatico")
    p.add_argument("--apagar-envio", action="store_true")
    args = p.parse_args()

    if args.permitir_envio:
        # Igual que `--ampliar`: Google solo concede el permiso nuevo si el
        # flujo se rehace entero, asi que el token viejo se retira.
        TOKEN.unlink(missing_ok=True)
        _servicio(ALCANCE_ENVIO)
        print("listo: el token ya incluye ENVIO.")
        print("Falta el interruptor: python correo_gmail.py --activar-envio")
    elif args.activar_envio:
        import datetime as _dt
        INTERRUPTOR.write_text(json.dumps(
            {"activo": True, "desde": _dt.datetime.now().isoformat(timespec="seconds"),
             "quien": "linea de comandos"},
            ensure_ascii=False, indent=2), encoding="utf-8")
        ok, porque = puede_enviar()
        print("interruptor encendido.", "El sistema YA puede enviar." if ok else porque)
    elif args.apagar_envio:
        INTERRUPTOR.unlink(missing_ok=True)
        print("interruptor apagado: el sistema vuelve a dejar solo borradores.")
    elif args.ampliar:
        # El token viejo se retira a proposito: Google solo concede el permiso
        # nuevo si el flujo se rehace entero.
        TOKEN.unlink(missing_ok=True)
        _servicio()
        print("listo: el sistema ya puede LEER tu correo. Seguir sin poder enviarlo.")
    elif args.buscar:
        if not puede_leer():
            raise SystemExit("falta el permiso de lectura: python correo_gmail.py --ampliar")
        for m in mensajes(args.buscar):
            print(f"- {m['fecha'][:22]} | {m['de'][:40]} | {m['asunto'][:60]}")
            print(f"    {m['resumen'][:150]}")
    elif args.probar:
        r = crear_borrador(
            CANDIDATO["correo"],
            "Prueba de ULTRA CHAMBA",
            "Este es un borrador de prueba creado por el sistema.\n"
            "Si lo ves en tu Gmail, la conexion funciona.\n",
            adjuntar_cv=False)
        print("borrador creado:", r["enlace"])
    else:
        print("autorizado:", disponible())
