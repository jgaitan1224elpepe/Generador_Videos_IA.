@echo off
chcp 65001 > nul
title Video Studio AI - Generador de Videos con IA
echo ========================================================
echo   Video Studio AI - Generador de Videos con Gemini e IA
echo ========================================================
echo.
echo Verificando entorno...
if not exist ".venv\Scripts\python.exe" (
    echo Error: Entorno virtual no encontrado en .venv
    pause
    exit /b 1
)

echo Iniciando servidor en http://127.0.0.1:8000 ...
echo Puedes abrir tu navegador en: http://127.0.0.1:8000
echo Para detener el servidor presiona Ctrl + C
echo.
".venv\Scripts\python.exe" run.py
pause

