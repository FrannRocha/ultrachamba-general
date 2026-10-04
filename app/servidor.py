"""
Servidor local del panel: sirve la interfaz y consulta la base de datos.

Qué cambia respecto a antes. El panel se generaba incrustando TODAS las
vacantes dentro del HTML: un archivo de 1,2 MB que había que reescribir entero
en cada corrida. Eso tenía tres problemas:

  1. Cambiar un color obligaba a regenerar los datos, y viceversa.
  2. El progreso ("ya apliqué a esta") vivía en el navegador, así que se perdía
     al cambiar de equipo o al limpiar el historial.
  3. Los datos del panel podían quedar desfasados respecto a la base.

Ahora la interfaz es un archivo estático de unos 25 KB que no cambia nunca, y
los datos se piden a este servidor, que los lee de SQLite. Marcar una vacante
como aplicada se guarda EN LA BASE, no en el navegador.

Uso:
    python app/servidor.py            # abre en http://127.0.0.1:8800
"""
from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import areas
from almacen import SQL_VIVAS_PANEL, conexion

RAIZ = Path(__file__).resolve().parent
PANEL = RAIZ.parent / "panel.html"
MOVIL = RAIZ.parent / "movil.html"
PUERTO = 8800

# EL TOKEN, y por que solo aparece cuando el servidor sale de esta maquina.
#
# Escuchando en 127.0.0.1 no hace falta: solo llega quien ya esta dentro del
# ordenador. Pero para aprobar desde el telefono el servidor tiene que
# escuchar en la red, y ahi cualquiera que comparta la wifi --una cafeteria,
# la universidad-- podria pedir `/api/aprobar` y mandar correos en nombre de
# quien usa el sistema. Por eso salir a la red obliga a llevar token: sin el, el servidor
# no arranca abierto. No es criptografia seria; es la cerradura minima para
# que una puerta que da a la red no quede abierta del todo.
TOKEN_ACCESO = ""      # lo pone el arranque cuando se usa --host

# Lo unico que se sirve sin token aunque el servidor este expuesto: la pagina
# en si, porque el navegador la pide antes de tener nada que enviar. Los datos
# y las acciones piden token SIEMPRE.
SIN_TOKEN = ("/movil", "/movil.html")

# La zona base (define "sin mudanza") y las areas activas vienen de `areas.py`.


def _fila_a_dict(f) -> dict:
    d = dict(f)
    d["motivos"] = json.loads(d.get("motivos") or "[]")
    d["motivos_fantasma"] = json.loads(d.get("motivos_fantasma") or "[]")
    d["habilidades"] = json.loads(d.get("habilidades") or "[]")
    d.pop("extra", None)
    d.pop("descripcion", None)  # se pide aparte, solo al abrir el detalle
    d["elegible_mx"] = bool(d.get("elegible_mx"))
    d["requiere_mudanza"] = bool(d.get("requiere_mudanza"))
    d["aplicada"] = bool(d.get("aplicada"))
    # El panel lo usa para la etiqueta "sin mudanza": asi no repite en
    # JavaScript el vocabulario de la zona base.
    d["en_zona"] = areas.en_zona(d.get("ubicacion") or "")
    d["verificacion"] = {
        "estado": d.pop("ver_estado", None),
        "metodo": d.pop("ver_metodo", None),
        "detalle": d.pop("ver_detalle", None),
        "fecha": d.pop("ver_fecha", None),
        "http": d.pop("ver_http", None),
    }
    return d


