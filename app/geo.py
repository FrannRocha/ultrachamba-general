"""
Clasificacion geografica de vacantes para ULTRA CHAMBA.

Modulo autonomo: solo depende de `nucleo` para normalizar texto. No importa
`perfil` ni `analisis` a proposito, para que el vocabulario geografico viva en
un unico lugar y pueda corregirse sin tocar el scoring.

QUE PROBLEMA RESUELVE
---------------------
Quien usa el sistema vive en Mexico y solo trabaja PRESENCIAL sin mudarse
dentro de su zona base (`ULTRACHAMBA_ZONA`, ver `areas.py`). Con la zona
`monterrey`, cualquier vacante presencial o hibrida en otra parte de Mexico
exigiria mudarse; presencial fuera de Mexico exigiria visa. Distinguir esos
tres casos es todo el trabajo de este modulo.

Solo el area metropolitana de Monterrey (AMM) tiene su vocabulario definido.
Con la zona `nacional` no se presupone ninguna ciudad: una vacante en Mexico
es elegible y NO se calcula si exige mudarse, porque decidirlo seria inventar
donde vive la persona. Las reglas 1 y 2 de abajo cambian solo en eso.

EL BUG QUE ORIGINA ESTE ARCHIVO
-------------------------------
La deteccion de "apertura a Mexico" usaba el patron `\\bmexico\\b`, y la cadena
"ciudad de mexico" CONTIENE la palabra "mexico". Como la apertura se evaluaba
ANTES que la regla de "otra parte de Mexico", 36 vacantes presenciales de CDMX,
Estado de Mexico, Jalisco, etc. quedaban marcadas como remotas abiertas y con
`requiere_mudanza = False`. Aqui se corrige por partida doble:

  1. ORDEN: la regla 2 (Mexico fuera del AMM) se evalua ANTES que la regla 5
     (remoto abierto). El orden de precedencia era la causa raiz.
  2. PATRON: `RX_APERTURA_MX` lleva lookbehind/lookahead para que "mexico"
     NO case dentro de "ciudad de mexico", "estado de mexico", "mexico city",
     "mexico, d.f." ni "new mexico". Asi el bug no puede reaparecer aunque
     alguien reordene las reglas mas adelante.

ORDEN DE PRECEDENCIA (es contractual, no reordenar a la ligera)
---------------------------------------------------------------
  1. Ubicacion en el AMM ................ elegible, sin mudanza  (mejor caso)
  2. Mexico fuera del AMM ............... elegible, CON mudanza si no es remoto
  3. Remoto cerrado a otra region ....... no elegible
  4. Restriccion legal en descripcion ... no elegible
  5. Remoto genuinamente abierto ........ elegible, sin mudanza
  6. Presencial en ciudad extranjera .... no elegible (requeriria visa)
  7. Ubicacion generica ................. mirar descripcion; si no hay senal,
                                          elegible con "confirmar al postular"
  8. Sin senales suficientes ............ fallback conservador

Todos los `motivos` se escriben en espanol SIN ACENTOS, porque acaban en
tablas de consola, nombres de archivo de Obsidian y CSV.
"""
from __future__ import annotations

import re

import areas
from nucleo import normalizar, terminos_presentes, tiene_termino

# =========================================================== vocabulario ====
# Todos los patrones se comparan contra texto ya normalizado por
# `nucleo.normalizar()`: minusculas y SIN acentos. Por eso aqui se escribe
# "alvaro obregon" y no "Álvaro Obregón".

# --- 1. Area metropolitana de Monterrey -------------------------------------
# Se parte en dos niveles a proposito:
#
#   FUERTE     -> nombra Nuevo Leon o Monterrey de forma inequivoca.
#   MUNICIPIO  -> nombres de municipio que TAMBIEN existen en otros estados o
#                 paises ("Guadalupe" esta en Zacatecas, "Juarez" en Chihuahua,
#                 "Santiago" es la capital de Chile). Solo cuentan como AMM si
#                 el resto de la ubicacion no nombra otro lugar.
AMM_FUERTE = r"""(?x)
    \b nuevo \s+ leon \b
  | (?<![a-z]) n \. \s* l \. (?![a-z])
  | \b monterrey \b
  | \b mty \b
  | \b area \s+ metropolitana \s+ de \s+ monterrey \b
  | \b san \s+ pedro \s+ garza \s+ garcia \b
  | \b san \s+ nicolas \s+ de \s+ los \s+ garza \b
"""

