"""
Clasificación y scoring de vacantes contra el perfil de `perfil.py`.

Este módulo es lo que separa "una lista de vacantes" de "una herramienta":
decide si cada vacante es alcanzable (nivel), relevante (área), legalmente
viable (geografía) y qué tanto encaja con lo que la persona ya sabe hacer.

Cada decisión queda registrada en `motivos` para que quien use el sistema
pueda auditar POR QUÉ le recomendó algo. Nada de cajas negras.
"""
from __future__ import annotations

import re
from datetime import date, datetime

import areas
import dominio
import experiencia
import geo

from nucleo import normalizar, terminos_presentes, tiene_termino
from perfil import (
    AMM, AREA_CIBER, AREA_CIBER_DEBIL, AREA_IA, BLOQUEO_GEO, CONTEXTO_TECNICO,
    HABILIDADES, NEGATIVO_DOMINIO, NIVEL_EXCLUIR, NIVEL_JUNIOR,
    NIVEL_PRACTICAS, PAISES_CERRADOS, ROL_NO_TECNICO,
    UBIC_EXTRANJERA, UBIC_GENERICA, UBIC_MX_OTRA, UBIC_REMOTO_ABIERTO,
    UBIC_REMOTO_CERRADO,
)

RX_REMOTO_CERRADO = re.compile(UBIC_REMOTO_CERRADO)
RX_REMOTO_ABIERTO = re.compile(UBIC_REMOTO_ABIERTO)
RX_EXTRANJERA = re.compile(UBIC_EXTRANJERA)
RX_MX_OTRA = re.compile(UBIC_MX_OTRA)
RX_GENERICA = re.compile(UBIC_GENERICA)
RX_PAIS_CERRADO = re.compile(rf"\b({PAISES_CERRADOS})\b")


def _contiene(texto: str, terminos) -> list[str]:
    """Coincidencia por palabra completa, no por subcadena.

    Sin esto, 'intern' casa dentro de 'internal' y una auditoría senior
    se clasificaba como vacante de prácticas.
    """
    return terminos_presentes(texto, terminos)


# ------------------------------------------------------------------ nivel ----

def clasificar_nivel(titulo_n: str, desc_n: str) -> tuple[str, list[str]]:
    """practicas | junior | medio | excluido."""
    motivos = []
    practicas = _contiene(titulo_n, NIVEL_PRACTICAS)
    if practicas:
        return "practicas", [f"titulo indica practicas: {practicas[0]}"]

    excluir = _contiene(titulo_n, NIVEL_EXCLUIR)
    if excluir:
        return "excluido", [f"titulo de nivel alto: {excluir[0]}"]

    junior = _contiene(titulo_n, NIVEL_JUNIOR)
    if junior:
        return "junior", [f"titulo indica junior: {junior[0]}"]

    # El título no dice nada: buscar en la descripción.
    practicas_desc = _contiene(desc_n[:2500], NIVEL_PRACTICAS)
    if practicas_desc:
        motivos.append(f"descripcion menciona practicas: {practicas_desc[0]}")
        return "practicas", motivos

    # Años de experiencia exigidos.
    anios = re.findall(r"(\d+)\+?\s*(?:-\s*\d+\s*)?(?:years|anos|años)", desc_n)
    if anios:
        minimo = min(int(a) for a in anios if a.isdigit())
        if minimo >= 4:
            return "excluido", [f"pide {minimo}+ anos de experiencia"]
        if minimo <= 2:
            return "junior", [f"pide solo {minimo} anos de experiencia"]
        return "medio", [f"pide {minimo} anos de experiencia"]

    if re.search(r"no experience|sin experiencia|no prior experience", desc_n):
        return "junior", ["no exige experiencia previa"]

    return "medio", ["nivel no declarado"]


# ------------------------------------------------------------------- área ----

def _ciber_en(texto: str, contexto_extra: str = "") -> list[str]:
    """Términos de ciberseguridad presentes, resolviendo los ambiguos.

    'audit', 'risk' y 'compliance' existen igual en auditoría contable y en
    riesgo financiero. Solo cuentan como ciberseguridad si el texto también
    trae contexto técnico. Sin esta regla, 'Becario de Auditoria Fiscal'
    puntuaba 83/100 como si fuera una vacante de seguridad.
    """
    fuertes = _contiene(texto, AREA_CIBER)
    debiles = _contiene(texto, AREA_CIBER_DEBIL)
    if debiles and not fuertes:
        if _contiene(f"{texto} {contexto_extra}", CONTEXTO_TECNICO):
            return debiles
        return []
    return fuertes + debiles


