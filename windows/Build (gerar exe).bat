@echo off
setlocal
cd /d "%~dp0"
title Mitigus XIV - build

where python >nul 2>&1
if %errorlevel% neq 0 (
  echo [!] Python nao encontrado. Instale em https://www.python.org e marque "Add to PATH".
  pause
  exit /b
)

echo Instalando dependencias e compilador...
python -m pip install -q pyinstaller -r requirements.txt

echo.
echo Gerando a versao definitiva (Mitigus XIV App)...
python -m PyInstaller --noconfirm "mitigus_xiv_native.spec"

echo.
echo ============================================
echo  Prontos em  dist\ :
echo     Mitigus XIV App\
echo.
echo  O ffxiv_dx11.exe do jogo NAO vai no pacote.
echo  Tenha o FFXIV/trial instalado (achado sozinho),
echo  ou crie  dist\Mitigus XIV App\vendor\  e cole o ffxiv_dx11.exe la.
echo ============================================
pause