AMM_MUNICIPIO = r"""(?x)
    \b san \s+ pedro \s+ garza \b
  | \b san \s+ nicolas \b
  | \b guadalupe \b
  | \b apodaca \b
  | \b santa \s+ catarina \b
  | \b (general \s+)? escobedo \b
  | \b garcia \b
  | (?<!benito\s) (?<!ciudad\s) \b juarez \b
    # Santiago, N.L. existe, pero 'santiago' a secas casaba con Santiago de
    # Chile y marcaba vacantes chilenas como alcanzables SIN MUDARSE. Seis
    # vacantes lo sufrieron, entre ellas "Analista de Seguridad Ofensiva" de
    # EY, ubicada en "Area metropolitana de Santiago". Se exige que NO venga
    # seguido de Chile ni precedido de "metropolitana de".
  | (?<!metropolitana\sde\s) \b santiago \b (?! \s* (de \s+ chile | , \s* chile | \s+ chile))
  | \b cadereyta \b
  | \b salinas \s+ victoria \b
  | \b cienega \s+ de \s+ flores \b
  | \b pesqueria \b
"""

# --- 2. Mexico fuera del AMM ------------------------------------------------
# Presencial o hibrido aqui = mudarse. Es la rama que el bug se saltaba.
# "ciudad de mexico", "estado de mexico" y "mexico city" van PRIMERO y de
# forma explicita: son exactamente las cadenas que el patron de apertura
# confundia con "abierto a Mexico".
MX_FUERA_AMM = r"""(?x)
    # --- Ciudad de Mexico, en todas sus grafias ---
    \b ciudad \s+ de \s+ mexico \b
  | \b cd \.? \s* de \s+ mexico \b
  | \b mexico \s+ city \b
  | \b cdmx \b
  | \b distrito \s+ federal \b
  | \b mexico \s* ,? \s* d \.? \s* f \.? (?![a-z])
    # --- alcaldias de la CDMX (aparecen solas en LinkedIn) ---
  | \b alvaro \s+ obregon \b
  | \b benito \s+ juarez \b
  | \b miguel \s+ hidalgo \b
  | \b cuauhtemoc \b
  | \b tlalpan \b
  | \b coyoacan \b
  | \b iztapalapa \b
  | \b iztacalco \b
  | \b azcapotzalco \b
  | \b venustiano \s+ carranza \b
  | \b gustavo \s+ a \.? \s* madero \b
  | \b (la \s+)? magdalena \s+ contreras \b
  | \b cuajimalpa \b
  | \b xochimilco \b
  | \b tlahuac \b
  | \b milpa \s+ alta \b
    # --- Estado de Mexico ---
  | \b estado \s+ de \s+ mexico \b
  | \b edo \.? \s* (de \s*)? mex \w* \b
  | \b naucalpan \b
  | \b tlalnepantla \b
  | \b toluca \b
  | \b ecatepec \b
  | \b atizapan \b
  | \b cuautitlan \b
  | \b nezahualcoyotl \b
  | \b huixquilucan \b
  | \b metepec \b
  | \b texcoco \b
    # --- resto de la republica ---
  | \b jalisco \b | \b guadalajara \b | \b zapopan \b | \b tlaquepaque \b
  | \b tonala \b | \b puerto \s+ vallarta \b
  | \b queretaro \b | \b puebla \b | \b cholula \b
  | \b tijuana \b | \b baja \s+ california \b | \b mexicali \b | \b ensenada \b
  | \b los \s+ cabos \b | \b cabo \s+ san \s+ lucas \b | \b la \s+ paz \b
  | \b chihuahua \b | \b hermosillo \b | \b sonora \b | \b nogales \b
  | \b saltillo \b | \b coahuila \b | \b torreon \b | \b gomez \s+ palacio \b
  | \b durango \b | \b aguascalientes \b | \b zacatecas \b
  | \b san \s+ luis \s+ potosi \b | \b slp \b
  | \b merida \b | \b yucatan \b | \b cancun \b | \b quintana \s+ roo \b
  | \b playa \s+ del \s+ carmen \b | \b campeche \b
  | \b guanajuato \b | \b irapuato \b | \b celaya \b | \b silao \b | \b bajio \b
  | \b veracruz \b | \b xalapa \b | \b coatzacoalcos \b
  | \b reynosa \b | \b matamoros \b | \b tampico \b | \b nuevo \s+ laredo \b
  | \b ciudad \s+ victoria \b | \b tamaulipas \b
  | \b culiacan \b | \b sinaloa \b | \b mazatlan \b | \b los \s+ mochis \b
  | \b morelia \b | \b michoacan \b | \b oaxaca \b | \b chiapas \b
  | \b tuxtla \b | \b villahermosa \b | \b tabasco \b
  | \b colima \b | \b nayarit \b | \b tepic \b | \b guerrero \b | \b acapulco \b
  | \b cuernavaca \b | \b morelos \b | \b pachuca \b | \b tlaxcala \b
"""