def clasificar_area(titulo_n: str, desc_n: str) -> tuple[str, list[str]]:
    """ciberseguridad | ia | ciber-ia | ti-general | fuera."""
    motivos = []
    t_ciber = _ciber_en(titulo_n, desc_n[:600])
    t_ia = _contiene(titulo_n, AREA_IA)

    # Un dominio ajeno en el título (fiscal, actuarial, seguridad física...)
    # anula los términos ambiguos: 'Becario de Auditoria Fiscal' no es una
    # vacante de ciberseguridad por mucho que diga 'auditoria'.
    ajeno = _contiene(titulo_n, NEGATIVO_DOMINIO)
    if ajeno and not _contiene(titulo_n, AREA_CIBER):
        return "fuera", [f"el titulo es de otro dominio: '{ajeno[0]}'"]

    if t_ciber and t_ia:
        return "ciber-ia", [f"titulo cruza seguridad e IA: {t_ciber[0]} + {t_ia[0]}"]
    if t_ciber:
        return "ciberseguridad", [f"titulo de seguridad: {t_ciber[0]}"]
    if t_ia:
        return "ia", [f"titulo de IA: {t_ia[0]}"]

    d_ciber = _ciber_en(desc_n[:3000])
    d_ia = _contiene(desc_n[:3000], AREA_IA)
    if len(d_ciber) >= 3 and len(d_ia) >= 3:
        return "ciber-ia", ["descripcion mezcla seguridad e IA"]
    if len(d_ciber) >= 3:
        return "ciberseguridad", [f"descripcion de seguridad ({len(d_ciber)} senales)"]
    if len(d_ia) >= 3:
        return "ia", [f"descripcion de IA ({len(d_ia)} senales)"]

    if re.search(r"\b(it|ti|sistemas|infrastructure|infraestructura|helpdesk|soporte|redes|network|cloud|devops)\b", titulo_n):
        return "ti-general", ["TI general: puerta de entrada, no objetivo directo"]

    return "fuera", ["no es seguridad ni IA"]


# -------------------------------------------------------------- geografía ----

def clasificar_geo(v: dict, titulo_n: str, desc_n: str) -> tuple[str, bool, bool, list[str]]:
    """Devuelve (modalidad, elegible_desde_mexico, requiere_mudanza, motivos).

    Orden de decisión, del dato más fiable al menos fiable:
      1. El campo de ubicación. "Remote - USA" es un remoto cerrado por mucho
         que la descripción hable de cultura global.
      2. Restricciones explícitas en la descripción (clearance, "US only").
      3. Aperturas explícitas (LatAm, worldwide, México).
    """
    motivos: list[str] = []
    ubic_n = normalizar(v.get("ubicacion", ""))
    desc_corta = desc_n[:4000]

    en_amm = any(m in ubic_n for m in AMM)
    hibrido = tiene_termino(f"{ubic_n} {titulo_n}", "hybrid") or tiene_termino(
        f"{ubic_n} {titulo_n}", "hibrido"
    )
    remoto = bool(
        re.search(r"\bremot(e|o|a)\b", f"{ubic_n} {titulo_n}")
        or re.search(r"\b(work from home|teletrabajo|distributed|anywhere)\b", ubic_n)
        or v.get("extra", {}).get("remoto_flag") is True
        or v.get("extra", {}).get("telecommuting") is True
    )

    # 1. Monterrey y su área metropolitana: el mejor caso posible.
    if en_amm:
        modalidad = "hibrido" if hibrido else ("remoto" if remoto else "presencial")
        motivos.append("ubicacion en el area metropolitana de Monterrey: sin mudanza")
        return modalidad, True, False, motivos

    # 2. Remoto declarado pero cerrado a otro pais o estado de EEUU.
    cerrado = RX_REMOTO_CERRADO.search(ubic_n)
    if cerrado:
        motivos.append(f"remoto restringido a otra region: '{cerrado.group(0).strip()}'")
        return "remoto", False, False, motivos

    # 3. Restricciones explicitas en el texto de la vacante.
    bloqueos = _contiene(desc_corta, BLOQUEO_GEO)
    if bloqueos:
        motivos.append(f"la vacante exige: '{bloqueos[0]}'")
        return ("remoto" if remoto else "presencial"), False, False, motivos

    # 4. Apertura declarada EN LA UBICACION. Solo aquí se acepta una apertura,
    #    nunca desde la descripción: casi toda oferta corporativa contiene la
    #    palabra "global" en su texto de marca, y eso colaba vacantes de
    #    San Francisco o Dublín como si fueran remotas mundiales.
    abierto = RX_REMOTO_ABIERTO.search(ubic_n)
    if abierto:
        hallazgo = abierto.group(0).strip()
        motivos.append(f"la ubicacion te incluye: '{hallazgo}'")
        if "america" in hallazgo and "latin" not in hallazgo and "latam" not in hallazgo:
            motivos.append("'North America' a veces significa solo EEUU y Canada: confirmar")
        return ("remoto" if remoto or "remot" in ubic_n else "presencial"), True, False, motivos

    # 5. Otra parte de Mexico: viable, pero implica mudarse.
    otra_mx = RX_MX_OTRA.search(ubic_n)
    if otra_mx:
        modalidad = "remoto" if remoto else ("hibrido" if hibrido else "presencial")
        motivos.append(
            f"en Mexico pero fuera de Monterrey ({otra_mx.group(0).strip()}): exigiria mudarse"
        )
        return modalidad, True, modalidad != "remoto", motivos

    # 6. La ubicacion nombra un pais o ciudad del extranjero. Aunque diga
    #    "remote", ese remoto esta anclado a esa region: no es mundial.
    extranjera = RX_EXTRANJERA.search(ubic_n) or RX_PAIS_CERRADO.search(ubic_n)
    if extranjera:
        lugar = extranjera.group(0).strip()
        if remoto:
            # Zona gris: es remoto y la sede esta fuera, pero la vacante no
            # declara ninguna restriccion legal. Muchas empresas contratan
            # desde LatAm como contractor. Se marca en vez de descartarse.
            motivos.append(
                f"ZONA GRIS: remoto con sede en {lugar}, sin restriccion legal declarada. "
                "Pregunta si contratan contractors desde Mexico antes de invertir tiempo"
            )
            return "remoto", False, False, motivos
        motivos.append(f"presencial en el extranjero ({lugar}): requeriria visa")
        return "presencial", False, False, motivos

    # 7. Ubicacion generica ("Remote", vacia). Aqui SI vale mirar la
    #    descripcion, porque no hay ningun dato de pais que la contradiga.
    if RX_GENERICA.search(ubic_n) or not ubic_n.strip():
        abierto_desc = RX_REMOTO_ABIERTO.search(desc_corta[:2000])
        if abierto_desc:
            motivos.append(
                f"ubicacion generica y la descripcion abre a: '{abierto_desc.group(0).strip()}'"
            )
            return "remoto", True, False, motivos
        motivos.append("remoto sin region declarada: confirmar al postular que contratan desde Mexico")
        return "remoto", True, False, motivos

    # 8. Sin senales suficientes.
    if remoto:
        motivos.append(f"remoto con ubicacion ambigua: '{v.get('ubicacion','')[:40]}'")
        return "remoto", True, False, motivos
    motivos.append(f"ubicacion no concluyente: '{v.get('ubicacion','sin dato')[:45]}'")
    return "presencial", False, False, motivos


