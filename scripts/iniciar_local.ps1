# LimaGo — ejecución local sin Docker (Windows PowerShell)
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

# La red vial ya viene en datos\miraflores.graphml; solo se descarga si falta.
& $python -m datos.red_vial

Write-Host "Iniciando worker de simulación en una ventana nueva ..."
Start-Process -FilePath $python -ArgumentList "-m", "api.worker" -WorkingDirectory (Get-Location)
Start-Sleep -Seconds 3
Write-Host "Abriendo http://localhost:8000 ..."
Start-Process "http://localhost:8000"
& $python -m uvicorn api.main:app --port 8000
