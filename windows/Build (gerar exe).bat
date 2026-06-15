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

echo Instalando PyInstaller e dependencias...
python -m pip install -q pyinstaller pydivert pystray pillow

echo.
echo Gerando as TRES versoes (pode levar alguns minutos)...
echo  1/3  versao navegador...
python -m PyInstaller --noconfirm "mitigus_xiv.spec"
echo  2/3  versao janela...
python -m PyInstaller --noconfirm "mitigus_xiv_window.spec"
echo  3/3  versao sem console (bandeja)...
python -m PyInstaller --noconfirm "mitigus_xiv_tray.spec"

echo.
echo ============================================
echo  Prontos em  dist\ :
echo     Mitigus XIV.exe              (abre no navegador)
echo     Mitigus XIV (janela).exe     (janela do app)
echo     Mitigus XIV (sem console).exe (segundo plano + icone na bandeja)
echo.
echo  O ffxiv_dx11.exe do jogo NAO vai no pacote.
echo  Tenha o FFXIV/trial instalado (achado sozinho),
echo  ou crie  dist\vendor\  e cole o ffxiv_dx11.exe la.
echo ============================================
pause
