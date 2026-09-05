<#
  configurar_tareas_programadas.ps1
  ====================================
  OBSOLETO desde que ambas versiones (dev y online) corren en Docker con
  "restart: unless-stopped" -- Docker ya las mantiene siempre arriba,
  sin necesitar estas tareas. Se deja el script como referencia; si
  preferís volver al modelo anterior (sin Docker para dev), seguís
  pudiendo correrlo. Si no, podés desactivar/borrar las tareas
  "FinanzasDev" y "FinanzasDocker" desde el Programador de tareas de
  Windows.

  Crea las 2 tareas programadas del proyecto Finanzas Personales:

    1. FinanzasDev     -> corre "py app.py" (servidor de desarrollo,
                          puerto 5001) al iniciar sesión, sin ventana
                          visible. Para probar funcionalidades nuevas.
    2. FinanzasDocker  -> corre "docker compose up -d" al iniciar sesión
                          (con 45s de espera para que Docker Desktop
                          arranque primero). Es la versión estable,
                          puerto 5002, pensada para acceder vía Tailscale.

  También abre el puerto 5002 en el firewall de Windows (solo ese puerto,
  no el 5001 -- la versión de desarrollo sigue sin ser alcanzable desde
  ningún otro dispositivo, ni siquiera por Tailscale).

  CÓMO CORRERLO (una sola vez):
    1. Botón derecho sobre este archivo -> "Ejecutar con PowerShell"
       -- si eso no funciona (pide permisos), abrí PowerShell como
       Administrador (buscá "PowerShell" en el menú de inicio, clic
       derecho -> "Ejecutar como administrador") y corré:
           cd "C:\Finanzas personales\scripts"
           .\configurar_tareas_programadas.ps1
    2. Windows puede pedir confirmación (UAC) -- aceptá.

  Después de correrlo, ambas tareas quedan activas para siempre (se
  disparan cada vez que iniciás sesión en Windows). No hace falta
  volver a correr este script salvo que quieras recrearlas.
#>

$ErrorActionPreference = "Stop"

$pythonw = "C:\Users\User\AppData\Local\Programs\Python\Python314\pythonw.exe"
$srcDir  = "C:\Finanzas personales\src"
$rootDir = "C:\Finanzas personales"
$docker  = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"

# --- Tarea 1: servidor de desarrollo ---------------------------------------
$action1   = New-ScheduledTaskAction -Execute $pythonw -Argument "app.py" -WorkingDirectory $srcDir
$trigger1  = New-ScheduledTaskTrigger -AtLogOn
$settings1 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
              -ExecutionTimeLimit (New-TimeSpan -Days 0) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName "FinanzasDev" -Action $action1 -Trigger $trigger1 -Settings $settings1 `
  -Description "Servidor local de desarrollo (puerto 5001) para probar funcionalidades nuevas de Finanzas Personales." `
  -Force

# --- Tarea 2: contenedor Docker (version estable) --------------------------
$action2   = New-ScheduledTaskAction -Execute $docker -Argument "compose up -d" -WorkingDirectory $rootDir
$trigger2  = New-ScheduledTaskTrigger -AtLogOn
$trigger2.Delay = "PT45S"   # 45s de margen para que Docker Desktop termine de arrancar
$settings2 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
              -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName "FinanzasDocker" -Action $action2 -Trigger $trigger2 -Settings $settings2 `
  -Description "Levanta el contenedor Docker (puerto 5002) de Finanzas Personales -- version estable, accesible via Tailscale." `
  -Force

Write-Host ""
Write-Host "Listo. Tareas creadas:" -ForegroundColor Green
Get-ScheduledTask -TaskName "FinanzasDev", "FinanzasDocker" | Select-Object TaskName, State

# --- Firewall: abrir SOLO el puerto del contenedor Docker (5002) ----------
# El 5001 (desarrollo) queda cerrado a propósito -- ese sigue en 127.0.0.1,
# solo accesible desde esta misma PC.
New-NetFirewallRule -DisplayName "FinanzasPersonales-Docker" -Direction Inbound -Protocol TCP -LocalPort 5002 -Action Allow -Profile Any -ErrorAction SilentlyContinue | Out-Null
Write-Host "Puerto 5002 habilitado en el firewall." -ForegroundColor Green

Write-Host ""
Write-Host "IMPORTANTE: en Docker Desktop, activa 'Start Docker Desktop when you sign in'" -ForegroundColor Yellow
Write-Host "(Settings -> General) para que FinanzasDocker encuentre el motor de Docker ya arrancado." -ForegroundColor Yellow
