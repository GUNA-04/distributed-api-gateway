@echo off
REM Quick-start script for local development
REM Prerequisites: Docker Desktop, Python 3.11+

echo ================================================
echo  Distributed API Gateway - Quick Start
echo ================================================

REM Check Docker
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Docker is not installed or not running
    exit /b 1
)

REM Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python 3.11+ is not installed
    exit /b 1
)

echo.
echo [1/4] Starting infrastructure (Postgres, Redis, Kafka)...
docker compose -f infra\docker\docker-compose.yml up -d postgres redis zookeeper kafka

echo.
echo [2/4] Waiting for services to be healthy...
timeout /t 15 /nobreak >nul
for %%s in (postgres redis kafka) do (
    docker compose -f infra\docker\docker-compose.yml ps %%s | findstr /i "Up" >nul
    if %errorlevel% neq 0 (
        echo WARNING: %%s may not be fully ready
    )
)

echo.
echo [3/4] Installing Python dependencies...
pip install -r requirements.txt

echo.
echo [4/4] Starting the gateway...
echo Gateway will be available at: http://localhost:8000
echo API Docs: http://localhost:8000/docs
echo.
uvicorn gateway.app.main:app --host 0.0.0.0 --port 8000 --reload

pause
