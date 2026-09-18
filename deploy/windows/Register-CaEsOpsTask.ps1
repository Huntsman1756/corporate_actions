# ca-es operational daily run — Windows Task Scheduler.
# Ejecutar como el usuario operativo (o SYSTEM si el state lo
# permite). Requiere ca-es en PATH o ajustar $CaEsExe.

param(
    [string]$StateDir = "C:\ca-es\state",
    [string]$ConfigPath = "C:\ca-es\ops.json",
    [string]$CaEsExe = "ca-es",
    [string]$TaskName = "ca-es-ops-daily",
    [string]$At = "06:30"
)

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument (
    "-NoProfile -Command " +
    "`"& '$CaEsExe' ops-run --state '$StateDir' " +
    "--config '$ConfigPath' --as-of (Get-Date -Format yyyy-MM-dd)`"")

$trigger = New-ScheduledTaskTrigger -Daily -At $At

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew
# IgnoreNew: si un run sigue activo, el nuevo no arranca (el
# runtime ademas rechaza un segundo writer con exit 3).

Register-ScheduledTask -TaskName $TaskName `
    -Action $action -Trigger $trigger -Settings $settings `
    -Description "ca-es operational daily run (P7)"

# Desregistrar:  Unregister-ScheduledTask -TaskName $TaskName
# Ejecutar ya:   Start-ScheduledTask -TaskName $TaskName
