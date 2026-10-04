"""
Analisis de mercado: que piden REALMENTE las vacantes, contado sobre los anuncios.

Esto no puntua nada ni opina. Cuenta. Sobre el corpus de vacantes recolectadas,
mide con que frecuencia aparece cada certificacion, herramienta y habilidad en
los anuncios de las areas prioritarias activas, y lo compara con lo que
`perfil.HABILIDADES` ya acredita.

Los vocabularios de abajo estan pensados para tecnologia; las herramientas de
las demas areas salen de `areas.py`.

El resultado es una lista de huecos ordenada por demanda observada en el
mercado, no por criterio propio.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import analisis
import areas
import fuentes_ats
import fuentes_boards
import fuentes_linkedin
import fuentes_mexico
from nucleo import DATOS, guardar_json, log, normalizar, terminos_presentes
from perfil import HABILIDADES

# ---------------------------------------------------------------------------
# Vocabularios a contar. Se cuentan por aparicion literal en el anuncio.
# ---------------------------------------------------------------------------

CERTIFICACIONES = [
    "comptia security+", "security+", "sec+", "comptia network+", "network+",
    "comptia cysa+", "cysa+", "comptia pentest+", "pentest+", "comptia a+",
    "cissp", "cisa", "cism", "crisc", "cgeit", "ccsp",
    "ceh", "certified ethical hacker", "oscp", "osce", "gpen", "gcih", "gsec",
    "giac", "cysa", "ejpt", "ecpptv", "crtp",
    "sc-200", "sc-100", "sc-300", "sc-900", "az-500", "az-900", "az-104",
    "ms-500", "aws certified security", "aws certified cloud practitioner",
    "aws certified solutions architect", "gcp professional cloud security",
    "iso 27001 lead auditor", "iso 27001 lead implementer", "iso 27001",
    "iso 22301", "iso 42001", "itil", "cobit", "pci dss", "cissp associate",
    "fortinet nse", "nse 4", "nse 7", "ccna", "ccnp", "ccna security",
    "cka", "ckad", "terraform associate", "splunk core certified",
    "google cybersecurity certificate", "isc2 cc", "certified in cybersecurity",
]

HERRAMIENTAS = [
    "splunk", "qradar", "arcsight", "logrhythm", "elastic siem", "wazuh",
    "microsoft sentinel", "sentinel", "microsoft defender", "defender for endpoint",
    "crowdstrike", "sentinelone", "carbon black", "cortex xdr", "trellix",
    "nessus", "qualys", "rapid7", "insightvm", "openvas", "burp suite",
    "metasploit", "nmap", "wireshark", "kali", "checkmarx", "sonarqube",
    "veracode", "snyk", "fortify", "acunetix", "owasp zap",
    "active directory", "entra id", "azure ad", "okta", "cyberark",
    "beyondtrust", "sailpoint", "saviynt", "keycloak",
    "palo alto", "fortinet", "fortigate", "cisco ise", "checkpoint",
    "zscaler", "netskope", "proofpoint", "mimecast",
    "aws", "azure", "gcp", "kubernetes", "docker", "terraform", "ansible",
    "jira", "servicenow", "confluence", "power bi", "tableau",
    "mitre att&ck", "att&ck", "nist csf", "cis benchmark", "cis controls",
    "soc 2", "gdpr", "lfpdppp", "hipaa", "sox", "itgc",
]

LENGUAJES = [
    "python", "powershell", "bash", "sql", "javascript", "java", "c#", "go",
    "kql", "kusto", "regex", "yara", "sigma", "terraform", "linux", "windows server",
]

IA = [
    "machine learning", "deep learning", "tensorflow", "pytorch", "scikit-learn",
    "pandas", "numpy", "llm", "langchain", "rag", "prompt engineering",
    "hugging face", "openai", "generative ai", "nlp", "computer vision",
    "mlops", "databricks", "spark", "airflow", "data pipeline",
    "ai governance", "responsible ai", "ai safety", "red teaming",
    "prompt injection", "guardrails", "model evaluation", "eu ai act", "nist ai rmf",
]

BLANDAS = [
    "ingles", "english", "bilingual", "bilingue", "b2", "c1", "advanced english",
    "ingles avanzado", "ingles intermedio", "trabajo en equipo", "teamwork",
    "comunicacion", "communication", "proactiv", "autodidacta", "liderazgo",
    "documentacion", "documentation", "atencion al detalle",
]

# Lo que el perfil YA acredita, para calcular el hueco (ver perfil.py).
YA_EN_CV = set(HABILIDADES)


def corpus() -> list[dict]:
    """Recolecta y se queda con los anuncios de las areas prioritarias activas."""
    log("Recolectando corpus de mercado...")
    v_ats, _ = fuentes_ats.recolectar_todo()
    v_boards, _ = fuentes_boards.recolectar_todo()
    v_mx, _ = fuentes_mexico.recolectar_todo()
    v_li = fuentes_linkedin.recolectar_todo()
    todas = analisis.deduplicar(v_ats + v_boards + v_mx + v_li)

    # Prefiltro barato ANTES de clasificar: el clasificador completo sobre
    # 10.000 anuncios tarda minutos, y aqui solo interesan los de las areas
    # activas. Un barrido de palabras clave sobre el titulo reduce el corpus
    # antes de pagar ese coste.
    clave = areas.regex_prefiltro_titulo()
    candidatas = [
        v for v in todas
        if (clave.search(v["titulo"]) or clave.search(normalizar(v["titulo"])))
        and len(v.get("descripcion", "")) > 200
    ]
    log(f"  prefiltro: {len(todas)} -> {len(candidatas)} candidatas por titulo")

    analizadas = analisis.analizar_lote(candidatas)
    prioritarias = set(areas.valores_prioritarios())
    mercado = [v for v in analizadas if v["area"] in prioritarias]
    log(f"  corpus de mercado: {len(mercado)} anuncios con descripcion util")
    return mercado


def contar(anuncios: list[dict], vocabulario: list[str]) -> Counter:
    c: Counter = Counter()
    for v in anuncios:
        texto = normalizar(f"{v['titulo']} {v.get('descripcion','')}")
        for t in set(terminos_presentes(texto, tuple(vocabulario))):
            c[t] += 1
    return c


def segmentar(anuncios: list[dict]) -> dict[str, list[dict]]:
    segmentos = {"TODO EL MERCADO": anuncios}
    # La zona base, si la hay: con `nacional` este segmento no existe.
    if areas.zona()["subcadenas"]:
        segmentos[f"ZONA {areas.zona()['corta'].upper()}"] = [
            v for v in anuncios if areas.en_zona(v.get("ubicacion", ""))]
    return {
        **segmentos,
        "MEXICO": [v for v in anuncios if "mexico" in normalizar(v.get("ubicacion", ""))],
        "PRACTICAS Y JUNIOR": [v for v in anuncios if v["nivel"] in ("practicas", "junior")],
        "REMOTO ELEGIBLE": [v for v in anuncios if v["modalidad"] == "remoto" and v["elegible_mx"]],
    }


def informe(anuncios: list[dict]) -> dict:
    segmentos = segmentar(anuncios)
    salida: dict = {"tamanos": {k: len(v) for k, v in segmentos.items()}, "conteos": {}}

    bloques = [
        ("CERTIFICACIONES", CERTIFICACIONES),
        ("HERRAMIENTAS Y MARCOS", HERRAMIENTAS),
        ("LENGUAJES Y SCRIPTING", LENGUAJES),
        ("IA Y DATOS", IA),
        ("IDIOMA Y BLANDAS", BLANDAS),
        ("HERRAMIENTAS DE TUS AREAS", areas.herramientas()),
    ]

    for nombre_seg, lista in segmentos.items():
        if not lista:
            continue
        salida["conteos"][nombre_seg] = {}
        for nombre_bloque, vocab in bloques:
            c = contar(lista, vocab)
            salida["conteos"][nombre_seg][nombre_bloque] = {
                termino: {"n": n, "pct": round(100 * n / len(lista), 1)}
                for termino, n in c.most_common(40)
            }
    return salida


def huecos(inf: dict, segmento: str = "PRACTICAS Y JUNIOR") -> list[tuple]:
    """Lo que el mercado pide y el perfil no acredita."""
    fila = []
    datos = inf["conteos"].get(segmento, {})
    for bloque, terminos in datos.items():
        for termino, m in terminos.items():
            if termino in YA_EN_CV:
                continue
            fila.append((m["pct"], m["n"], bloque, termino))
    fila.sort(reverse=True)
    return fila


def imprimir(inf: dict) -> None:
    print("\n" + "=" * 78)
    print("QUE PIDEN LOS ANUNCIOS REALES  (conteo sobre el texto de cada vacante)")
    print("=" * 78)
    for seg, n in inf["tamanos"].items():
        print(f"  {seg:22} {n:5} anuncios")

    for seg in ("PRACTICAS Y JUNIOR",
                *[s for s in inf["tamanos"] if s.startswith("ZONA ")],
                "REMOTO ELEGIBLE"):
        datos = inf["conteos"].get(seg)
        if not datos:
            continue
        print(f"\n{'-' * 78}\nSEGMENTO: {seg}  ({inf['tamanos'][seg]} anuncios)\n{'-' * 78}")
        for bloque, terminos in datos.items():
            top = [(t, m) for t, m in list(terminos.items())[:12] if m["n"] >= 2]
            if not top:
                continue
            print(f"\n  {bloque}")
            for t, m in top:
                marca = "[ya lo tienes]" if t in YA_EN_CV else ""
                print(f"    {m['pct']:5.1f}%  ({m['n']:4})  {t:34} {marca}")


if __name__ == "__main__":
    anuncios = corpus()
    inf = informe(anuncios)
    guardar_json("mercado.json", inf)
    imprimir(inf)

    print("\n" + "=" * 78)
    print("HUECOS: lo que el mercado junior pide y tu CV NO acredita")
    print("=" * 78)
    for pct, n, bloque, termino in huecos(inf)[:30]:
        print(f"  {pct:5.1f}%  ({n:4})  {bloque:24} {termino}")