def consultar(params: dict) -> dict:
    """Filtra en SQL, no en el navegador: así el panel no carga 2.000 filas."""
    # Se filtra tambien aqui, no solo al recolectar: la base ya contiene
    # vacantes de nivel senior de corridas anteriores y el panel no debe
    # mostrarlas. Siguen guardadas para poder auditarlas.
    condiciones = ["(ver_estado IS NULL OR ver_estado != 'cerrada')",
                   "(nivel IS NULL OR nivel != 'excluido')",
                   # Sin esto seguian saliendo vacantes de rubros que no estan
                   # entre las areas activas y que el clasificador ya habia
                   # descartado.
                   "(area IS NULL OR area != 'fuera')"]
    args: list = []

    def uno(clave: str) -> str | None:
        v = params.get(clave, [None])[0]
        return v or None

    if (v := uno("veredicto")):
        condiciones.append(f"veredicto IN ({','.join('?' * len(v.split(',')))})")
        args += v.split(",")
    if (v := uno("area")):
        condiciones.append(f"area IN ({','.join('?' * len(v.split(',')))})")
        args += v.split(",")
    if (v := uno("nivel")):
        condiciones.append(f"nivel IN ({','.join('?' * len(v.split(',')))})")
        args += v.split(",")
    if (v := uno("modalidad")):
        condiciones.append(f"modalidad IN ({','.join('?' * len(v.split(',')))})")
        args += v.split(",")
    if (v := uno("verificacion")):
        condiciones.append(f"ver_estado IN ({','.join('?' * len(v.split(',')))})")
        args += v.split(",")
    if uno("monterrey") == "1":
        # El parametro conserva su nombre de origen: significa "solo mi zona".
        sql_zona, args_zona = areas.sql_en_zona("ubicacion")
        condiciones.append(sql_zona)
        args += args_zona
    if uno("mudanza") == "0":
        condiciones.append("requiere_mudanza = 0")
    if uno("sin_experiencia") == "1":
        condiciones.append("(anios_exigidos IS NULL OR anios_exigidos < 3)")
    if uno("ocultar_aplicadas") == "1":
        condiciones.append("aplicada = 0")
    if uno("sin_fantasmas") == "1":
        # Riesgo alto = el anuncio lleva tanto tiempo abierto (o se ha
        # republicado tanto) que lo mas probable es que no contrate.
        condiciones.append("(riesgo_fantasma IS NULL OR riesgo_fantasma < 55)")
    if uno("nuevas") == "1":
        # "Nueva" = se vio en la ultima corrida y NO en la anterior. Es mas
        # fiable que mirar la fecha: si una corrida falla o se repite el mismo
        # dia, la fecha miente y el registro de avistamientos no.
        ult, prev = _dos_ultimas_corridas()
        if ult:
            condiciones.append(
                "id IN (SELECT vacante_id FROM avistamientos WHERE corrida_id=?)")
            args.append(ult)
            if prev:
                condiciones.append(
                    "id NOT IN (SELECT vacante_id FROM avistamientos WHERE corrida_id=?)")
                args.append(prev)
    if (q := uno("q")):
        condiciones.append("(LOWER(titulo) LIKE ? OR LOWER(empresa) LIKE ? "
                           "OR LOWER(ubicacion) LIKE ? OR LOWER(habilidades) LIKE ?)")
        args += [f"%{q.lower()}%"] * 4
    try:
        minimo = float(uno("min") or 40)
    except ValueError:
        minimo = 40.0
    condiciones.append("score >= ?")
    args.append(minimo)

    orden = {"score": "score DESC", "fecha": "publicado DESC, score DESC",
             "empresa": "empresa ASC"}.get(uno("orden") or "score", "score DESC")
    limite = min(int(uno("limite") or 300), 2000)

    donde = " AND ".join(condiciones)
    with conexion() as con:
        total = con.execute(f"SELECT COUNT(*) n FROM vacantes WHERE {donde}", args).fetchone()["n"]
        filas = con.execute(
            f"SELECT * FROM vacantes WHERE {donde} ORDER BY {orden} LIMIT {limite}", args
        ).fetchall()
    return {"total": total, "mostradas": len(filas),
            "vacantes": [_fila_a_dict(f) for f in filas]}


def _dos_ultimas_corridas() -> tuple[int | None, int | None]:
    """(ultima, anterior). Solo cuentan las corridas que guardaron algo."""
    with conexion() as con:
        filas = con.execute(
            "SELECT id FROM corridas WHERE guardadas > 0 ORDER BY id DESC LIMIT 2"
        ).fetchall()
    ids = [f["id"] for f in filas]
    return (ids[0] if ids else None, ids[1] if len(ids) > 1 else None)


def novedades() -> dict:
    """Que aparecio y que desaparecio entre las dos ultimas corridas.

    Es la pregunta que de verdad importa cuando revisas cada semana: no
    "que hay", sino "que hay que no estuviera ya".
    """
    ult, prev = _dos_ultimas_corridas()
    if not ult:
        return {"nuevas": [], "desaparecidas": [], "comparando": None}
    vivas = SQL_VIVAS_PANEL
    with conexion() as con:
        if prev:
            nuevas = con.execute(
                f"""SELECT * FROM vacantes WHERE {vivas}
                    AND id IN (SELECT vacante_id FROM avistamientos WHERE corrida_id=?)
                    AND id NOT IN (SELECT vacante_id FROM avistamientos WHERE corrida_id=?)
                    ORDER BY score DESC LIMIT 100""", (ult, prev)).fetchall()
            idas = con.execute(
                f"""SELECT * FROM vacantes WHERE {vivas}
                    AND id IN (SELECT vacante_id FROM avistamientos WHERE corrida_id=?)
                    AND id NOT IN (SELECT vacante_id FROM avistamientos WHERE corrida_id=?)
                    ORDER BY score DESC LIMIT 100""", (prev, ult)).fetchall()
        else:
            nuevas, idas = [], []
    return {
        "comparando": {"ultima": ult, "anterior": prev},
        "nuevas": [_fila_a_dict(f) for f in nuevas],
        "desaparecidas": [_fila_a_dict(f) for f in idas],
    }


