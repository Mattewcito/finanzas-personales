<#
  instalar_runner_cicd.ps1
  ==========================
  Instala el runner de GitHub Actions como servicio de Windows, para que
  cada push a "master" dispare automáticamente el redeploy del contenedor
  Docker en esta PC (ver .github/workflows/deploy.yml).

  El runner ya se descargó y registró en C:\actions-runner -- este script
  solo hace la parte que necesita permisos de administrador (instalarlo
  como servicio de Windows, para que quede corriendo siempre, incluso
  después de reiniciar).

  CÓMO CORRERLO (una sola vez):
    Abrí PowerShell como Administrador y corré:
        cd "C:\Finanzas personales\scripts"
        .\instalar_runner_cicd.ps1

  Requiere que "gh" (GitHub CLI) ya esté autenticado (lo está desde antes).
#>

$ErrorActionPreference = "Stop"
$gh = "C:\Program Files\GitHub CLI\gh.exe"
$runnerDir = "C:\actions-runner"

Write-Host "Generando un token de registro nuevo..." -ForegroundColor Cyan
$token = & $gh api -X POST repos/Mattewcito/finanzas-personales/actions/runners/registration-token --jq ".token"

Write-Host "Configurando el runner como servicio de Windows..." -ForegroundColor Cyan
Push-Location $runnerDir
try {
    & .\config.cmd --unattended `
        --url "https://github.com/Mattewcito/finanzas-personales" `
        --token $token `
        --name "finanzas-runner" `
        --work "_work" `
        --replace `
        --runasservice
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "Listo. Verificando el servicio:" -ForegroundColor Green
Get-Service | Where-Object { $_.Name -like "actions.runner.*" } | Select-Object Name, Status, StartType
