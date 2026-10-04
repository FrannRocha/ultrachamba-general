# Ultrachamba — versión general

Buscador local de prácticas profesionales y primer empleo en México para
varias carreras. Recolecta vacantes de bolsas públicas, las clasifica por área
profesional, comprueba que sigan publicadas, las ordena según lo alcanzables que
son para alguien sin experiencia y prepara las postulaciones. No postula ni
envía nada por su cuenta: cada paso que sale de tu computadora lo apruebas tú.

Nace de un sistema personal pensado solo para ciberseguridad e inteligencia
artificial en Monterrey. Esta versión no contiene datos de su autor y adapta la
búsqueda y la clasificación a ocho áreas. La cobertura **no es igual** en todas:
lee la sección 8 antes de confiar en los resultados.

Secciones: 1. Propósito y público · 2. Funcionalidades disponibles ·
3. Requisitos · 4. Instalación · 5. Configuración · 6. Ejecución local ·
7. Pruebas · 8. Fuentes de datos y limitaciones · 9. Publicar en GitHub

---

## 1. Propósito y público

**Para quién.** Estudiantes y recién egresados que buscan prácticas o su primer
empleo en México (presencial en su zona o remoto) en alguna de estas áreas:

| Clave | Área |
|---|---|
| `tecnologia` | Tecnología: TI, ciberseguridad, IA y datos |
| `contabilidad-finanzas` | Contabilidad y finanzas |
| `administracion` | Administración |
| `mercadotecnia-ventas` | Mercadotecnia y ventas |
| `recursos-humanos` | Recursos humanos |
| `derecho` | Derecho |
| `ingenieria-industrial` | Ingeniería industrial y operaciones |
| `salud` | Salud |

Hace falta poder ejecutar Python en tu computadora: no es un servicio en línea.

**Qué resuelve.** Las bolsas repiten anuncios, conservan vacantes caducadas y
mezclan puestos senior con prácticas. El sistema junta varias fuentes en una
base local, aparta lo que no es de tus áreas o pide años de experiencia, marca
lo que exige mudarse y te deja una cola corta de «qué hacer hoy».

**Qué no hace.** No inicia sesión en ningún portal ni guarda contraseñas: lo
que necesita tu sesión ocurre en tu navegador. No llena formularios por ti. No
envía correos sin tu aprobación, una a una: por defecto solo deja borradores.

---

## 2. Funcionalidades disponibles

| Funcionalidad | Módulos | Requiere |
|---|---|---|
| Recolección de vacantes de varias fuentes (sección 8) | `app/dia.py`, `app/excavadora.py`, `app/fuentes_*.py` | Internet |
| Clasificación por área, nivel (prácticas, junior…), años de experiencia exigidos y geografía (zona, remoto, mudanza) | `app/areas.py`, `app/dominio.py`, `app/analisis.py`, `app/experiencia.py`, `app/geo.py` | — |
| Verificación de que la vacante sigue publicada y riesgo de «vacante fantasma» | `app/verificador.py`, `app/fantasma.py`, `app/verificador_chrome.py` | Internet; Chrome para leer fichas de OCC |
| Panel local: filtros, marcar aplicadas o descartadas, plan del día, seguimiento y formación | `app/servidor.py`, `panel.html`, `app/vendor/` | Navegador |
| Vista móvil para aprobar desde el teléfono y agente que ejecuta lo aprobado | `movil.html`, `app/agente_local.py`, `app/aprobaciones.py`, `agente-en-casa.bat` | Red de confianza |
| Dashboard estático en un solo archivo HTML | `app/generar_todo.py`, `app/generar_dashboard.py` | — |
| Cola de postulación, con el porqué de cada vacante | `app/cola.py`, `app/postular.py` | — |
| Correos de postulación y correos en frío escritos solo con hechos de tu perfil | `app/generador_correos.py`, `app/correos_frios.py` | `app/perfil.py` relleno |
| Borradores en tu Gmail, seguimiento de respuestas y trámites (becas, cursos) | `app/correo_gmail.py`, `app/seguimiento.py`, `app/tramites.py` | Opcional: tu cliente OAuth de Google |
| Empresas objetivo y descubrimiento de sus bolsas de empleo (ATS) | `app/empresas.py`, `app/descubrir_ats.py` | Tus datos semilla |
| Formación gratuita: catálogo verificado, vigilante de convocatorias y elegibilidad según tu perfil | `app/datos_cursos.py`, `app/cursos.py`, `app/fuentes_cursos.py`, `app/formacion.py` | Internet para vigilar |
| Qué piden las vacantes de tus áreas; exportación a texto y copia opcional a Google Drive | `app/analisis_mercado.py`, `app/exportar_corpus.py`, `app/sincronizar_drive.py` | Drive: opcional |