# --- 3 y 6. Fuera de Mexico -------------------------------------------------
# Estados de EEUU: "Remote - Virginia, USA" es un remoto cerrado aunque no
# escriba "USA" pegado a "Remote".
ESTADOS_EEUU = (
    r"alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware"
    r"|florida|georgia|hawaii|idaho|illinois|indiana|iowa|kansas|kentucky"
    r"|louisiana|maine|maryland|massachusetts|michigan|minnesota|mississippi"
    r"|missouri|montana|nebraska|nevada|new\s+hampshire|new\s+jersey"
    r"|new\s+mexico|new\s+york|north\s+carolina|north\s+dakota|ohio|oklahoma"
    r"|oregon|pennsylvania|rhode\s+island|south\s+carolina|south\s+dakota"
    r"|tennessee|texas|utah|vermont|virginia|washington|wisconsin|wyoming"
)

# Paises y bloques donde alguien que vive en Mexico necesitaria visa o permiso
# de trabajo.
# OJO: aqui NO va "america" a secas. Si estuviera, "North America" y
# "Latin America" -- que SI le sirven -- se leerian como region cerrada.
PAISES_EXTRANJEROS = (
    r"united\s+states|u\.?\s?s\.?a\b|\busa\b|\bu\.s\.\b|\bus\b"
    r"|canada|united\s+kingdom|\buk\b|england|scotland|wales|ireland"
    r"|germany|deutschland|france|spain|espana|portugal|italy|italia"
    r"|poland|polska|romania|netherlands|belgium|switzerland|austria"
    r"|sweden|norway|denmark|finland|greece|czech|hungary|bulgaria"
    r"|israel|turkey|\buae\b|saudi|qatar"
    r"|india|pakistan|bangladesh|china|japan|korea|taiwan|hong\s+kong"
    r"|singapore|malaysia|thailand|vietnam|philippines|indonesia"
    r"|australia|new\s+zealand|\banz\b|apac"
    r"|nigeria|kenya|egypt|south\s+africa|ghana|morocco"
    r"|brazil|brasil|argentina|chile|colombia|peru|uruguay|paraguay"
    r"|bolivia|ecuador|venezuela|costa\s+rica|panama|guatemala"
    r"|honduras|el\s+salvador|nicaragua|dominican|puerto\s+rico"
    r"|europe|emea|\beea\b|\beu\b"
)

