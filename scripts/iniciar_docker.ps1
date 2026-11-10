# LimaGo V3 — despliegue con Docker Desktop (Windows PowerShell)
# Uso:  powershell -ExecutionPolicy Bypass -File scripts\iniciar_docker.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Se creó .env a partir de .env.example (contraseñas de demostración: LimaGoPass)."
} elseif (-not (Select-String -Path ".env" -Pattern "^LIMAGO_ESCENARIO=" -Quiet)) {
    Write-Warning "Tu .env es de la V2: sus valores LIMAGO_* (300 conductores, turnos de 30 s) reemplazarían los del escenario de Lima."
    Write-Warning "Renómbralo (Rename-Item .env .env.v2) y vuelve a ejecutar este script para crear uno nuevo."
}

docker compose up --build -d
docker compose ps
Write-Host ""
Write-Host "Cuando los 6 servicios estén 'healthy':"
Write-Host "  Sitio web ........... http://localhost:8080"
Write-Host "  Monitoreo (Grafana) . http://localhost:3000   (usuario admin, contraseña LimaGoPass salvo que la cambies en .env)"
Write-Host "  Prometheus .......... http://localhost:9090"
Write-Host "  Código de operador .. LimaGoPass (LIMAGO_TOKEN_OPERACIONES en .env)"