Retirado respecto al sistema de origen: un bot de chat que estaba incompleto,
los generadores de su bóveda de Obsidian y su medición de contexto, además de
todos los datos personales, documentos y bases de datos.

---

## 3. Requisitos

- **Python 3.12** (probado con 3.12.3).
- **Windows 10 u 11** (probado en Windows 11). El código es Python estándar,
  pero los `.bat` y la apertura de Chrome están pensados para Windows; en Linux
  y macOS no se ha probado.
- Conexión a internet para recolectar y verificar. El panel carga sus
  tipografías desde Google Fonts; sin conexión usa las de reserva del sistema.
- Opcionales:
  - **Google Chrome**, para leer fichas de OCC y para que el agente abra
    portales;
  - **una cuenta de Google con tu propio cliente OAuth**, para Gmail y Drive;
  - **una clave de la API de Indeed**, para esa fuente;
  - **Git**, para versionar y publicar, y **GitHub CLI (`gh`)** si prefieres el
    atajo de la sección 9.

---

## 4. Instalación

Desde la carpeta del proyecto, en PowerShell o CMD:

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
copy .env.example .env
```

Solo si vas a usar Gmail o Google Drive:

```bat
python -m pip install -r requirements-opcional.txt
```

En Linux o macOS: `python3.12 -m venv .venv`, `source .venv/bin/activate` y
`cp .env.example .env`.

No hace falta crear la base de datos: la primera ejecución crea `app/datos/` y
dentro `ultrachamba.db` (SQLite). Todo lo que el sistema genera vive ahí, y Git
lo ignora.

---

## 5. Configuración

### 5.1 Áreas y zona: `.env`

`app/config.py` lee `.env` al arrancar, sin librerías externas. Si una variable
también está definida en el entorno del sistema, gana la del sistema. Cada
variable se explica en `.env.example`.

| Variable | Valores | Por defecto |
|---|---|---|
| `ULTRACHAMBA_AREAS` | Claves de la tabla de la sección 1 separadas por comas, o `todas`. En tecnología también valen `ciber-ia`, `ciberseguridad`, `ia` y `ti-general` | `todas` |
| `ULTRACHAMBA_ZONA` | `monterrey` (área metropolitana; calcula mudanza) o `nacional` (todo México, sin zona base) | `monterrey` |
| `INDEED_API_KEY` | Tu clave; vacía desactiva Indeed | vacía |

Ejemplo para Contabilidad y Administración en todo México:

```ini
ULTRACHAMBA_AREAS=contabilidad-finanzas,administracion
ULTRACHAMBA_ZONA=nacional
```

Qué cambia al elegir áreas (todo sale de `app/areas.py`):

- las consultas que se mandan a LinkedIn, OCC, Computrabajo e Indeed;
- las categorías de Remotive y Jobicy, y el prefiltro de títulos;
- el clasificador: lo que pertenece a un área no activa queda «fuera»;
- las áreas prioritarias de la cola diaria, los pesos de los cursos y la
  afinidad de las convocatorias;
- las etiquetas y los filtros del panel, que muestra en su cabecera la zona y
  las áreas activas.

Un área o una zona mal escritas detienen el programa con un mensaje claro.
Cambiar de área no reescribe lo ya guardado: cada vacante conserva el área con
la que se analizó hasta que se vuelva a analizar.

La zona `monterrey` existe porque el sistema de origen se construyó ahí: es
vocabulario geográfico configurable, no un dato personal. Añadir otra ciudad
exige definirla en `ZONAS` (`app/areas.py`) y, para calcular mudanza, adaptar
`app/geo.py`.

### 5.2 Tu perfil: `app/perfil.py`

Es una **plantilla**: los datos de identidad dicen `EJEMPLO`, y los correos
avisan mientras sea así. Rellena:

- `CANDIDATO`: nombre, correo, teléfono, ciudad y enlaces;
- `HABILIDADES` (con su peso) y `HABILIDADES_EN_ESTUDIO`;
- `LOGROS` y `LOGROS_EN`: los únicos hechos que los correos pueden afirmar;
- `CERTIFICACIONES`, `CURSOS_YA_CUBIERTO`, `CURSOS_BRECHAS` y `COMPETENCIAS`;
- `POSTULACION`: carrera, semestre, si estás titulado, disponibilidad de
  mudanza, etc.

Lo que vale `None` no se inventa: los descartes que dependen de ese dato no se
aplican, y la vacante o la convocatoria queda «por confirmar». En la cola de
postulación eso significa:

- `titulado`, `carta_de_la_universidad` y `requiere_practicas_obligatorias`
  descartan solo si valen `False`;
- `disponibilidad_mudanza = False` limita la cola a tu zona base;
- `anios_experiencia` sube el tope de años admitidos (mínimo 1);
- con `salario_esperado_mxn` se descartan las prácticas no remuneradas;
- las ofertas que exigen autorización para trabajar en Estados Unidos se
  descartan, salvo que `CANDIDATO["requiere_patrocinio_visa"]` sea `False`.

> Si publicas tu copia, **no subas tu perfil real**. Revisa `app/perfil.py`
> antes de cada commit, o haz que Git deje de ver tus cambios con
> `git update-index --skip-worktree app/perfil.py`.

### 5.3 Gmail y Google Drive (opcional)

1. Crea tu propio proyecto en Google Cloud, activa las API de Gmail y de Drive
   y crea un cliente OAuth de tipo «Aplicación de escritorio».
2. Guarda su archivo JSON como `app/datos/credenciales_drive.json`; Gmail usa el
   mismo archivo.
3. La primera vez que un módulo lo necesite se abrirá el navegador para
   autorizar. Los tokens quedan en `app/datos/`, que Git ignora.

Por defecto solo se crean **borradores** (permisos `gmail.compose` y
`gmail.readonly`) y tú pulsas Enviar. El envío directo está apagado: activarlo
exige tres pasos explícitos, descritos en `app/correo_gmail.py`, y aun así solo
sale lo que hayas aprobado una a una. Sin credenciales, el resto del sistema
funciona.

### 5.4 Empresas, contactos y convocatorias

- `app/datos_empresas.py` y `app/datos_contactos.py` traen solo **ejemplos
  ficticios** (marcados `EJEMPLO`, con dominios `example.com` y puntuación 0).
  Sustitúyelos por tu propia investigación, y no guardes datos de personas sin
  su consentimiento.
- `app/fuentes_cursos.py` vigila páginas públicas de convocatorias. Añade las de
  tu universidad y tu facultad en `SEMILLAS`: el comentario indica el formato.

---

## 6. Ejecución local

Con el entorno virtual activado y desde la raíz del proyecto:

| Qué | Comando |
|---|---|
| Panel en `http://127.0.0.1:8800` | `python app/servidor.py` |
| Ciclo del día: recolectar, limpiar, seguir el correo, preparar la cola y regenerar | `python app/dia.py` |
| El mismo ciclo sin la recolección larga | `python app/dia.py --rapido` |
| Dashboard estático (`dashboard.html`) | `python app/generar_todo.py` |
| Qué cursos conviene inscribir hoy | `python app/formacion.py --cola` |
| Vigilar páginas de convocatorias | `python app/fuentes_cursos.py` |