CIUDADES_EXTRANJERAS = r"""(?x)
    \b (san \s+ francisco | bay \s+ area | silicon \s+ valley | new \s+ york | nyc
      | brooklyn | seattle | austin | boston | chicago | denver | los \s+ angeles
      | san \s+ diego | palo \s+ alto | mountain \s+ view | sunnyvale | cupertino
      | washington \s+ d | atlanta | dallas | houston | miami | phoenix
      | philadelphia | portland | minneapolis | detroit | charlotte | raleigh
      | nashville | salt \s+ lake | las \s+ vegas | pittsburgh | columbus
      | kansas \s+ city | tampa | orlando | boulder | arlington | mclean
      | toronto | vancouver | montreal | ottawa | calgary | waterloo
      | london | manchester | edinburgh | dublin | belfast | cambridge \s* , \s* uk
      | berlin | munich | muenchen | hamburg | frankfurt | cologne | stuttgart
      | paris | lyon | toulouse | madrid | barcelona | lisbon | lisboa | porto
      | amsterdam | rotterdam | brussels | zurich | geneva | vienna | prague
      | warsaw | krakow | wroclaw | budapest | bucharest | sofia | athens
      | stockholm | oslo | copenhagen | helsinki | tallinn | vilnius
      | tel \s+ aviv | jerusalem | istanbul | dubai | abu \s+ dhabi
      | bangalore | bengaluru | hyderabad | mumbai | new \s+ delhi | gurgaon
      | gurugram | noida | pune | chennai | kolkata | ahmedabad
      | tokyo | osaka | seoul | beijing | shanghai | shenzhen | taipei
      | sydney | melbourne | brisbane | perth | auckland | wellington
      | sao \s+ paulo | rio \s+ de \s+ janeiro | belo \s+ horizonte | brasilia
      | buenos \s+ aires | bogota | medellin | lima | montevideo
      | santiago \s+ de \s+ chile | san \s+ jose \s* , \s* costa
      # LinkedIn escribe las ubicaciones chilenas asi, sin nombrar el pais.
      | area \s+ metropolitana \s+ de \s+ santiago
      | region \s+ metropolitana \s+ de \s+ santiago) \b
"""

# --- Remoto cerrado a una region donde no puede trabajar --------------------
REMOTO_CERRADO = rf"""(?x)
    # "Remote - USA", "Remote (Canada)", "Remote / Virginia"
    \b remote \s* [-–—(,/|]+ \s* ({PAISES_EXTRANJEROS}|{ESTADOS_EEUU}) \b
    # "USA - Remote", "US Remote"
  | \b ({PAISES_EXTRANJEROS}) \s* [-–—(,/|]* \s* remote \b
    # "Remote in the US", "Remote within the United States"
  | \b remote \s+ (in|within|from|across) \s+ (the \s+)?
      ({PAISES_EXTRANJEROS}|{ESTADOS_EEUU}) \b
    # "Remote - Virginia, USA": el pais aparece detras del estado
  | \b remote \b [^|]{{0,28}}? \b ({ESTADOS_EEUU}) \s* ,? \s*
      (usa|us\b|united\s+states)
"""

# Programas que por definicion solo admiten personal de EEUU. Se buscan
# tambien en el TITULO, que es donde suelen aparecer ("DoD SkillBridge Intern").
# Ojo: NO se usa "federal" a secas. En espanol "Distrito Federal" es la CDMX,
# y una vacante de CDMX se marcaria como programa militar de EEUU.
PROGRAMA_EEUU = r"""(?x)
    \b (skillbridge | govcloud | public \s+ sector \s+ us
      | federal \s+ (government | contractor | contract | agency | civilian)) \b
"""

# --- 5. Remoto genuinamente abierto ----------------------------------------
# "north america" entra aqui porque Mexico es Norteamerica, pero se marca con
# una advertencia: muchas empresas lo usan para decir "EEUU y Canada".
REMOTO_ABIERTO = r"""(?x)
    \b (worldwide | anywhere | globally | global \s+ remote
      | fully \s+ distributed | globally \s+ distributed
      | work \s+ from \s+ anywhere | any \s+ location | any \s+ timezone
      | hire \s+ globally | hiring \s+ globally) \b
  | \b remote \s* [-–—(,/|]* \s* (global | worldwide | anywhere | international) \b
  | \b (latam | latin \s+ america | america \s+ latina | latinoamerica
      | south \s+ america | americas | north \s+ america | norteamerica) \b
"""

# EL PATRON DEL BUG, YA BLINDADO.
# Detecta "abierto a Mexico" sin casar dentro de los nombres de lugar que
# significan justo lo contrario:
#   (?<!ciudad de ) -> "ciudad de mexico"  = CDMX, exige mudanza
#   (?<!estado de ) -> "estado de mexico"  = Edomex, exige mudanza
#   (?<!new )       -> "new mexico"        = estado de EEUU, exige visa
#   (?!\s+city)     -> "mexico city"       = CDMX, exige mudanza
#   (?!\s*,?\s*d.f.)-> "mexico, d.f."      = CDMX, exige mudanza
# Cada lookbehind es de ancho fijo, requisito del modulo `re`.
APERTURA_MX = r"""(?x)
    (?<!ciudad\sde\s) (?<!estado\sde\s) (?<!new\s)
    \b mexic (o|an) \b
    (?! \s+ city)
    (?! \s* ,? \s* d \.? \s* f \b)
"""

