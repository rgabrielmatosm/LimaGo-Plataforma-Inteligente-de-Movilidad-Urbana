# LimaGo V3 — ejecución local sin Docker (Windows PowerShell)
# Uso:  powershell -ExecutionPolicy Bypass -File scripts\iniciar_local.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Test-Path ".venv")) {
    Write-Host "Creando entorno virtual .venv ..."
    py -3 -m venv .venv
}
$python = ".\.venv\Scripts\python.exe"
& $python -m pip install --upgrade pip
& $python -m pip install -r requirements-dev.txt

# La red académica (datos\miraflores.graphml) y la de Lima Metropolitana (datos\lima\*.npz) ya vienen
# en el repositorio; la de Miraflores solo se descarga si falta.
& $python -m datos.red_vial

# Escenario: "lima" (aplicación comercial, por defecto) o "miraflores" (escenario académico del informe)
if (-not $env:LIMAGO_ESCENARIO) { $env:LIMAGO_ESCENARIO = "lima" }
Write-Host "Escenario: $env:LIMAGO_ESCENARIO"

# Código para el centro de operaciones (solo para esta sesión local)
if (-not $env:LIMAGO_TOKEN_OPERACIONES) {
    $env:LIMAGO_TOKEN_OPERACIONES = -join ((48..57) + (97..122) | Get-Random -Count 16 | ForEach-Object { [char]$_ })
}
Write-Host "Código de operador para operaciones.html: $env:LIMAGO_TOKEN_OPERACIONES"

Write-Host "Iniciando worker de simulación en una ventana nueva ..."
Start-Process -FilePath $python -ArgumentList "-m", "api.worker" -WorkingDirectory (Get-Location)
Start-Sleep -Seconds 8   # la red de Lima tarda unos segundos en cargarse
Write-Host "Abriendo http://localhost:8000 ..."
Start-Process "http://localhost:8000"
& $python -m uvicorn api.main:app --port 8000
