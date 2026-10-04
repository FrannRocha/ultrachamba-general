@echo off
REM ---------------------------------------------------------------------
REM  ULTRA CHAMBA - ciclo diario
REM
REM  Lanza `app/dia.py`: recolecta, limpia, sigue el correo, prepara la cola
REM  del dia y regenera los derivados. Deja todo listo para que solo tengas
REM  que aprobar en el panel.
REM
REM  Existe como .bat y no como una linea directa en el Programador de
REM  tareas porque una ruta con espacios rompe el entrecomillado de
REM  schtasks. Aqui no hay nada que escapar.
REM
REM  Se ejecuta a mano con doble clic. NO se registra solo como tarea
REM  programada: si quieres que corra cada dia, el README explica como
REM  programarlo a mano, lo que implica y como quitarlo.
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

"%PY%" %PYVER% -X utf8 "%~dp0app\dia.py" %*

REM Nunca devuelve error al Programador: si un paso falla, queda anotado en
REM el registro del ciclo y el resto del ciclo ya se ejecuto igual.
exit /b 0