- El panel arranca vacío hasta la primera recolección.
- Si el puerto 8800 ya está ocupado (por ejemplo, porque otra copia del
  sistema sirve ahí), el panel no arranca. Usa otro puerto:
  `python app/servidor.py --puerto 8811` y abre `http://127.0.0.1:8811`. En
  `agente-en-casa.bat` se cambia en la variable `PUERTO`.
- El ciclo completo hace **muchas peticiones reales** y tarda minutos. LinkedIn
  limita la tasa si se abusa, así que úsalo con moderación.
- `ciclo-diario.bat` lanza `app/dia.py` con el Python de `.venv`; si no existe,
  usa `py` o `python`.

### Aprobar desde el teléfono (opcional)

`agente-en-casa.bat` arranca dos cosas: el panel escuchando en la red con token
obligatorio y el agente local que ejecuta lo aprobado. Úsalo solo en una red de
confianza o detrás de una VPN privada, nunca en una wifi pública. En la misma
máquina, la vista móvil está en `http://127.0.0.1:8800/movil` (o en el puerto
que hayas elegido).

### Ejecución automática, solo si la quieres

Ningún archivo del proyecto registra tareas programadas ni programas de inicio.
Si quieres automatizarlo, hazlo a mano sabiendo lo que implica:

- el ciclo hará peticiones reales cada día con tu conexión;
- escribirá en `app/datos/`;
- si configuraste Gmail, leerá tu correo y dejará borradores;
- nadie estará delante para ver los errores, que quedan en `app/datos/dia.log`.

