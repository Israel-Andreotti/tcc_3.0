@echo off
rem Backup do banco de producao (Postgres do Railway) para um arquivo .dump local.
rem
rem Precisa da URL PUBLICA do banco: Railway > servico Postgres > Variables > DATABASE_PUBLIC_URL.
rem Defina-a na variavel de ambiente RAILWAY_DB_URL ou cole quando o script pedir.
rem Restaurar num banco local:  pg_restore --no-owner --no-acl -d tcc_restaurado arquivo.dump
setlocal

set "PG_BIN=C:\Program Files\PostgreSQL\18\bin"
set "DESTINO=%USERPROFILE%\Documents\tcc_backups"

if not exist "%PG_BIN%\pg_dump.exe" (
    echo pg_dump nao encontrado em "%PG_BIN%". Ajuste PG_BIN neste arquivo.
    exit /b 1
)
if "%RAILWAY_DB_URL%"=="" set /p "RAILWAY_DB_URL=Cole a DATABASE_PUBLIC_URL do Postgres do Railway: "
if "%RAILWAY_DB_URL%"=="" (
    echo Nenhuma URL informada.
    exit /b 1
)

if not exist "%DESTINO%" mkdir "%DESTINO%"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmm"') do set "DATA=%%i"
set "ARQUIVO=%DESTINO%\railway_%DATA%.dump"

"%PG_BIN%\pg_dump.exe" --format=custom --no-owner --no-acl --dbname="%RAILWAY_DB_URL%" --file="%ARQUIVO%"
if errorlevel 1 (
    echo Falha no backup.
    if exist "%ARQUIVO%" del "%ARQUIVO%"
    exit /b 1
)
echo Backup salvo em "%ARQUIVO%"