# --- 7. Ubicacion que no dice nada del pais ---------------------------------
UBIC_GENERICA = r"""(?x)
    ^ \s* (remote | remoto | remota | work \s+ from \s+ home | wfh | teletrabajo
      | distributed | virtual | home \s*-?\s* based | flexible | varios
      | multiple \s+ locations | multiples \s+ ubicaciones | n/?a | tbd |) \s* $
"""

# --- 4. Restricciones legales declaradas en la descripcion ------------------
# Se buscan con `nucleo.terminos_presentes`, que respeta limites de palabra.
BLOQUEO_LEGAL = [
    "us citizen", "u.s. citizen", "united states citizen", "citizenship required",
    "security clearance", "ts/sci", "top secret", "public trust",
    "clearance required", "active clearance", "polygraph", "itar", "ear99",
    "us only", "united states only", "usa only", "domestic us",
    "must reside in the united states", "must be located in the us",
    "must be based in the united states", "must live in the united states",
    "must reside in the us", "must be a us resident",
    "authorized to work in the united states",
    "eligible to work in the united states",
    "legally authorized to work in the us",
    "work authorization in the united states",
    "eu only", "europe only", "eea only", "uk only",
    "must be based in the uk", "right to work in the uk",
    "canada only", "must reside in canada", "must be based in canada",
    "india only", "australia only", "singapore only",
    "no visa sponsorship", "we do not sponsor", "unable to sponsor",
    "cannot provide sponsorship", "without sponsorship",
    "not able to sponsor", "does not offer sponsorship",
]

# --- Modalidad --------------------------------------------------------------
PALABRAS_HIBRIDO = ["hybrid", "hibrido", "hibrida", "semipresencial", "mixto"]
PALABRAS_REMOTO = [
    "remote", "remoto", "remota", "remotely", "wfh", "work from home",
    "trabajo desde casa", "teletrabajo", "distributed", "anywhere",
    "home based", "home-based", "telecommute", "telecommuting",
]
PALABRAS_PRESENCIAL = [
    "on site", "on-site", "onsite", "in office", "in-office", "presencial",
    "en sitio", "sede", "oficina",
]

# ============================================================== compilado ===
RX_AMM_FUERTE = re.compile(AMM_FUERTE)
RX_AMM_MUNICIPIO = re.compile(AMM_MUNICIPIO)
RX_MX_FUERA_AMM = re.compile(MX_FUERA_AMM)
RX_REMOTO_CERRADO = re.compile(REMOTO_CERRADO)
RX_REMOTO_ABIERTO = re.compile(REMOTO_ABIERTO)
RX_APERTURA_MX = re.compile(APERTURA_MX)
RX_GENERICA = re.compile(UBIC_GENERICA)
RX_CIUDAD_EXTRANJERA = re.compile(CIUDADES_EXTRANJERAS)
RX_PAIS_EXTRANJERO = re.compile(rf"\b({PAISES_EXTRANJEROS})\b")
RX_ESTADO_EEUU = re.compile(rf"\b({ESTADOS_EEUU})\b")

# Para la zona `nacional`: todo Mexico, incluidos Nuevo Leon y los municipios
# del AMM cuyo nombre no se repite en otro estado. Los ambiguos (Guadalupe,
# Juarez, Garcia, Santiago) no entran: sin zona base no hay contra que
# desempatarlos.
AMM_INEQUIVOCO = r"""(?x)
    \b apodaca \b
  | \b santa \s+ catarina \b
  | \b (general \s+)? escobedo \b
  | \b cadereyta \b
  | \b salinas \s+ victoria \b
  | \b cienega \s+ de \s+ flores \b
  | \b pesqueria \b
  | \b san \s+ pedro \s+ garza \b
  | \b san \s+ nicolas \s+ de \s+ los \s+ garza \b
"""
# Las tres expresiones empiezan con su propia bandera `(?x)`, y Python no
# admite banderas globales a mitad de un patron: se quitan y se compila todo
# en modo verbose.
RX_MX_TODO = re.compile(
    "|".join(f"(?:{p.replace('(?x)', '', 1)})"
             for p in (MX_FUERA_AMM, AMM_FUERTE, AMM_INEQUIVOCO)),
    re.X)