Ciclo diario a las 7:00, con tu usuario y sin privilegios elevados
(`/RL LIMITED`), y cómo consultarlo y quitarlo:

```bat
schtasks /Create /TN "Ultrachamba ciclo diario" /SC DAILY /ST 07:00 /RL LIMITED /TR "C:\ruta\a\ultrachamba-general\ciclo-diario.bat"
schtasks /Query /TN "Ultrachamba ciclo diario"
schtasks /Delete /TN "Ultrachamba ciclo diario" /F
```

Pon el proyecto en una ruta sin espacios: `schtasks` rompe el entrecomillado de
las rutas que los llevan.

Agente al iniciar sesión, también sin privilegios elevados: pulsa `Win + R`,
escribe `shell:startup` y crea en esa carpeta un acceso directo a
`agente-en-casa.bat`. Se quita borrando el acceso directo.

---

## 7. Pruebas

Las pruebas son scripts: se ejecutan con Python y terminan con código 0 si todo
pasa. Ninguna hace peticiones de red, salvo `test_indeed.py` cuando hay clave.

```bat
python app/test_modulos.py
python app/test_analisis.py
python app/test_areas.py
python app/test_formacion.py
python app/test_fantasma.py
python app/test_indeed.py
```

| Prueba | Qué comprueba |
|---|---|
| `test_modulos.py` | Geografía, años de experiencia y áreas de tecnología |
| `test_analisis.py` | Nivel, elegibilidad y área en casos reales de tecnología |
| `test_areas.py` | Que cambiar de área cambia las búsquedas y la clasificación (contabilidad, recursos humanos, salud…), la zona `nacional` y los errores de configuración |
| `test_formacion.py` | Elegibilidad de cursos y convocatorias, filtro de ruido, fechas de cierre y ciclo de inscripción (crea y borra un curso ficticio en tu base local) |
| `test_fantasma.py` | La puntuación de vacante fantasma y su coherencia con la base local |
| `test_indeed.py` | La fuente Indeed contra la API real; sin `INDEED_API_KEY` dice «NO EJECUTADO» y termina con 0 |

Las pruebas escritas para tecnología fijan `ULTRACHAMBA_AREAS=tecnologia` y la
zona `monterrey` dentro de su propia ejecución, así que no dependen de tu `.env`.

**Estado conocido:** `test_formacion.py` tiene 2 fallos heredados del sistema de
origen. Son dos controles que piden que el filtro de ruido no descarte «Becas
Nacionales», y hoy sí lo descarta. Se deja visible en vez de ocultarlo.

Comprobación estática rápida: `python -m compileall -q app`.

---

## 8. Fuentes de datos y limitaciones

### Fuentes de vacantes

