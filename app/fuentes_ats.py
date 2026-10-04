"""
Colectores de ATS (Applicant Tracking Systems).

Por qué esto es el corazón del sistema: Greenhouse, Lever, Ashby, Workable,
Recruitee y SmartRecruiters publican la bolsa de trabajo de cada empresa como
JSON abierto. Si el API devuelve una vacante, esa vacante está publicada AHORA
en el sitio oficial de la empresa. No hay intermediario que la haya copiado ni
caducado: es la fuente primaria. Eso resuelve el problema de "vacantes fantasma"
de los agregadores.

Los tokens de empresa son candidatos: los que no existen devuelven 404 y se
descartan solos. No se inventa ninguna vacante.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from nucleo import limpiar_html, log, obtener_json, vacante

# --------------------------------------------------------------------------
# Catálogo de empresas por ATS.
# Criterio de inclusión: (a) contratan en México/Monterrey, (b) contratan
# remoto global o LatAm, o (c) son referentes de ciberseguridad / IA cuyas
# vacantes de prácticas vale la pena vigilar.
# --------------------------------------------------------------------------

GREENHOUSE = [
    # Ciberseguridad
    "cloudflare", "crowdstrike", "sentinelone", "tenable", "rapid7", "sophos",
    "arcticwolf", "huntress", "dragos", "snyk", "hashicorp", "okta", "auth0",
    "1password", "keeper", "bitwarden", "cybereason", "trellix", "netskope",
    "zscaler", "proofpoint", "abnormalsecurity", "materialsecurity", "vanta",
    "drata", "secureframe", "tailscale", "teleport", "doppler", "semgrep",
    "chainguard", "socketdev", "trailofbits", "bishopfox", "nccgroup",
    "hackerone", "bugcrowd", "intigriti", "synack", "expel", "redcanary",
    "corelight", "runzero", "greynoise", "censys", "recordedfuture",
    "flashpoint", "intel471", "silentpush", "domaintools",
    # IA / ML
    "anthropic", "openai", "scaleai", "surgehq", "huggingface", "cohere",
    "databricks", "weightsandbiases", "runwayml", "perplexityai", "together",
    "fireworksai", "modal", "replicate", "langchain", "llamaindex", "pinecone",
    "weaviate", "chroma", "deepgram", "assemblyai", "elevenlabs", "synthesia",
    "adept", "imbue", "sierra", "harvey", "abridge", "cresta", "glean",
    "writer", "typeface", "instabase", "hebbia", "mistral",
    # Tech con presencia MX / LatAm o remoto amigable
    "datadog", "elastic", "grafanalabs", "confluent", "mongodb", "cockroachlabs",
    "stripe", "coinbase", "gemini", "kraken", "circle", "chainalysis", "trmlabs",
    "plaid", "brex", "ramp", "mercury", "affirm", "robinhood", "gusto",
    "rippling", "deel", "remotecom", "oyster", "papayaglobal", "toptal",
    "twilio", "segment", "airtable", "asana", "notion", "figma", "canva",
    "discord", "reddit", "pinterest", "duolingo", "coursera", "udemy",
    "nubank", "mercadolibre", "rappi", "kavak", "clip", "bitso", "konfio",
    "clara", "stori", "belvo", "kushki", "jeeves", "nowports", "justo",
    "platzi", "runa", "cometa", "luuna", "tul", "frubana", "chiper",
]

LEVER = [
    "gitlab", "cloudera", "netlify", "vercel", "supabase", "planetscale",
    "hopper", "wealthsimple", "shieldai", "anduril", "palantir",
    "bitfinex", "consensys", "ledger", "trailofbits", "yugabyte",
    "matterport", "sardine", "unit21", "alloy", "persona", "socure",
    "veza", "opal", "cerbos", "oso", "authzed", "warp", "temporal",
    "wiz", "orca-security", "cyberark", "aqua-security", "sysdig",
    "upstart", "nuvemshop", "tiendanube", "worldcoin", "toolsforhumanity",
    "voiceflow", "cresta", "moveworks", "observe", "cribl", "panther-labs",
    "jumpcloud", "beyondtrust", "delinea", "saviynt", "sailpoint",
]

ASHBY = [
    "openai", "ramp", "linear", "cursor", "anysphere", "sierra", "decagon",
    "clay", "mercor", "elevenlabs", "suno", "pika", "luma-ai", "physicalintelligence",
    "skild", "figure", "cohere", "contextual", "reflection", "magic",
    "notion", "vanta", "chainguard", "wiz", "astrix", "pangea", "descope",
    "corgea", "pillar", "protectai", "lakera", "hiddenlayer", "robustintelligence",
    "haize", "gray-swan", "patronus", "galileo", "braintrust", "langfuse",
    "arize", "fiddler", "credo", "holisticai", "guardrails", "promptfoo",
    "zeropath", "xbow", "runsybil", "terra-security", "dreadnode",
    "irregular", "andon-labs", "far-ai", "redwood-research", "apollo-research",
    "epoch-ai", "metr", "eleuther", "goodfire", "transluce", "conjecture",
]

WORKABLE = [
    "acronis", "cyberint", "hub-security", "cyberproof", "checkmarx",
    "cymulate", "safebreach", "pentera", "cyberark-il", "coro",
    "cynet", "guardio", "silverfort", "grip-security", "seemplicity",
    "deep-instinct", "morphisec", "hunters", "axonius", "reco",
]

RECRUITEE = [
    "outsystems", "onfido", "sensity", "onespan", "hadrian", "eye-security",
    "zivver", "cybersprint", "nixu", "sekoia", "harfanglab", "tehtris",
]

SMARTRECRUITERS = [
    "Bosch", "Visa", "Ubisoft", "McDonalds", "Publicis", "Avery",
    "Ipsos", "SGS", "Sanofi", "Bayer", "Continental", "Danone", "Nestle",
    "Atos", "Capgemini", "Orange", "Schneider", "Alstom", "SafranGroup",
    "Adecco", "Randstad", "SoftwareAG", "Software", "Wallbox",
]


# ------------------------------------------------------------ Greenhouse ----

def greenhouse(token: str) -> list[dict]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    datos = obtener_json(url)
    if not isinstance(datos, dict) or "jobs" not in datos:
        return []
    salida = []
    for j in datos.get("jobs", []):
        ubic = (j.get("location") or {}).get("name", "")
        empresa = _empresa_desde_token(token, j)
        salida.append(
            vacante(
                titulo=j.get("title", ""),
                empresa=empresa,
                url=j.get("absolute_url", ""),
                fuente=f"greenhouse:{token}",
                ats="greenhouse",
                ubicacion=ubic,
                # `limpiar_html` y no el crudo: ver la cabecera de este parche.
                descripcion=limpiar_html(j.get("content", "")),
                publicado=j.get("updated_at") or j.get("first_published"),
                extra={"gh_id": j.get("id"), "token": token},
            )
        )
    return salida


def _empresa_desde_token(token: str, j: dict) -> str:
    meta = j.get("company_name")
    if meta:
        return meta
    return token.replace("-", " ").replace("_", " ").title()


# ------------------------------------------------------------------ Lever ----

def lever(token: str) -> list[dict]:
    url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    datos = obtener_json(url)
    if not isinstance(datos, list):
        return []
    salida = []
    for j in datos:
        cat = j.get("categories") or {}
        desc = (j.get("descriptionPlain") or j.get("description") or "")
        listas = j.get("lists") or []
        for bloque in listas:
            desc += " " + limpiar_html(bloque.get("content", ""))
        salida.append(
            vacante(
                titulo=j.get("text", ""),
                empresa=token.replace("-", " ").title(),
                url=j.get("hostedUrl") or j.get("applyUrl", ""),
                fuente=f"lever:{token}",
                ats="lever",
                ubicacion=cat.get("location", "") or "",
                descripcion=desc,
                publicado=j.get("createdAt"),
                extra={
                    "equipo": cat.get("team", ""),
                    "compromiso": cat.get("commitment", ""),
                    "token": token,
                },
            )
        )
    return salida


# ------------------------------------------------------------------ Ashby ----

def ashby(token: str) -> list[dict]:
    url = (
        f"https://api.ashbyhq.com/posting-api/job-board/{token}"
        "?includeCompensation=true"
    )
    datos = obtener_json(url)
    if not isinstance(datos, dict):
        return []
    salida = []
    for j in datos.get("jobs", []):
        comp = j.get("compensation") or {}
        resumen = comp.get("compensationTierSummary") or ""
        salida.append(
            vacante(
                titulo=j.get("title", ""),
                empresa=token.replace("-", " ").title(),
                url=j.get("jobUrl") or j.get("applyUrl", ""),
                fuente=f"ashby:{token}",
                ats="ashby",
                ubicacion=j.get("location", "")
                or ", ".join(j.get("secondaryLocations", []) or []),
                descripcion=j.get("descriptionPlain") or j.get("descriptionHtml", ""),
                publicado=j.get("publishedAt"),
                salario=resumen,
                extra={
                    "departamento": j.get("department", ""),
                    "equipo": j.get("team", ""),
                    "remoto_flag": j.get("isRemote"),
                    "token": token,
                },
            )
        )
    return salida


# --------------------------------------------------------------- Workable ----

def workable(token: str) -> list[dict]:
    url = f"https://apply.workable.com/api/v1/widget/accounts/{token}?details=true"
    datos = obtener_json(url)
    if not isinstance(datos, dict):
        return []
    nombre = (datos.get("name") or token).strip()
    salida = []
    for j in datos.get("jobs", []):
        ubic = ", ".join(
            x for x in [j.get("city"), j.get("state"), j.get("country")] if x
        )
        salida.append(
            vacante(
                titulo=j.get("title", ""),
                empresa=nombre,
                url=j.get("url") or j.get("application_url", ""),
                fuente=f"workable:{token}",
                ats="workable",
                ubicacion=ubic,
                descripcion=j.get("description", ""),
                publicado=j.get("published_on") or j.get("created_at"),
                extra={"token": token, "telecommuting": j.get("telecommuting")},
            )
        )
    return salida


# -------------------------------------------------------------- Recruitee ----

def recruitee(token: str) -> list[dict]:
    url = f"https://{token}.recruitee.com/api/offers/"
    datos = obtener_json(url)
    if not isinstance(datos, dict):
        return []
    salida = []
    for j in datos.get("offers", []):
        salida.append(
            vacante(
                titulo=j.get("title", ""),
                empresa=j.get("company_name") or token.title(),
                url=j.get("careers_url") or j.get("careers_apply_url", ""),
                fuente=f"recruitee:{token}",
                ats="recruitee",
                ubicacion=j.get("location", "") or j.get("city", ""),
                descripcion=j.get("description", ""),
                publicado=j.get("published_at") or j.get("created_at"),
                extra={"token": token, "remote": j.get("remote")},
            )
        )
    return salida


# -------------------------------------------------------- SmartRecruiters ----

def smartrecruiters(token: str) -> list[dict]:
    url = (
        f"https://api.smartrecruiters.com/v1/companies/{token}/postings"
        "?limit=100&offset=0"
    )
    datos = obtener_json(url)
    if not isinstance(datos, dict):
        return []
    salida = []
    for j in datos.get("content", []):
        loc = j.get("location") or {}
        ubic = ", ".join(
            x for x in [loc.get("city"), loc.get("region"), loc.get("country")] if x
        )
        uuid = j.get("id", "")
        salida.append(
            vacante(
                titulo=j.get("name", ""),
                empresa=(j.get("company") or {}).get("name") or token,
                url=f"https://jobs.smartrecruiters.com/{token}/{uuid}",
                fuente=f"smartrecruiters:{token}",
                ats="smartrecruiters",
                ubicacion=ubic,
                descripcion=(j.get("jobAd") or {}).get("sections", {}) and "" or "",
                publicado=j.get("releasedDate"),
                extra={"token": token, "remote": loc.get("remote")},
            )
        )
    return salida


# ------------------------------------------------------------ orquestación ----

COLECTORES = [
    ("greenhouse", greenhouse, GREENHOUSE),
    ("lever", lever, LEVER),
    ("ashby", ashby, ASHBY),
    ("workable", workable, WORKABLE),
    ("recruitee", recruitee, RECRUITEE),
    ("smartrecruiters", smartrecruiters, SMARTRECRUITERS),
]


def recolectar_todo(hilos: int = 16) -> tuple[list[dict], dict]:
    """Consulta todos los ATS en paralelo. Devuelve (vacantes, informe)."""
    vacantes: list[dict] = []
    informe = {"validos": {}, "invalidos": {}, "total_por_ats": {}}

    tareas = []
    with ThreadPoolExecutor(max_workers=hilos) as ex:
        for nombre_ats, funcion, tokens in COLECTORES:
            informe["validos"][nombre_ats] = []
            informe["invalidos"][nombre_ats] = []
            for token in tokens:
                tareas.append((nombre_ats, token, ex.submit(funcion, token)))

        for nombre_ats, token, fut in tareas:
            try:
                res = fut.result()
            except Exception:
                res = []
            if res:
                informe["validos"][nombre_ats].append(f"{token}({len(res)})")
                vacantes.extend(res)
            else:
                informe["invalidos"][nombre_ats].append(token)

    for nombre_ats, _, _ in COLECTORES:
        informe["total_por_ats"][nombre_ats] = sum(
            1 for v in vacantes if v["ats"] == nombre_ats
        )
        log(
            f"  {nombre_ats}: {len(informe['validos'][nombre_ats])} bolsas vivas, "
            f"{informe['total_por_ats'][nombre_ats]} vacantes"
        )
    return vacantes, informe


if __name__ == "__main__":
    vs, inf = recolectar_todo()
    log(f"TOTAL ATS: {len(vs)} vacantes crudas")
