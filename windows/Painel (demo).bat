@echo off
setlocal
cd /d "%~dp0"
title Mitigus XIV - painel (demo)

where python >nul 2>&1
if %errorlevel% neq 0 (
  echo [!] Python nao encontrado. Instale em https://www.python.org e marque "Add to PATH".
  pause
  exit /b
)

echo Abrindo o painel de demonstracao (sem PS5, sem Admin)...
echo Use o endereco que aparecer abaixo no navegador ou no celular.
echo.
python "%~dp0run_panel.py"
pause