# ----------------------------------------------------------------- skills ----

def medir_habilidades(texto_n: str) -> tuple[float, list[str]]:
    """Suma ponderada de las habilidades del CV que aparecen en la vacante.

    Usa límites de palabra igual que el resto del clasificador. Cuando esto
    comparaba por subcadena, 'bec' (Business Email Compromise) casaba dentro
    de 'becario' y subía el score de cualquier vacante escrita en español.
    """
    presentes = terminos_presentes(texto_n, tuple(HABILIDADES))
    encontradas = [(h, HABILIDADES[h]) for h in presentes]
    total = sum(p for _, p in encontradas)
    encontradas.sort(key=lambda x: -x[1])
    # Se satura en 20 puntos: 5 coincidencias fuertes ya bastan.
    puntos = min(20.0, total / 3.0)
    return puntos, [h for h, _ in encontradas[:10]]


# ------------------------------------------------------------------ score ----

VEREDICTOS = [
    (72, "aplicar-ya"),
    (56, "buen-fit"),
    (40, "explorar"),
    (0, "descartado"),
]


def _dias_desde(fecha_str: str) -> int | None:
    if not fecha_str:
        return None
    try:
        d = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        return (date.today() - d).days
    except Exception:
        return None


def analizar(v: dict) -> dict:
    """Enriquece la vacante con nivel, área, geografía, score y veredicto."""
    titulo_n = normalizar(v.get("titulo", ""))
    desc_n = normalizar(v.get("descripcion", ""))
    texto_n = f"{titulo_n} {desc_n}"

    titulo = v.get("titulo", "")
    desc = v.get("descripcion", "")

    # Los tres modulos especializados sustituyen a las funciones locales.
    # Cada uno se creo para cerrar un fallo concreto detectado en el panel:
    #   geo         -> presenciales en otros estados sin marcar la mudanza
    #   experiencia -> vacantes que exigen anos de experiencia inalcanzables
    #   dominio     -> puestos de otros rubros colados en el area equivocada
    g = geo.clasificar_geo(v.get("ubicacion", ""), titulo, desc, v.get("extra"))
    modalidad = g["modalidad"]
    elegible = g["elegible_mx"]
    mudanza = g["requiere_mudanza"]
    m_geo = g["motivos"]

    d = dominio.clasificar_dominio(titulo, desc)
    area = d["area"]
    m_area = d["motivos"]

    exp = experiencia.anos_exigidos(titulo, desc)

    nivel, m_nivel = clasificar_nivel(titulo_n, desc_n)
    # Una exigencia explicita de anos manda sobre lo que sugiera el titulo:
    # habia vacantes con "junior" en el nombre que pedian 5 anos.
    if not exp["alcanzable"]:
        nivel = "excluido"
        m_nivel = list(exp["motivos"])

    pts_hab, habilidades = medir_habilidades(texto_n)

    motivos = m_nivel + m_area + m_geo
    score = 0.0

    # 1. Nivel alcanzable (máx 35)
    score += {"practicas": 35, "junior": 26, "medio": 8, "excluido": -25}[nivel]

    # 2. Relevancia de área (máx 25). Los pesos viven en `areas.py`.
    score += areas.peso(area)

    # 3. Viabilidad geográfica (máx 20). La zona base viene de la configuración.
    en_zona = areas.en_zona(v.get("ubicacion", ""))
    if not elegible:
        score -= 30
    elif en_zona:
        score += 20
        motivos.append(f"presencial/hibrido en {areas.zona()['corta']}: sin mudanza ni visa")
    elif mudanza:
        score += 6
        motivos.append("viable solo si aceptas mudarte dentro de Mexico")
    elif modalidad == "remoto":
        score += 17
    elif modalidad == "hibrido":
        score += 12
    else:
        score += 8

    # 4. Coincidencia de habilidades (máx 20)
    score += pts_hab
    if habilidades:
        motivos.append(f"coincide con tu CV en: {', '.join(habilidades[:5])}")

    # 5. Recencia (máx 5)
    dias = _dias_desde(v.get("publicado", ""))
    if dias is not None:
        if dias <= 7:
            score += 5
            motivos.append(f"publicada hace {dias} dias")
        elif dias <= 30:
            score += 2
        elif dias > 90:
            score -= 6
            motivos.append(f"antigua: {dias} dias")

    # 6. Bonus de idioma: si la vacante está en español, el nivel de inglés
    #    deja de ser freno.
    if re.search(r"\b(practicante|becario|empresa|solicitamos|ofrecemos|conocimientos)\b", desc_n):
        score += 3
        motivos.append("vacante en espanol: el nivel de ingles no es obstaculo")

    # 6b. Penalización por rol no técnico, SOLO dentro de tecnología: una
    #     vacante comercial de ciberseguridad sigue siendo una vacante de
    #     ventas. Si el área es mercadotecnia y ventas, ese es justo el puesto.
    no_tecnico = _contiene(titulo_n, ROL_NO_TECNICO)
    if no_tecnico and area in areas.TECNOLOGIA["valores"]:
        score -= 16
        motivos.append(f"rol no tecnico ('{no_tecnico[0]}'): es un puesto de negocio, no de seguridad")

    score = max(0.0, min(100.0, score))
    veredicto = next(nombre for umbral, nombre in VEREDICTOS if score >= umbral)

    v["nivel"] = nivel
    v["area"] = area
    v["modalidad"] = modalidad
    v["elegible_mx"] = elegible
    v["requiere_mudanza"] = mudanza
    v["anios_exigidos"] = exp["minimo"]
    v["evidencia_experiencia"] = exp.get("evidencia", "")
    v["confianza_area"] = d.get("confianza")
    v["habilidades_coincidentes"] = habilidades
    v["score"] = round(score, 1)
    v["veredicto"] = veredicto
    v["motivos"] = motivos
    v["dias_publicada"] = dias
    return v


