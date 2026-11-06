# LimaGo — despliegue con Docker Desktop (Windows PowerShell)
# Uso:  powershell -ExecutionPolicy Bypass -File scripts\iniciar_docker.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    $clave = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ })
    (Get-Content ".env") -replace "cambia-esta-contrasena", $clave | Set-Content ".env"
    Write-Host "Se creó .env con una contraseña aleatoria para PostgreSQL."
}

docker compose up --build -d
docker compose ps
Write-Host "Cuando todos los servicios estén 'healthy', abre http://localhost:8080"
