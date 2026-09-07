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
        cd "<esta carpeta>\scripts"
        .\instalar_runner_cicd.ps1

  Requiere que "gh" (GitHub CLI) ya esté autenticado (lo está desde antes).
  gh.exe se detecta solo; si el runner no está en C:\actions-runner,
  indicá la carpeta real:
        .\instalar_runner_cicd.ps1 -RunnerDir 'C:\ruta\al\runner'
#>

param(
    [string]$GhPath,
    [string]$RunnerDir = "C:\actions-runner"
)

$ErrorActionPreference = "Stop"

if (-not $GhPath) {
    $cmd = Get-Command gh.exe -ErrorAction SilentlyContinue
    if ($cmd) {
        $GhPath = $cmd.Source
    } else {
        $fallback = "C:\Program Files\GitHub CLI\gh.exe"
        if (Test-Path $fallback) { $GhPath = $fallback }
    }
}
if (-not $GhPath -or -not (Test-Path $GhPath)) {
    Write-Host "No encontre gh.exe (GitHub CLI) automaticamente. Corre indicando la ruta:" -ForegroundColor Red
    Write-Host "  .\instalar_runner_cicd.ps1 -GhPath 'C:\ruta\a\gh.exe'" -ForegroundColor Yellow
    exit 1
}
if (-not (Test-Path $RunnerDir)) {
    Write-Host "No encontre el runner instalado en $RunnerDir. Si lo instalaste en otra carpeta, corre:" -ForegroundColor Red
    Write-Host "  .\instalar_runner_cicd.ps1 -RunnerDir 'C:\ruta\al\runner'" -ForegroundColor Yellow
    exit 1
}
$gh = $GhPath

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
