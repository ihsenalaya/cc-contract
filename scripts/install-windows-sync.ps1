param(
    [Parameter(Mandatory = $true)][string]$WorkspaceWsl,
    [string]$Distro = 'Ubuntu-22.04',
    [string]$LinuxUser = 'ihsen'
)
$ErrorActionPreference = 'Stop'
$TaskName = 'CCContractGitSync'
$TaskUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$TaskCommand = "-d `"$Distro`" -u `"$LinuxUser`" --exec /bin/bash `"$WorkspaceWsl/scripts/retry-sync.sh`""
$TaskAction = New-ScheduledTaskAction -Execute "$env:WINDIR\System32\wsl.exe" -Argument $TaskCommand
$TaskRetry = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$TaskLogon = New-ScheduledTaskTrigger -AtLogOn -User $TaskUser
$TaskPrincipal = New-ScheduledTaskPrincipal -UserId $TaskUser -LogonType Interactive -RunLevel Limited
$TaskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -MultipleInstances IgnoreNew
$ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($ExistingTask) {
    if ($ExistingTask.Actions.Arguments -ne $TaskCommand) {
        throw 'Existing task has different arguments; inspect before replacing it.'
    }
} else {
    Register-ScheduledTask -TaskName $TaskName -Action $TaskAction -Trigger @($TaskRetry, $TaskLogon) -Settings $TaskSettings -Principal $TaskPrincipal -Description 'Wake WSL and retry verified CC-Contract Git backup when the two-hour checkpoint is due.' | Out-Null
}
$TaskEvidence = Join-Path $PSScriptRoot '..\.local\sync\windows-task.xml'
Export-ScheduledTask -TaskName $TaskName | Out-File -Encoding utf8 $TaskEvidence
Start-ScheduledTask -TaskName $TaskName
Write-Output 'CCContractGitSync installed and started; retries every five minutes and at logon, backing up only when the two-hour checkpoint is due.'
