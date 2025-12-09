@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Cerebro Companion

echo.
echo ========================================
echo   Cerebro Companion
echo ========================================
echo.

:: Check if Docker Desktop is running
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo [FOUT] Docker Desktop is niet actief!
    echo.
    echo Start Docker Desktop en probeer het opnieuw.
    echo.
    echo Druk op een toets om af te sluiten...
    pause >nul
    exit /b 1
)

echo [OK] Docker Desktop is actief
echo.

:: Check if GITHUB_TOKEN is set in .env file
set GITHUB_TOKEN_SET=false
if exist ".env" (
    findstr /C:"GITHUB_TOKEN=" .env >nul 2>&1
    if !errorlevel! equ 0 (
        for /f "tokens=2 delims==" %%a in ('findstr /C:"GITHUB_TOKEN=" .env') do (
            if not "%%a"=="" set GITHUB_TOKEN_SET=true
        )
    )
)

if "%GITHUB_TOKEN_SET%"=="false" (
    echo.
    echo ============================================================
    echo   FOUT: GITHUB_TOKEN is niet geconfigureerd!
    echo ============================================================
    echo.
    echo   De cerebro_care package kan niet worden geinstalleerd
    echo   zonder een geldig GitHub token.
    echo.
    echo   Oplossing:
    echo   1. Maak een .env bestand in deze map
    echo   2. Voeg toe: GITHUB_TOKEN=jouw_github_token
    echo.
    echo   Of installeer handmatig:
    echo   pip install git+https://TOKEN@github.com/stanbies/Cerebro_Algorithm_V2.git
    echo.
    echo ============================================================
    echo.
    echo Druk op een toets om af te sluiten...
    pause >nul
    exit /b 1
)

echo [OK] GITHUB_TOKEN is geconfigureerd
echo.

:: Check for updates from GitHub before starting
echo [INFO] Controleren op updates...
git fetch origin main >nul 2>&1
git fetch --tags >nul 2>&1
for /f %%i in ('git rev-parse HEAD') do set LOCAL_HASH=%%i
for /f %%i in ('git rev-parse origin/main') do set REMOTE_HASH=%%i

:: Get latest tag for version info
set LATEST_TAG=
for /f %%i in ('git tag --sort=-version:refname') do (
    if not defined LATEST_TAG set LATEST_TAG=%%i
)
if not defined LATEST_TAG set LATEST_TAG=1.0.0

:: Check if there are new commits
set HAS_NEW_COMMITS=false
if not "%LOCAL_HASH%"=="%REMOTE_HASH%" set HAS_NEW_COMMITS=true

:: Create data directory if it doesn't exist
if not exist "data" mkdir data

:: Write version info for Docker container to read (without BOM)
>data\.latest_version echo %LATEST_TAG%
if "%HAS_NEW_COMMITS%"=="true" >>data\.latest_version echo has_commits

if not "%LOCAL_HASH%"=="%REMOTE_HASH%" (
    echo [UPDATE] Nieuwe versie beschikbaar!
    echo.
    set /p UPDATE_CHOICE="Wil je updaten naar de nieuwste versie? (J/N): "
    if /i "!UPDATE_CHOICE!"=="J" (
        echo.
        echo [INFO] Updates worden gedownload...
        git pull origin main
        if %errorlevel% neq 0 (
            echo [WAARSCHUWING] Update mislukt, doorgaan met huidige versie...
        ) else (
            echo [OK] Update voltooid!
            :: Update version file after successful pull
            for /f %%i in ('git tag --sort=-version:refname') do (
                if not defined NEW_TAG set NEW_TAG=%%i
            )
            if defined NEW_TAG echo !NEW_TAG!> data\.latest_version
        )
        echo.
    ) else (
        echo [INFO] Update overgeslagen.
        echo.
    )
) else (
    echo [OK] Je hebt de nieuwste versie.
    echo.
)

:: Build and start the container
echo [INFO] Container wordt opgestart...
echo [INFO] Cerebro Algorithm package wordt bijgewerkt...
echo.

:: Set CACHE_BUST to current timestamp to force package update
for /f %%i in ('powershell -command "Get-Date -Format yyyyMMddHHmmss"') do set CACHE_BUST=%%i

docker-compose up -d --build

if %errorlevel% neq 0 (
    echo.
    echo [FOUT] Kon de container niet starten!
    echo.
    echo Druk op een toets om af te sluiten...
    pause >nul
    exit /b 1
)

echo.
echo [OK] Cerebro Companion is gestart!
echo.

:: Wait for the server to be ready (with timeout and crash detection)
echo [INFO] Wachten tot de server klaar is...
set WAIT_COUNT=0
:waitloop
timeout /t 1 /nobreak >nul
set /a WAIT_COUNT+=1

:: Check if container is still running
set CONTAINER_RUNNING=
for /f %%i in ('docker ps -q -f "name=cerebro-companion"') do set CONTAINER_RUNNING=%%i
if "%CONTAINER_RUNNING%"=="" (
    echo.
    echo ============================================================
    echo   FOUT: Container is gestopt!
    echo ============================================================
    echo.
    echo   Dit kan komen door een ontbrekende cerebro_care package.
    echo   Controleer of GITHUB_TOKEN correct is in .env
    echo.
    echo   Bekijk de logs met: docker logs cerebro-companion
    echo.
    echo ============================================================
    echo.
    echo Druk op een toets om af te sluiten...
    pause >nul
    exit /b 1
)

:: Check if server is responding
curl -s http://127.0.0.1:18421/api/keys/status >nul 2>&1
if %errorlevel% neq 0 (
    if %WAIT_COUNT% gtr 60 (
        echo.
        echo [WAARSCHUWING] Server reageert niet na 60 seconden.
        echo Bekijk de logs met: docker logs cerebro-companion
        echo.
    )
    goto waitloop
)

echo [OK] Server is klaar!
echo.

:: Open browser
echo [INFO] Browser wordt geopend...
start http://127.0.0.1:18421

echo.
echo ========================================
echo   Cerebro Companion draait op:
echo   http://127.0.0.1:18421
echo ========================================
echo.
echo Druk op ENTER om de applicatie te stoppen...
echo.
pause >nul

:: Stop the container
echo.
echo [INFO] Container wordt gestopt...
docker-compose down

echo.
echo [OK] Cerebro Companion is gestopt.
echo.
echo Druk op een toets om af te sluiten...
pause >nul
