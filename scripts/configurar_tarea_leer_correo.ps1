<#
  configurar_tarea_leer_correo.ps1
  ====================================
  Crea la tarea programada de Windows que corre src/leer_correo.py cada
  5 minutos, para siempre (mientras la PC esté prendida) -- reemplaza al
  bot externo de Gmail que hasta ahora escribía el Excel.

  Cada corrida revisa TODAS las cuentas configuradas desde la interfaz
  ("Correo automático" en el menú, una por usuario) y procesa solo las
  que ya les toca según SU PROPIA frecuencia (cada X minutos, o una vez
  al día a una hora fija) -- ver esta_pendiente() en leer_correo.py. Por
  eso alcanza con esta única tarea, corriendo seguido: no hace falta
  crear ni tocar nada acá cuando alguien agrega o cambia su
  configuración desde la web.

  Requisito PREVIO: al menos una persona debe haber configurado su
  correo desde la interfaz (menú "Correo automático", dentro de la app
  -- ahí mismo hay una guía paso a paso). Sin ninguna cuenta configurada,
  la tarea igual queda creada pero cada corrida no hace nada (se ve en
  data/leer_correo.log).

  CÓMO CORRERLO (una sola vez):
    Botón derecho sobre este archivo -> "Ejecutar con PowerShell". Si
    pide permisos, abrí PowerShell como Administrador y corré:
        cd "C:\Finanzas personales\scripts"
        .\configurar_tarea_leer_correo.ps1

  Después de correrlo, la tarea "FinanzasLeerCorreo" queda activa para
  siempre (arranca sola al iniciar sesión y se repite cada 5 min). Cada
  corrida deja renglones en data/leer_correo.log, etiquetados por
  usuario -- revisalo si algo no cuadra. No hace falta volver a correr
  este script salvo que quieras recrear la tarea.
#>

$ErrorActionPreference = "Stop"

$pythonw = "C:\Users\User\AppData\Local\Programs\Python\Python314\pythonw.exe"
$srcDir  = "C:\Finanzas personales\src"

$action   = New-ScheduledTaskAction -Execute $pythonw -Argument "leer_correo.py --dias 2 --aplicar" -WorkingDirectory $srcDir

# Se repite cada 5 min, para siempre, empezando al iniciar sesión. El
# intervalo corto es barato (esta_pendiente() descarta sin conectarse a
# IMAP a cualquier cuenta a la que todavía no le toque) y permite que
# una frecuencia configurada como "cada 5 minutos" se respete de verdad.
$trigger  = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration ([TimeSpan]::MaxValue)
$trigger.Delay = "PT1M"  # 1 min de margen tras iniciar sesión

$loginTrigger = New-ScheduledTaskTrigger -AtLogOn
$loginTrigger.Delay = "PT1M"

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
              -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
              -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName "FinanzasLeerCorreo" -Action $action -Trigger @($trigger, $loginTrigger) -Settings $settings `
  -Description "Lee notificaciones bancarias del correo (IMAP) para cada cuenta configurada desde la interfaz y las inserta en finanzas.db, respetando la frecuencia que cada quien eligio. Ver src/leer_correo.py y data/leer_correo.log." `
  -Force

Write-Host ""
Write-Host "Listo. Tarea creada:" -ForegroundColor Green
Get-ScheduledTask -TaskName "FinanzasLeerCorreo" | Select-Object TaskName, State

Write-Host ""
Write-Host "Para forzar una corrida ya mismo (util para probar):" -ForegroundColor Yellow
Write-Host "  Start-ScheduledTask -TaskName FinanzasLeerCorreo"
Write-Host "Para ver el resultado de esa corrida:" -ForegroundColor Yellow
Write-Host "  Get-Content 'C:\Finanzas personales\data\leer_correo.log' -Tail 10"