def facetas() -> dict:
    """Conteos por cada filtro, para poder mostrarlos junto a su etiqueta."""
    vivas = SQL_VIVAS_PANEL
    salida: dict = {}
    with conexion() as con:
        for campo in ("veredicto", "area", "nivel", "modalidad"):
            salida[campo] = {
                r[campo]: r["n"] for r in con.execute(
                    f"SELECT {campo}, COUNT(*) n FROM vacantes WHERE {vivas} "
                    f"GROUP BY {campo}") if r[campo]
            }
        salida["verificacion"] = {
            r["ver_estado"]: r["n"] for r in con.execute(
                f"SELECT ver_estado, COUNT(*) n FROM vacantes WHERE {vivas} "
                f"GROUP BY ver_estado") if r["ver_estado"]
        }
        sql_zona, args_zona = areas.sql_en_zona("ubicacion")
        # Zona, areas activas y etiquetas de area: el panel las pinta sin
        # repetir en JavaScript lo que ya dice `areas.py`.
        salida["contexto"] = areas.contexto_panel()
        salida["resumen"] = {
            "total": con.execute(f"SELECT COUNT(*) n FROM vacantes WHERE {vivas}").fetchone()["n"],
            # El total incluye las que ya se descartaron a mano. Se desglosa
            # para que la cifra grande no se lea como "esto es lo que tienes
            # por delante": 29 de ellas ya tienen motivo escrito.
            "descartadas": con.execute(
                f"SELECT COUNT(*) n FROM vacantes WHERE {vivas} "
                "AND descartada_motivo IS NOT NULL AND descartada_motivo <> ''"
            ).fetchone()["n"],
            "en_juego": con.execute(
                f"SELECT COUNT(*) n FROM vacantes WHERE {vivas} "
                "AND (descartada_motivo IS NULL OR descartada_motivo = '')"
            ).fetchone()["n"],
            # "monterrey" es el nombre de origen de la clave: cuenta la zona base.
            "monterrey": con.execute(
                f"SELECT COUNT(*) n FROM vacantes WHERE {vivas} AND {sql_zona}",
                args_zona).fetchone()["n"],
            "mudanza": con.execute(
                f"SELECT COUNT(*) n FROM vacantes WHERE {vivas} AND requiere_mudanza=1"
            ).fetchone()["n"],
            "aplicadas": con.execute("SELECT COUNT(*) n FROM vacantes WHERE aplicada=1").fetchone()["n"],
            "fantasmas": con.execute(
                f"SELECT COUNT(*) n FROM vacantes WHERE {vivas} AND riesgo_fantasma >= 55"
            ).fetchone()["n"],
            "nuevas": (con.execute(
                f"SELECT COUNT(*) n FROM vacantes WHERE {vivas} "
                "AND id IN (SELECT vacante_id FROM avistamientos WHERE corrida_id=?) "
                "AND id NOT IN (SELECT vacante_id FROM avistamientos WHERE corrida_id=?)",
                _dos_ultimas_corridas()).fetchone()["n"]
                if all(_dos_ultimas_corridas()) else 0),
            "historicas": con.execute("SELECT COUNT(*) n FROM vacantes").fetchone()["n"],
            "corridas": con.execute("SELECT COUNT(*) n FROM corridas").fetchone()["n"],
            "ultima": (con.execute(
                "SELECT MAX(fin) f FROM corridas").fetchone()["f"] or "")[:16].replace("T", " "),
        }
    return salida


def detalle(vid: str) -> dict:
    with conexion() as con:
        f = con.execute("SELECT * FROM vacantes WHERE id=?", (vid,)).fetchone()
    if not f:
        return {}
    d = dict(f)
    return {"id": d["id"], "descripcion": (d.get("descripcion") or "")[:6000],
            "motivos": json.loads(d.get("motivos") or "[]"),
            "evidencia_experiencia": d.get("evidencia_experiencia"),
            "anios_exigidos": d.get("anios_exigidos"),
            "notas": d.get("notas") or ""}


def marcar(vid: str, aplicada: bool, notas: str = "") -> dict:
    from nucleo import ahora_iso
    with conexion() as con:
        con.execute(
            "UPDATE vacantes SET aplicada=?, fecha_aplicada=?, notas=? WHERE id=?",
            (int(aplicada), ahora_iso() if aplicada else None, notas, vid))
        n = con.execute("SELECT COUNT(*) n FROM vacantes WHERE aplicada=1").fetchone()["n"]
    return {"ok": True, "id": vid, "aplicada": aplicada, "total_aplicadas": n}


# Repasar Gmail cuesta una llamada de red por hilo, y el panel se recarga
# cada vez que se cambia de pestana. Sin este freno, abrir el plan
# tres veces seguidas serian tres barridos completos de la bandeja.
_CACHE_SEG: dict = {"cuando": 0.0, "datos": None}
_FRESCURA = 300     # segundos


