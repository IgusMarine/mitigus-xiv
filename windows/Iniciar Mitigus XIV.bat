@echo off
setlocal
cd /d "%~dp0"
title Mitigus XIV

rem --- 1) precisa de Administrador (WinDivert carrega driver) -> auto-eleva
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Pedindo privilegios de Administrador...
  powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

rem --- 2) Python instalado?
where python >nul 2>&1
if %errorlevel% neq 0 (
  echo.
  echo [!] Python nao encontrado.
  echo     Instale em https://www.python.org/downloads/ e marque "Add to PATH".
  echo.
  pause
  exit /b
)

echo ============================================
echo            M I T I G U S   X I V
echo ============================================
echo.
echo Instalando dependencias (so na primeira vez)...
python -m pip install -q -r "%~dp0requirements.txt"

echo Ligando o roteamento (PC como gateway do PS5)...
powershell -ExecutionPolicy Bypass -File "%~dp0setup\enable-routing.ps1"
echo.
echo Abrindo o painel. Use o endereco que aparecer abaixo no navegador/celular.
echo (O jogo, ffxiv_dx11.exe, e procurado automaticamente. Se faltar, o painel avisa
echo  e a pasta certa abre sozinha para voce colar o arquivo.)
echo.

python "%~dp0run_proxy.py" --mitigate --panel

echo.
pause
