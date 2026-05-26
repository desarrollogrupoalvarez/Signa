@echo off
setlocal

echo ============================================================
echo  Signa — Remitos
echo ============================================================

:: Detectar Python
set PY=
for %%p in (py python python3) do (
    if not defined PY (
        %%p --version >nul 2>&1 && set PY=%%p
    )
)
if not defined PY (
    echo ERROR: Python no encontrado. Instalar desde https://python.org
    pause & exit /b 1
)
echo Python: %PY%

:: Entorno virtual
set VENV=backend\venv
if not exist "%VENV%\Scripts\activate.bat" (
    echo Creando entorno virtual...
    %PY% -m venv "%VENV%"
)
call "%VENV%\Scripts\activate.bat"

:: Dependencias
pip install -q -r backend\requirements.txt

:: Carpetas de datos
if not exist datos\Bandeja_Entrada mkdir datos\Bandeja_Entrada
if not exist datos\Remitos_Firmados mkdir datos\Remitos_Firmados
if not exist logs mkdir logs

:: .env
if not exist .env copy .env.example .env

echo.
echo Iniciando servidor en http://localhost:5000
echo.
cd backend
python server.py