| Fuente | ¿Acepta consultas por área? | Cómo se usa |
|---|---|---|
| LinkedIn (búsqueda pública, sin sesión) | Sí | Consultas por área en la zona base; tecnología conserva sus listas de origen |
| OCC Mundial | Sí | Frases y términos por área, con la zona base si la hay |
| Computrabajo | Sí | Frases por área, con la zona base si la hay |
| Indeed (API de la aplicación móvil) | Sí | Solo con `INDEED_API_KEY`; desactivada por defecto |
| Remotive y Jobicy | Solo por categorías del tablón | Tecnología usa sus categorías; las demás áreas, las generalistas (`all-others`, `product`, `design`, `business`) |
| RemoteOK, Himalayas, Arbeitnow, WorkingNomads y We Work Remotely | No | Traen su catálogo y el clasificador filtra; son sobre todo empleos de tecnología en inglés |
| Bolsas ATS de empresas: Greenhouse, Lever, Ashby, SmartRecruiters, Workday, Oracle, iCIMS y SuccessFactors | No | Descargan las vacantes de listas fijas de empresas elegidas para tecnología, ciberseguridad e IA, y de corporativos con operación en México. Para otras áreas solo aportan lo que esas empresas publiquen de esos puestos |

Todas son fuentes públicas consultadas con peticiones de lectura, sin iniciar
sesión. No hay datos de demostración: lo que muestra el panel viene de estas
fuentes.

### Fuentes de formación

- `app/datos_cursos.py`: catálogo de cursos gratuitos escrito a mano, con cada
  URL comprobada en agosto de 2026. Casi todo es de tecnología (nube,
  ciberseguridad, IA), con algunos generales. Los enlaces y las condiciones
  pueden caducar.
- `app/fuentes_cursos.py`: páginas públicas de convocatorias (programas del
  gobierno de México, fabricantes y fundaciones) que se vigilan para avisar
  cuando cambian. Lo que encuentra entra como candidato, no al catálogo.
- Para las demás áreas no hay fuentes de cursos verificadas, y no se inventan:
  la sección de formación mostrará sobre todo cursos de tecnología y generales.

### Cobertura por área

| Área | Búsqueda | Clasificación | Formación | Estado |
|---|---|---|---|---|
| Tecnología | Listas de origen de cada bolsa, usadas a diario en el sistema de origen | Clasificador especializado con pruebas de regresión | Catálogo verificado | La más completa |
| Contabilidad y finanzas | 10 frases y 3 términos propios | Términos de título, más términos ambiguos (auditoría, riesgo, cumplimiento) con confianza baja | Sin catálogo propio | Nueva |
| Administración | 7 frases y 2 términos | Términos de título | Sin catálogo propio | Nueva |
| Mercadotecnia y ventas | 8 frases y 3 términos | Términos de título | Sin catálogo propio | Nueva |
| Recursos humanos | 6 frases y 2 términos | Términos de título | Sin catálogo propio | Nueva |
| Derecho | 6 frases y 2 términos | Términos de título | Sin catálogo propio | Nueva |
| Ingeniería industrial y operaciones | 8 frases y 3 términos | Términos de título | Sin catálogo propio | Nueva |
| Salud | 7 frases y 2 términos | Términos de título | Sin catálogo propio | Nueva |

«Nueva» significa que las consultas y los términos se definieron para esta
versión y se comprueban con casos de prueba, pero todavía no hay corridas largas
que midan la calidad de sus resultados.

**Validación real y pequeña (13 de septiembre de 2026).** Con la zona
`monterrey`, una página por fuente y sin iniciar sesión:

| Área activa | Fuente y consulta generada | Vacantes | En su área | Con solo tecnología activa |
|---|---|---|---|---|
| Contabilidad y finanzas | LinkedIn, «practicante contabilidad» | 10 | 10 | 0 (todas «fuera») |
| Contabilidad y finanzas | OCC, `practicante-contabilidad` | 20 | 13 | 0 |
| Recursos humanos | LinkedIn, «practicante recursos humanos» | 10 | 10 | 0 |
| Recursos humanos | Computrabajo, `practicante-recursos-humanos` | 20 | 19 | 0 |

Las que siguen «fuera» son de otras áreas (compras, cuentas clave, operaciones)
o ambiguas. Esa corrida destapó títulos en inglés con «HR» y el plural
«nóminas», que se añadieron al vocabulario y se comprueban en `test_areas.py`.

En la misma fecha, las fuentes que no aceptan consulta no aportaron **ninguna**
vacante de nivel de entrada elegible desde México a las áreas no informáticas:

| Fuente | Vacantes | De otras áreas | De entrada y elegibles desde México |
|---|---|---|---|
| Remotive, `all-others` | 16 | 4 | 0 |
| Jobicy, `business` | 50 | 23 (casi todas de ventas en el extranjero) | 0 |
| Tres tableros Greenhouse de empresas con operación en México | 6, 0 y 0 | 1 | 0 |

Para esas áreas, el volumen útil viene de LinkedIn, OCC, Computrabajo e Indeed.

Riesgos conocidos, todavía sin medir:

- Los términos están sobre todo en español, con algunos en inglés
  (`accounting`, `payroll`, `recruiter`, `sales`, `legal`, `nurse`,
  `supply chain`…). Un título en inglés que no use esas palabras puede quedar
  «fuera».
- Palabras amplias como `calidad`, `planta`, `ventas` o `comercial` pueden colar
  puestos operativos. Algunos oficios sin carrera (vigilancia, atención
  telefónica, caja, chofer…) se descartan siempre.
- En salud, buena parte de las plazas de nivel inicial (servicio social,
  internado) suele asignarse por instituciones y no publicarse en bolsas.
- «Empresas objetivo» y «correos en frío» dependen de tus datos semilla; los
  que vienen son ejemplos ficticios.

### Zona

- `monterrey`: completa. Busca en el área metropolitana, marca las vacantes «en
  tu zona» y calcula si una presencial exige mudarse.
- `nacional`: busca en todo México sin zona base. No calcula mudanza ni marca
  vacantes «en tu zona», y el filtro rápido de zona no aparece en el panel.
- No hay otras ciudades configuradas (ver 5.1).

### Limitaciones generales

- Las bolsas cambian su HTML o bloquean (403, 429) sin avisar, y una fuente
  puede quedarse en cero en silencio. Revisa el informe de salud
  (`app/salud.py`) y los registros de `app/datos/`.
- La clasificación es heurística, por palabras clave, y se equivoca. Por eso
  cada vacante muestra sus motivos y puedes descartarla con uno propio.
- La búsqueda de texto del panel distingue tildes: «nóminas» encuentra
  vacantes que «nominas» no encuentra.
- «Verificada viva» significa que la página respondía y no decía estar cerrada;
  un 403 no se da por cerrada.
- Respeta las condiciones de uso de cada sitio. El sistema hace peticiones de
  lectura sin iniciar sesión, pero el volumen es responsabilidad de quien lo
  ejecuta.
- `app/vendor/` incluye React, React DOM y htm sin modificar; sus licencias y
  atribuciones están en `app/vendor/TERCEROS.md`. El panel carga sus
  tipografías desde Google Fonts.

---

## 9. Publicar en GitHub

Este proyecto se distribuye con licencia MIT (archivo `LICENSE`). Si publicas
tu propia copia, conserva ese archivo.

1. **Revisa lo que entraría en el commit:**

   ```bat
   git status
   git ls-files --cached
   git ls-files --cached | findstr /i /r "\.db$ \.log$ \.pdf$ token client_secret credenciales \.env$"
   ```

   La última orden no debe devolver nada.
2. **Comprueba que `app/perfil.py` sigue siendo la plantilla**, con los datos
   marcados `EJEMPLO`.
3. **Configura la identidad del commit**, que quedará en el historial. Puedes
   usar el correo `noreply` que te da GitHub:

   ```bat
   git config user.name "Tu nombre o alias"
   git config user.email "tu-usuario@users.noreply.github.com"
   ```

4. **Haz el primer commit:**

   ```bat
   git add -A
   git commit -m "Ultrachamba, version general"
   ```

5. **Crea en GitHub un repositorio vacío**, sin README, licencia ni
   `.gitignore` para evitar conflictos, y déjalo privado mientras lo revisas.
6. **Conéctalo y súbelo:**

   ```bat
   git remote add origin https://github.com/TU-USUARIO/ultrachamba-general.git
   git push -u origin main
   ```

   Con GitHub CLI, los pasos 5 y 6 se resumen en
   `gh repo create ultrachamba-general --private --source . --remote origin --push`.

El repositorio guarda los finales de línea normalizados (`.gitattributes`);
cada archivo conserva el suyo en tu carpeta de trabajo.