# ================================================================ helpers ===

def _recorte(coincidencia: re.Match | None) -> str:
    """Texto literal que disparo una regla, para poder auditar el motivo."""
    return coincidencia.group(0).strip(" ,-/|(") if coincidencia else ""


def _bandera_remota(extra: dict | None) -> bool:
    """Banderas de remoto que ya traen algunas APIs (Greenhouse, Lever, LinkedIn)."""
    if not isinstance(extra, dict):
        return False
    for clave in ("remoto_flag", "telecommuting", "remote", "is_remote", "remoto"):
        if extra.get(clave) is True:
            return True
    return False


def detectar_modalidad(ubic_n: str, titulo_n: str, extra: dict | None = None) -> str:
    """'remoto' | 'presencial' | 'hibrido' a partir de ubicacion y titulo.

    Se mira SOLO ubicacion y titulo, nunca la descripcion: casi toda oferta
    corporativa dice "remote-first culture" en su texto de marca, y eso
    convertia vacantes presenciales de Dublin en remotas.

    Si aparecen a la vez "hybrid" y "remote", gana HIBRIDO: es la lectura
    conservadora, porque hibrido implica pisar la oficina y por tanto puede
    implicar mudanza.
    """
    texto = f"{ubic_n} {titulo_n}"
    if any(tiene_termino(texto, p) for p in PALABRAS_HIBRIDO):
        return "hibrido"
    if any(tiene_termino(texto, p) for p in PALABRAS_REMOTO) or _bandera_remota(extra):
        return "remoto"
    return "presencial"


# =============================================================== API ========