def _seguimiento(refrescar: bool = False) -> dict:
    """El estado de las candidaturas ya enviadas, mirado en el correo."""
    import time

    import correo_gmail
    if not correo_gmail.puede_leer():
        return {"autorizado": False, "por_estado": {}, "pendientes": [],
                "hay_que_insistir": []}

    import seguimiento as seg
    reciente = (time.time() - _CACHE_SEG["cuando"]) < _FRESCURA
    if _CACHE_SEG["datos"] is not None and reciente and not refrescar:
        return {**_CACHE_SEG["datos"], "cacheado": True}

    try:
        seg.emparejar()
        seg.revisar()
        datos = {"autorizado": True, **seg.resumen()}
    except Exception as ex:
        # Que Gmail falle no puede tumbar el plan del dia: lo demas de la
        # pestana no depende del correo.
        return {"autorizado": True, "error": str(ex)[:200],
                "por_estado": {}, "pendientes": [], "hay_que_insistir": []}

    _CACHE_SEG.update(cuando=time.time(), datos=datos)
    return {**datos, "cacheado": False}


def _resumen_movil() -> dict:
    """Todo lo que la pantalla del movil necesita, en UNA peticion.

    Una y no cinco porque en el telefono cada viaje de red es medio segundo
    mas de espera; y porque si una de las cinco fallara, la pantalla quedaria
    a medias sin decir cual falto.

    No toca Gmail: lee lo que `tramites.py` y `seguimiento.py` dejaron
    escrito. Abrir esta pagina no puede tardar lo que tarde Google.
    """
    import aprobaciones
    import arranque

    d = arranque.estado()
    cif = d["cifras"]
    return {
        "enviadas": cif["candidaturas_enviadas"],
        "en_juego": cif["en_juego"],
        "pendientes": aprobaciones.pendientes(),
        "aprobadas_sin_ejecutar": aprobaciones.aprobadas_sin_ejecutar(),
        "novedades": d["tramites"].get("novedades", []),
        "cierres": d["cierres"],
        "procesos": d["procesos_vivos"],
        "avisos": d["avisos"],
        "agente": _estado_agente(),
    }


def _estado_agente() -> dict:
    """¿Esta vivo el agente de casa? Lo dice su latido, no una suposicion.

    Sin esto, aprobar desde el movil seria un acto de fe: la tarjeta diria
    "aprobada" y el correo no saldria nunca porque el proceso que lo manda
    lleva dos dias apagado. Es el fallo silencioso de siempre; aqui se ve en
    la pantalla.
    """
    import time as _t
    f = RAIZ / "datos" / "agente_local.json"
    if not f.exists():
        return {"vivo": False, "nunca": True}
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {"vivo": False, "ilegible": True}
    hace = (_t.time() - f.stat().st_mtime) / 60
    # Late cada 3 minutos; se le dan 15 de margen antes de darlo por caido,
    # para que un portatil que durmio un rato no dispare la alarma.
    return {"vivo": hace < 15, "hace_min": int(hace), "ultimo": d.get("cuando")}


