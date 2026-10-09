param(
    [Parameter(Mandatory = $true)][string]$WorkspaceWsl,
    [string]$Distro = 'Ubuntu-22.04',
    [string]$LinuxUser = 'ihsen'
)
$ErrorActionPreference = 'Stop'
if ($Distro -notmatch '^[A-Za-z0-9_.-]+$' -or $LinuxUser -notmatch '^[A-Za-z0-9_.-]+$' -or $WorkspaceWsl -notmatch '^/[A-Za-z0-9_./-]+$') {
    throw 'Launcher arguments must not contain spaces or shell metacharacters.'
}
$TaskLog = Join-Path $PSScriptRoot '..\.local\sync\windows-task.log'
Add-Content -Encoding UTF8 $TaskLog "$(Get-Date -Format o) PowerShell backup trigger starting"
$TaskProcess = New-Object System.Diagnostics.Process
$TaskProcess.StartInfo.FileName = "$env:WINDIR\System32\wsl.exe"
$TaskProcess.StartInfo.Arguments = "-d $Distro -u $LinuxUser --exec /bin/bash $WorkspaceWsl/scripts/retry-sync.sh"
$TaskProcess.StartInfo.UseShellExecute = $false
$TaskProcess.StartInfo.CreateNoWindow = $true
$TaskProcess.StartInfo.RedirectStandardInput = $true
$TaskProcess.StartInfo.RedirectStandardOutput = $true
$TaskProcess.StartInfo.RedirectStandardError = $true
try {
    [void]$TaskProcess.Start()
    $TaskProcess.StandardInput.Close()
    $TaskOutput = $TaskProcess.StandardOutput.ReadToEndAsync()
    $TaskError = $TaskProcess.StandardError.ReadToEndAsync()
    $TaskProcess.WaitForExit()
    Add-Content -Encoding UTF8 $TaskLog $TaskOutput.Result
    Add-Content -Encoding UTF8 $TaskLog $TaskError.Result
    $TaskResult = $TaskProcess.ExitCode
    Add-Content -Encoding UTF8 $TaskLog "$(Get-Date -Format o) PowerShell backup trigger finished result=$TaskResult"
} finally {
    $TaskProcess.Dispose()
}
exit $TaskResult