def clasificar_geo(
    ubicacion: str,
    titulo: str,
    descripcion: str,
    extra: dict | None = None,
    zona: str | None = None,
) -> dict:
    """Devuelve {'modalidad', 'elegible_mx', 'requiere_mudanza', 'motivos'}.

    - modalidad ......... 'remoto' | 'presencial' | 'hibrido'
    - elegible_mx ....... bool. ¿Se puede tomar este empleo sin visa?
    - requiere_mudanza .. bool. True si es presencial/hibrido en Mexico pero
                          fuera de la zona base. Con la zona `nacional` es
                          siempre False: no se sabe donde vive la persona.
    - motivos ........... list[str] en espanol sin acentos, auditable.

    `zona` es una clave de `areas.ZONAS`; por defecto, la de la configuracion.

    El orden de los bloques de abajo ES la logica del modulo. Reordenarlos
    reintroduce el bug que este archivo existe para corregir.
    """
    ubic_n = normalizar(ubicacion or "")
    titulo_n = normalizar(titulo or "")
    desc_n = normalizar(descripcion or "")[:4000]
    con_amm = areas.ZONAS[zona or areas.zona_clave()]["geo"] == "monterrey"

    motivos: list[str] = []
    modalidad = detectar_modalidad(ubic_n, titulo_n, extra)

    # Se calcula por adelantado para poder AVISAR de una restriccion legal
    # incluso en las ramas donde la precedencia dice que no decide (1 y 2).
    bloqueos = terminos_presentes(desc_n, BLOQUEO_LEGAL)

    if not con_amm:
        # -- Reglas 1 y 2 sin zona base: Mexico, sin calcular mudanza. -----
        en_mexico = RX_MX_TODO.search(ubic_n)
        if en_mexico:
            lugar = _recorte(en_mexico)
            if modalidad == "remoto":
                motivos.append(
                    f"remoto anclado a {lugar}: en Mexico, pero confirmar que no "
                    "pidan ir a la oficina"
                )
                return _resultado("remoto", True, False, motivos)
            motivos.append(
                f"{modalidad} en Mexico ({lugar}); sin zona base configurada no se "
                "calcula si exige mudarse"
            )
            if bloqueos:
                motivos.append(
                    f"aviso: la descripcion menciona '{bloqueos[0]}'; suele ser "
                    "plantilla de EEUU en una vacante mexicana, confirmar al postular"
                )
            return _resultado(modalidad, True, False, motivos)

    # -- Regla 1: area metropolitana de Monterrey. El mejor caso posible. ----
    # Los municipios de nombre ambiguo (Guadalupe, Juarez, Santiago, Garcia)
    # solo cuentan si la ubicacion no nombra ademas otro lugar: asi
    # "Guadalupe, Zacatecas" y "Santiago, Chile" no se cuelan como AMM.
    amm_fuerte = RX_AMM_FUERTE.search(ubic_n) if con_amm else None
    amm_municipio = RX_AMM_MUNICIPIO.search(ubic_n) if con_amm else None

    # EL TITULO GANA A LA UBICACION cuando nombra otra ciudad.
    #
    # El titulo lo escribe la empresa; la ubicacion la rellena el portal, y a
    # veces la rellena mal. Se encontraron 17 vacantes etiquetadas "Nuevo Leon"
    # cuyo propio titulo decia CDMX, Tijuana o Queretaro: "Ingeniero SOC Jr /
    # N1 / 7x24 CDMX", "Becario en Desarrollo de Software - Tijuana", "Becario
    # TI - Santa Fe, CDMX". Las 17 salian como alcanzables SIN MUDARSE.
    #
    # Cuando la empresa se molesta en poner la ciudad en el titulo, esa es la
    # ciudad. Se cree al titulo.
    titulo_otra_ciudad = RX_MX_FUERA_AMM.search(titulo_n)
    if titulo_otra_ciudad and (amm_fuerte or amm_municipio):
        lugar = _recorte(titulo_otra_ciudad)
        motivos.append(
            f"el titulo dice '{lugar}' aunque el portal la etiquete en Nuevo Leon: "
            "manda el titulo, que lo escribe la empresa")
        if modalidad == "remoto":
            return _resultado(modalidad, True, False, motivos)
        return _resultado(modalidad, True, True, motivos)
    hay_otro_lugar = bool(
        RX_MX_FUERA_AMM.search(ubic_n)
        or RX_CIUDAD_EXTRANJERA.search(ubic_n)
        or RX_PAIS_EXTRANJERO.search(ubic_n)
    )
    if amm_fuerte or (amm_municipio and not hay_otro_lugar):
        lugar = _recorte(amm_fuerte or amm_municipio)
        motivos.append(
            f"ubicacion en el area metropolitana de Monterrey ('{lugar}'): sin mudanza"
        )
        if bloqueos:
            motivos.append(
                f"aviso: la descripcion menciona '{bloqueos[0]}', probablemente "
                "texto heredado de una plantilla; confirmar al postular"
            )
        return _resultado(modalidad, True, False, motivos)

    # -- Regla 2: Mexico, pero fuera del AMM. ------------------------------
    # ESTA ES LA RAMA DEL BUG. Va ANTES que la deteccion de apertura remota
    # porque "Ciudad de Mexico" contiene la palabra "mexico" y antes se leia
    # como "abierto a Mexico" en vez de como "exige mudarse".
    mx_fuera = RX_MX_FUERA_AMM.search(ubic_n) if con_amm else None
    if mx_fuera:
        lugar = _recorte(mx_fuera)
        if modalidad == "remoto":
            motivos.append(
                f"remoto anclado a {lugar}: en Mexico, sin mudanza, pero confirmar "
                "que no pidan ir a la oficina"
            )
            return _resultado("remoto", True, False, motivos)
        motivos.append(
            f"{modalidad} en Mexico pero fuera del area metropolitana de Monterrey "
            f"({lugar}): exigiria mudarse"
        )
        if bloqueos:
            motivos.append(
                f"aviso: la descripcion menciona '{bloqueos[0]}'; suele ser plantilla "
                "de EEUU en una vacante mexicana, confirmar al postular"
            )
        return _resultado(modalidad, True, True, motivos)

    # -- Regla 3: remoto cerrado a otro pais o a un estado de EEUU. ---------
    cerrado = RX_REMOTO_CERRADO.search(ubic_n)
    if cerrado:
        motivos.append(f"remoto restringido a otra region: '{_recorte(cerrado)}'")
        return _resultado("remoto", False, False, motivos)

    # -- Regla 4: restriccion legal explicita en la descripcion. -----------
    if bloqueos:
        motivos.append(f"la vacante exige: '{bloqueos[0]}'")
        if len(bloqueos) > 1:
            motivos.append(f"otras restricciones declaradas: {', '.join(bloqueos[1:3])}")
        return _resultado(modalidad, False, False, motivos)

    # -- Regla 5: remoto genuinamente abierto. -----------------------------
    abierto = RX_REMOTO_ABIERTO.search(ubic_n) or RX_APERTURA_MX.search(ubic_n)
    if abierto:
        hallazgo = _recorte(abierto)
        motivos.append(f"la ubicacion te incluye: '{hallazgo}'")
        if "north america" in hallazgo or "norteamerica" in hallazgo:
            motivos.append(
                "'North America' es ambiguo: muchas empresas lo usan para decir "
                "solo EEUU y Canada. Confirmar antes de invertir tiempo"
            )
        if modalidad == "presencial":
            # "Mexico Remote" sin la palabra remote en el titulo, por ejemplo.
            modalidad = "remoto"
        return _resultado(modalidad, True, False, motivos)

    # -- Regla 6: ciudad o pais extranjero. --------------------------------
    extranjero = (
        RX_CIUDAD_EXTRANJERA.search(ubic_n)
        or RX_PAIS_EXTRANJERO.search(ubic_n)
        or RX_ESTADO_EEUU.search(ubic_n)
    )
    if extranjero:
        lugar = _recorte(extranjero)
        if modalidad == "remoto":
            # Zona gris: es remoto y la sede esta fuera, pero la vacante no
            # declara ninguna restriccion legal. Se marca como no elegible
            # para no inflar la lista, pero el motivo dice que se puede
            # preguntar: varias empresas contratan desde LatAm como contractor.
            motivos.append(
                f"ZONA GRIS: remoto con sede en {lugar}, sin restriccion legal "
                "declarada. Preguntar si contratan contractors desde Mexico"
            )
            return _resultado("remoto", False, False, motivos)
        motivos.append(f"presencial en el extranjero ({lugar}): requeriria visa")
        return _resultado(modalidad, False, False, motivos)

    # -- Regla 7: ubicacion generica. Aqui SI vale mirar la descripcion, ----
    # porque no hay ningun dato de pais que la pueda contradecir.
    if RX_GENERICA.search(ubic_n) or not ubic_n.strip():
        abierto_desc = RX_REMOTO_ABIERTO.search(desc_n[:2000]) or RX_APERTURA_MX.search(
            desc_n[:2000]
        )
        if abierto_desc:
            motivos.append(
                f"ubicacion generica y la descripcion abre a: '{_recorte(abierto_desc)}'"
            )
            return _resultado("remoto", True, False, motivos)
        motivos.append(
            "remoto sin region declarada: confirmar al postular que contratan "
            "desde Mexico"
        )
        return _resultado("remoto", True, False, motivos)

    # -- Regla 8: sin senales suficientes. ---------------------------------
    if modalidad == "remoto":
        motivos.append(f"remoto con ubicacion ambigua: '{(ubicacion or '')[:40]}'")
        return _resultado("remoto", True, False, motivos)
    motivos.append(f"ubicacion no concluyente: '{(ubicacion or 'sin dato')[:45]}'")
    return _resultado(modalidad, False, False, motivos)


def _resultado(
    modalidad: str, elegible: bool, mudanza: bool, motivos: list[str]
) -> dict:
    """Punto unico de salida: garantiza que el dict siempre tenga la misma forma.

    Invariante duro: si NO es elegible, `requiere_mudanza` no significa nada y
    se fuerza a False; y un empleo remoto nunca exige mudarse.
    """
    if not elegible or modalidad == "remoto":
        mudanza = False
    return {
        "modalidad": modalidad,
        "elegible_mx": bool(elegible),
        "requiere_mudanza": bool(mudanza),
        "motivos": motivos,
    }


def clasificar_vacante(v: dict) -> dict:
    """Comodidad para el pipeline: aplica `clasificar_geo` a una vacante entera."""
    return clasificar_geo(
        v.get("ubicacion", ""),
        v.get("titulo", ""),
        v.get("descripcion", ""),
        v.get("extra"),
    )