class Manejador(BaseHTTPRequestHandler):
    # Los unicos origenes externos que pueden hablar con el panel. Chrome
    # bloquea toda peticion de una web HTTPS hacia 127.0.0.1 (proteccion de
    # red privada) salvo que el servidor local lo autorice, y hay que
    # autorizarlo por origen concreto: con "*" cualquier pagina que se
    # visitara podria escribir aqui.
    #
    # Se descubrio porque desde la pestana de Indeed el `fetch` fallaba con
    # "Failed to fetch" y `sendBeacon` devolvia true sin entregar nada: el
    # navegador lo aceptaba en cola y luego lo descartaba en silencio.
    ORIGENES = ("https://mx.indeed.com", "https://www.occ.com.mx",
                "https://www.linkedin.com")

    # Rutas que de verdad necesitan hablar con una pestana de otra web. Es
    # SOLO el buzon de fichas: el bookmarklet lee el HTML de OCC/Indeed desde
    # su propio dominio y lo escribe aqui.
    #
    # `/api/js/detalle` esta aqui desde el 28-ago-2026: la pestana de OCC
    # tiene que poder DESCARGAR el lector de fichas, no solo escribir el
    # resultado. Se anadio a conciencia y con el limite claro: esa ruta
    # devuelve codigo con ids publicos de ofertas, no datos personales, y no
    # ejecuta ninguna accion. Las rutas que SI actuan o exponen sus datos
    # (`/api/aprobar`, `/api/rechazar`, `/api/movil`) siguen fuera, que es
    # justo el agujero que se cerro la noche anterior.
    RUTAS_CORS = ("/api/detalle", "/api/js/detalle")

    def _cors(self, ruta: str = "") -> None:
        """Permisos de origen cruzado, y solo para la ruta que los necesita.

        FALLO ENCONTRADO POR EL `jefe` EL 28-ago-2026, reproducido: esto se
        aplicaba a TODAS las respuestas y `do_OPTIONS` contestaba 204 a
        cualquier ruta. Con el panel abierto en local (donde no hay token) y
        una pestana de LinkedIn delante, un script de esa pagina podia leer
        `/api/movil` --ids, cuerpos de los correos, direcciones de contacto--
        y llamar a `/api/aprobar` y `/api/rechazar`. Comprobado con peticiones
        reales: 204 al OPTIONS y 200 al POST.
        La lista de origenes no era el problema y no se toca: el problema era
        aplicarla a rutas que nunca la pidieron.
        """
        if ruta not in self.RUTAS_CORS:
            return
        origen = self.headers.get("Origin", "")
        if origen in self.ORIGENES:
            self.send_header("Access-Control-Allow-Origin", origen)
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            # La cabecera que levanta el bloqueo de red privada.
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Access-Control-Max-Age", "600")

    def do_OPTIONS(self):  # noqa: N802
        """Peticion previa de CORS. Solo tiene sentido para /api/detalle."""
        ruta = urlparse(self.path).path
        if ruta not in self.RUTAS_CORS:
            # Sin cabeceras de permiso, el navegador corta la peticion real
            # antes de mandarla. Es el "no" que faltaba.
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(204)
        self._cors(ruta)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _responder(self, datos, codigo=200, tipo="application/json"):
        cuerpo = (json.dumps(datos, ensure_ascii=False).encode("utf-8")
                  if tipo == "application/json" else datos)
        self.send_response(codigo)
        self.send_header("Content-Type", f"{tipo}; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self._cors(urlparse(self.path).path)
        self.end_headers()
        self.wfile.write(cuerpo)

    def _autorizado(self, u, params) -> bool:
        """¿Puede pasar esta peticion? Solo importa si hay token configurado.

        El token viaja por parametro y no solo por cabecera a proposito: la
        pagina movil se abre desde un enlace guardado, y un enlace no lleva
        cabeceras. Viaja por la red local o por Tailscale, que ya cifra.
        """
        if not TOKEN_ACCESO or u.path in SIN_TOKEN:
            return True
        dado = params.get("t", [""])[0] or self.headers.get("X-Token", "")
        return dado == TOKEN_ACCESO

    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        params = parse_qs(u.query)
        if not self._autorizado(u, params):
            return self._responder({"error": "token invalido"}, 403)
        try:
            if u.path in ("/movil", "/movil.html"):
                if not MOVIL.exists():
                    return self._responder(b"Falta movil.html", 404, "text/plain")
                return self._responder(MOVIL.read_bytes(), 200, "text/html")
            if u.path == "/api/movil":
                return self._responder(_resumen_movil())
            if u.path == "/api/js/detalle":
                # El lector de fichas de OCC, servido con los ids YA dentro.
                #
                # Por que un endpoint y no pegar el JS cada vez: son ~5 KB por
                # tanda y hacen falta ocho o diez tandas para vaciar la cola.
                # Asi cada tanda es una linea en la consola del navegador:
                #
                #     eval(await (await fetch(
                #       'http://127.0.0.1:8800/api/js/detalle')).text())
                #
                # Que es, ademas, lo que se puede guardar como marcador y
                # disparar desde una pestana de OCC.
                #
                # Devuelve texto plano y NO lleva cabeceras de origen cruzado
                # (solo `/api/detalle` las tiene, ver `_cors`), asi que solo lo
                # lee quien ya esta en esta maquina o en una pestana de las
                # tres bolsas autorizadas.
                import verificador_chrome as vc
                n = int(params.get("n", ["40"])[0])
                ids = vc.ids_para_detalle(max(1, min(n, 200)))
                if not ids:
                    return self._responder(
                        b"console.log('no queda ninguna ficha pendiente')",
                        200, "text/javascript")
                # Se envuelve en una funcion async, y no es cosmetico: el
                # lector usa `await` en el nivel superior, que la consola de
                # Chrome acepta pero `eval()` rechaza con
                # "await is only valid in async functions". Envuelto sirve
                # para las dos formas de dispararlo -- pegado a mano o por
                # `eval` desde la extension -- y deja la promesa en
                # `window.__uc_fichas`, por si se quiere esperar a que acabe.
                envuelto = ("window.__uc_fichas = (async () => {" + chr(10)
                            + vc.plantilla_detalle(ids) + chr(10) + "})();")
                return self._responder(envuelto.encode("utf-8"),
                                       200, "text/javascript")
            if u.path in ("/", "/index.html", "/panel.html"):
                if not PANEL.exists():
                    return self._responder(b"Falta panel.html", 404, "text/plain")
                return self._responder(PANEL.read_bytes(), 200, "text/html")
            # React y htm se sirven desde disco, no desde un CDN: así el panel
            # sigue funcionando sin conexión.
            if u.path.startswith("/vendor/"):
                f = RAIZ / "vendor" / Path(u.path).name
                if not f.exists():
                    return self._responder({"error": "no encontrado"}, 404)
                tipo = "text/javascript" if f.suffix == ".js" else "text/plain"
                return self._responder(f.read_bytes(), 200, tipo)
            # Imágenes del panel (el fondo).
            if u.path.startswith("/assets/"):
                f = RAIZ.parent / "assets" / Path(u.path).name
                if not f.exists():
                    return self._responder({"error": "no encontrado"}, 404)
                tipos = {".png": "image/png", ".jpg": "image/jpeg",
                         ".jpeg": "image/jpeg", ".webp": "image/webp",
                         ".svg": "image/svg+xml"}
                return self._responder(
                    f.read_bytes(), 200, tipos.get(f.suffix.lower(), "application/octet-stream"))
            if u.path == "/api/vacantes":
                return self._responder(consultar(params))
            if u.path == "/api/facetas":
                return self._responder(facetas())
            if u.path == "/api/novedades":
                return self._responder(novedades())
            if u.path == "/api/gmail":
                import correo_gmail
                return self._responder({"autorizado": correo_gmail.disponible()})
            if u.path == "/api/seguimiento":
                return self._responder(_seguimiento(refrescar="refrescar" in params))
            if u.path == "/api/cola":
                # El plan del dia: tres candidaturas con el correo ya escrito.
                # Se genera aqui y no en un archivo porque el correo depende
                # del estado de la base AHORA (que sigue viva, a quien no se
                # le escribio ya) y un borrador guardado envejece mal.
                import cola as mod_cola
                import correos_frios
                import generador_correos
                elementos = mod_cola.elegir()
                for e in elementos:
                    try:
                        if e["via"] == "portal":
                            # El contacto, si lo hay, entra en el saludo: el
                            # correo tiene que salir listo para enviar.
                            e["correo"] = generador_correos.generar(
                                e, contacto=e.get("contacto"))
                        elif e.get("contacto"):
                            with conexion() as con:
                                emp = con.execute(
                                    "SELECT * FROM empresas WHERE id=?",
                                    (e["empresa_id"],)).fetchone()
                            e["correo"] = correos_frios.generar_frio(
                                dict(emp), e["contacto"])
                        ident = mod_cola.registrar(
                            e, (e.get("correo") or {}).get("asunto", ""),
                            (e.get("correo") or {}).get("cuerpo", ""))
                        e["candidatura_id"] = ident
                    except Exception as ex:
                        e["correo"] = None
                        e["error_correo"] = f"{type(ex).__name__}: {ex}"
                    e.pop("descripcion", None)   # la tarjeta no la necesita
                return self._responder({
                    "cola": elementos, "situacion": mod_cola.situacion(),
                    # Por que la cola trae esta mezcla y no otra. Ensenarlo
                    # importa: si se ve que hoy hay dos correos porque
                    # el correo contesta cinco veces mas, entiende la cola en
                    # vez de sufrirla.
                    "rendimiento": mod_cola.rendimiento(),
                    "reparto": mod_cola._reparto(3)})
            if u.path == "/api/empresas":
                import empresas as mod_emp
                objetivos = mod_emp.objetivos(
                    int(params.get("limite", ["25"])[0]))
                with conexion() as con:
                    for e in objetivos:
                        e["contactos"] = [dict(r) for r in con.execute(
                            "SELECT nombre, puesto, correo, correo_origen, "
                            "confianza, fuente FROM contactos WHERE empresa_id=?",
                            (e["id"],))]
                return self._responder({"empresas": objetivos})
            if u.path == "/api/cursos":
                # Formacion gratuita. Se sirve desde la misma base que las
                # vacantes a proposito: los cursos se puntuan contra lo que
                # piden los anuncios reales, no contra una lista de modas.
                import cursos as mod_cursos
                return self._responder({
                    "cursos": mod_cursos.consultar(
                        area=params.get("area", [None])[0],
                        solo_gratis=params.get("solo_gratis", ["0"])[0] == "1",
                        solo_abiertos=params.get("solo_abiertos", ["0"])[0] == "1"),
                    "resumen": mod_cursos.resumen(),
                })
            if u.path == "/api/formacion":
                # El carril de formacion: lo mismo que `/api/cursos` pero
                # contestando la pregunta que decide, que no es "¿que hay?"
                # sino "¿a que puedo inscribirme, y que se cierra antes".
                #
                # `cursos.consultar` sigue existiendo y sirve al catalogo; esta
                # ruta anade lo que aquel no sabe: elegibilidad, el embudo de
                # inscripciones y lo que ya esta en marcha por correo. Las
                # cifras salen de `formacion.cifras()` y de ningun otro sitio,
                # por la cicatriz 1 -- el dashboard llego a publicar 2.228
                # vacantes vivas contra las 3.700 de la base porque cada
                # generador rehacia su propio WHERE.
                import formacion
                return self._responder({
                    "cifras": formacion.cifras(),
                    "cola": formacion.cola_de_hoy(
                        int(params.get("n", ["5"])[0])),
                    "pendientes": formacion.pendientes(),
                    "en_marcha": formacion.en_marcha(),
                })
            if m := re.match(r"^/api/vacante/([\w]+)$", u.path):
                return self._responder(detalle(m.group(1)))
            return self._responder({"error": "no encontrado"}, 404)
        except Exception as e:
            return self._responder({"error": f"{type(e).__name__}: {e}"}, 500)

    def do_POST(self):  # noqa: N802
        u = urlparse(self.path)
        params = parse_qs(u.query)
        if not self._autorizado(u, params):
            return self._responder({"error": "token invalido"}, 403)
        largo = int(self.headers.get("Content-Length", 0))
        try:
            cuerpo = json.loads(self.rfile.read(largo) or b"{}")
        except Exception:
            cuerpo = {}

        # Los tres gestos del modo movil. Aprobar NO envia: deja la
        # candidatura en 'aprobada' y el agente de casa la saca. Asi el toque
        # en el telefono responde al instante aunque Gmail tarde o el
        # ordenador este apagado. Ver `aprobaciones.py`.
        if u.path == "/api/aprobar":
            import aprobaciones
            return self._responder(
                aprobaciones.aprobar(cuerpo.get("id", ""), cuerpo.get("nota", "")))
        if u.path == "/api/rechazar":
            import aprobaciones
            return self._responder(
                aprobaciones.rechazar(cuerpo.get("id", ""), cuerpo.get("motivo", "")))
        if u.path == "/api/tramite-leido":
            import tramites
            return self._responder(
                {"ok": bool(tramites.marcar_leido(cuerpo.get("id", "")))})
        if u.path == "/api/detalle":
            # Buzon para lo que Chrome lee de las fichas de OCC.
            #
            # Por que existe. El HTML de la ficha solo se puede pedir desde una
            # pestana del propio dominio (OCC responde 403 a Python). Hasta
            # ahora el resultado volvia como texto en la consola y habia que
            # copiarlo a mano, lo que limitaba cada tanda a lo que cupiera en
            # pantalla: 12 vacantes de 332. Con este endpoint el navegador
            # escribe directo y las tandas dejan de tener tope.
            #
            # Alcance deliberadamente minimo: solo toca cinco columnas de
            # `vacantes` y solo para ids que ya estan en la base. No crea
            # filas, no borra, no acepta SQL. Y el servidor escucha unicamente
            # en 127.0.0.1, asi que el buzon no sale de esta maquina.
            import verificador_chrome as vc
            filas = cuerpo.get("filas") or []
            datos = {}
            for f in filas:
                if isinstance(f, str):          # "id|estado|edu|contr|hor|esp|ciudad"
                    p = (f.split("|") + [""] * 7)[:7]
                    f = {"id": p[0], "estado": p[1], "educacion": p[2],
                         "contratacion": p[3], "horario": p[4], "espacio": p[5],
                         "ubicacion": p[6]}
                if f.get("id"):
                    datos[str(f["id"])] = f
            escritas = vc.guardar_detalle(datos) if datos else 0
            return self._responder({"recibidas": len(datos), "escritas": escritas})

        if u.path == "/api/borrador":
            # Deja el correo escrito en el Gmail configurado. El sistema NO
            # envia: crea el borrador y la persona pulsa Enviar. Es la diferencia
            # entre una herramienta y algo de lo que hay que desconfiar.
            import correo_gmail
            import cola as mod_cola
            ident = cuerpo.get("id", "")
            with conexion() as con:
                c = con.execute(
                    "SELECT asunto, cuerpo, contacto_id, notas FROM candidaturas WHERE id=?",
                    (ident,)).fetchone()
                if not c:
                    return self._responder({"error": "candidatura no encontrada"}, 404)
                destino = ""
                if c["contacto_id"]:
                    ct = con.execute("SELECT correo FROM contactos WHERE id=?",
                                     (c["contacto_id"],)).fetchone()
                    destino = (ct["correo"] or "") if ct else ""
            try:
                # Si ya se pulso antes y el borrador sigue en Gmail, se
                # devuelve ese mismo. Dos clicks no pueden ser dos correos.
                previo = (c["notas"] or "")
                if previo.startswith("borrador en Gmail: "):
                    vivo = correo_gmail.actualizar_borrador(
                        previo.split(": ", 1)[1].strip(), destino,
                        c["asunto"], c["cuerpo"])
                    if vivo:
                        return self._responder({"ok": True, "destino": destino,
                                                "ya_existia": True, **vivo})
                r = correo_gmail.crear_borrador(destino, c["asunto"], c["cuerpo"])
                # Queda como enviada solo cuando el usuario lo confirme; aqui
                # solo se anota que ya existe el borrador, para no duplicarlo.
                with conexion() as con:
                    con.execute("UPDATE candidaturas SET notas=? WHERE id=?",
                                (f"borrador en Gmail: {r['id']}", ident))
                # Viaja el destino para que el panel no prometa "darle
                # Enviar" cuando el borrador salio sin destinatario (las
                # vacantes de portal no tienen contacto: es lo normal).
                return self._responder({"ok": True, "destino": destino, **r})
            except Exception as ex:
                return self._responder(
                    {"error": f"{type(ex).__name__}: {ex}",
                     "necesita_autorizar": not correo_gmail.disponible()}, 500)
        if u.path == "/api/candidatura":
            # Marca el resultado de un elemento de la cola. "enviada" es el
            # unico estado que mueve la aguja de verdad; "descartada" tambien
            # se registra para que mañana no vuelva a proponerse lo mismo.
            import cola as mod_cola
            ident = cuerpo.get("id", "")
            if cuerpo.get("estado") == "enviada":
                return self._responder({"ok": mod_cola.marcar_enviada(ident)})
            if cuerpo.get("estado") == "descartada":
                # Rechazar tiene que ENSEÑAR, no solo borrar la tarjeta.
                #
                # Antes esto marcaba la candidatura y nada mas: la vacante
                # seguia elegible y podia volver a proponerse manana con otro
                # identificador. Ahora el motivo baja tambien a la vacante,
                # que es lo que leen `elegir()` y `ranking()` para no
                # repetirla. Cada rechazo afina el filtro un poco.
                from nucleo import ahora_iso
                motivo = (cuerpo.get("motivo") or "descartada a mano en el panel")[:200]
                with conexion() as con:
                    n = con.execute(
                        "UPDATE candidaturas SET estado='descartada', "
                        "notas=COALESCE(notas,'') || ' | rechazada: ' || ?, "
                        "actualizada=? WHERE id=?",
                        (motivo, ahora_iso(), ident)).rowcount
                    fila = con.execute(
                        "SELECT vacante_id FROM candidaturas WHERE id=?",
                        (ident,)).fetchone()
                    if fila and fila["vacante_id"]:
                        con.execute(
                            "UPDATE vacantes SET descartada_motivo=?, "
                            "descartada_fecha=? WHERE id=?",
                            (motivo, ahora_iso(), fila["vacante_id"]))
                return self._responder({"ok": bool(n), "motivo": motivo})
            return self._responder({"error": "estado no soportado"}, 400)
        if u.path == "/api/aplicar":
            return self._responder(
                marcar(cuerpo.get("id", ""), bool(cuerpo.get("aplicada")),
                       cuerpo.get("notas", "")))
        return self._responder({"error": "no encontrado"}, 404)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    import argparse
    import secrets

    ap = argparse.ArgumentParser(description="Panel de ULTRA CHAMBA")
    ap.add_argument("--host", default="127.0.0.1",
                    help="0.0.0.0 para poder entrar desde el telefono")
    ap.add_argument("--puerto", type=int, default=PUERTO)
    ap.add_argument("--token", default="",
                    help="clave de acceso; se genera una si no se da")
    args = ap.parse_args()

    if args.host not in ("127.0.0.1", "localhost"):
        # Salir a la red sin cerradura no es una opcion que se ofrezca: si no
        # se da token, se genera y se imprime. Nunca se arranca abierto.
        TOKEN_ACCESO = args.token or secrets.token_urlsafe(12)
        print(f"Panel EN LA RED: http://{args.host}:{args.puerto}/movil?t={TOKEN_ACCESO}")
        print("  Ese enlace es la llave: abrelo en el telefono y guardalo.")
        print("  Recomendado: Tailscale, para que solo lleguen tus dispositivos.")
    else:
        print(f"Panel en http://127.0.0.1:{args.puerto}")
        print(f"  Vista movil: http://127.0.0.1:{args.puerto}/movil")

    f = facetas()["resumen"]
    print(f"  zona base: {areas.zona()['etiqueta']} | areas: "
          f"{', '.join(areas.claves_activas())}")
    print(f"  {f['total']} vacantes vivas - {f['monterrey']} en {areas.zona()['corta']} - "
          f"{f['aplicadas']} aplicadas - {f['historicas']} en el historial")
    print("  Ctrl+C para detener")
    HTTPServer((args.host, args.puerto), Manejador).serve_forever()
