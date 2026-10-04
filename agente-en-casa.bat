@echo off
REM ---------------------------------------------------------------------
REM  ULTRA CHAMBA - el agente de casa (para aprobar desde el telefono)
REM
REM  Arranca dos cosas y las deja corriendo:
REM
REM    1. El panel escuchando EN LA RED, con su vista movil y su token.
REM       Imprime el enlace: abrelo una vez en el telefono y quedara
REM       guardado (el token se recuerda en el navegador).
REM    2. El agente local, que cada tres minutos ejecuta lo que aprobaste
REM       en el panel.
REM
REM  POR QUE HACEN FALTA LOS DOS. El panel recoge el si; el agente lo
REM  ejecuta. Si solo corre el panel, las aprobaciones se quedan en la cola.
REM  Si solo corre el agente, no hay desde donde aprobar.
REM
REM  SEGURIDAD. El panel sale a la red con token obligatorio. Usalo solo en
REM  una red de confianza o detras de una VPN privada (por ejemplo,
REM  Tailscale), para que solo lleguen tus dispositivos y no cualquiera que
REM  comparta la wifi.
REM
REM  Se ejecuta a mano con doble clic. NO se registra como tarea programada
REM  ni como programa de inicio: el README explica como hacerlo a mano si lo
REM  quieres, y como quitarlo. Se cierra cerrando las dos ventanas que abre.
REM ---------------------------------------------------------------------

cd /d "%~dp0"

REM Python: el del entorno virtual del proyecto (.venv) si existe; si no, el
REM lanzador `py` de Windows; si no, el `python` del PATH.
set "PY=%~dp0.venv\Scripts\python.exe"
set "PYVER="
if not exist "%PY%" (
  set "PY=python"
  where py >nul 2>nul
  if not errorlevel 1 (
    set "PY=py"
    set "PYVER=-3"
  )
)

REM Puerto del panel. Si el 8800 ya esta ocupado (por ejemplo, porque otra
REM copia del sistema sirve ahi), cambialo aqui.
set PUERTO=8800

REM El token se puede fijar aqui para que el enlace del telefono no cambie
REM cada vez que se reinicia. Si se deja vacio, el servidor genera uno nuevo
REM en cada arranque y hay que volver a abrir el enlace en el movil.
set TOKEN=

if "%TOKEN%"=="" (
  start "ULTRA CHAMBA - panel movil" "%PY%" %PYVER% -X utf8 "%~dp0app\servidor.py" --host 0.0.0.0 --puerto %PUERTO%
) else (
  start "ULTRA CHAMBA - panel movil" "%PY%" %PYVER% -X utf8 "%~dp0app\servidor.py" --host 0.0.0.0 --puerto %PUERTO% --token %TOKEN%
)

start "ULTRA CHAMBA - agente local" "%PY%" %PYVER% -X utf8 "%~dp0app\agente_local.py"

echo.
echo  Dos ventanas abiertas: el panel (mira ahi el enlace con el token) y el agente.
echo  Vista movil en esta maquina: http://127.0.0.1:%PUERTO%/movil
echo  Si el panel no arranca, el puerto %PUERTO% puede estar ocupado: cambia PUERTO en este archivo.
echo.
exit /b 0
