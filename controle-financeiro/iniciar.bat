@echo off
chcp 65001 >nul
title Controle Financeiro Pessoal
cd /d "%~dp0"

rem Ambiente Python fica fora da pasta do programa, em cada computador
set "AMB=%LOCALAPPDATA%\ControleFinanceiroPessoal\venv"

python --version >nul 2>nul
if errorlevel 1 (
    echo.
    echo Python nao encontrado neste computador.
    echo Instale em https://www.python.org/downloads/  ^(marque "Add Python to PATH"^)
    echo.
    pause
    exit /b 1
)

if not exist "%AMB%\Scripts\python.exe" (
    echo Preparando o programa pela primeira vez neste computador...
    python -m venv "%AMB%"
    if errorlevel 1 goto erro
)

fc /b requirements.txt "%AMB%\requirements.txt" >nul 2>nul
if errorlevel 1 (
    echo Instalando/atualizando bibliotecas...
    "%AMB%\Scripts\python.exe" -m pip install --upgrade pip -q
    "%AMB%\Scripts\python.exe" -m pip install -r requirements.txt -q
    if errorlevel 1 goto erro
    copy /y requirements.txt "%AMB%\requirements.txt" >nul
)

rem Evita a pergunta de e-mail do Streamlit na primeira execucao
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
    if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
    (echo [general]& echo email = "") > "%USERPROFILE%\.streamlit\credentials.toml"
)

echo.
echo Abrindo o Controle Financeiro Pessoal no navegador...
echo Endereco: http://localhost:8766
echo Para FECHAR o programa, feche esta janela.
echo.
"%AMB%\Scripts\python.exe" -m streamlit run main.py --server.port 8766
goto fim

:erro
echo.
echo Ocorreu um erro. Tire um print desta janela.
pause
exit /b 1

:fim
pause