def analizar_lote(vacantes: list[dict]) -> list[dict]:
    return [analizar(v) for v in vacantes]


def deduplicar(vacantes: list[dict]) -> list[dict]:
    """Misma empresa + mismo título = misma vacante. Gana la de mejor fuente.

    Prioridad de fuente: ATS oficial > bolsa de México > agregador remoto.
    El ATS es la fuente primaria; los agregadores copian y quedan desfasados.
    """
    prioridad = {
        "greenhouse": 5, "lever": 5, "ashby": 5, "workable": 5,
        "smartrecruiters": 5, "recruitee": 5,
        "linkedin": 4, "occ": 4, "computrabajo": 4,
    }

    def rango(v: dict) -> int:
        return prioridad.get(v.get("ats") or v.get("fuente", "").split(":")[0], 2)

    mejores: dict[str, dict] = {}
    for v in vacantes:
        clave = normalizar(f"{v['empresa']}|{v['titulo']}")
        clave = re.sub(r"[^a-z0-9|]", "", clave)
        actual = mejores.get(clave)
        if actual is None or rango(v) > rango(actual):
            mejores[clave] = v
        elif rango(v) == rango(actual) and len(v.get("descripcion", "")) > len(
            actual.get("descripcion", "")
        ):
            mejores[clave] = v
    return list(mejores.values())
