# Run in an Administrator PowerShell after quitting Docker Desktop.
# Compact only Docker's existing dynamic VHD; retain its images and volumes.
$ErrorActionPreference = 'Stop'
$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = [Security.Principal.WindowsPrincipal]::new($Identity)
if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Windows requires an Administrator PowerShell to compact this VHD.'
}
$Disk = Join-Path $env:LOCALAPPDATA 'Docker\wsl\disk\docker_data.vhdx'
if (-not (Test-Path -LiteralPath $Disk -PathType Leaf)) {
    throw 'Expected Docker data VHD was not found; no other disk will be selected.'
}
if (Get-Process -Name 'com.docker.backend','Docker Desktop' -ErrorAction SilentlyContinue) {
    throw 'Quit Docker Desktop and rerun this script. Running Docker prevents safe compaction.'
}
# Fail if another process still owns the VHD. Do not terminate any WSL distro.
$Handle = [IO.File]::Open($Disk, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
$Handle.Dispose()
$Before = (Get-Item -LiteralPath $Disk).Length
$Drive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($Disk))
$FreeBefore = $Drive.AvailableFreeSpace
$CommandFile = Join-Path $env:TEMP ('cc-contract-compact-' + [guid]::NewGuid() + '.txt')
try {
    $Commands = @(('select vdisk file="' + $Disk + '"'), 'compact vdisk', 'exit')
    $Encoding = [Text.Encoding]::Default
    $Text = ($Commands -join "`r`n") + "`r`n"
    $Bytes = $Encoding.GetBytes($Text)
    if ($Encoding.GetString($Bytes) -cne $Text) {
        throw 'The Windows text encoding cannot preserve this disk path; no compaction performed.'
    }
    # Diskpart receives plain Windows text, with CRLF and no UTF-16 BOM/NUL bytes.
    [IO.File]::WriteAllBytes($CommandFile, $Bytes)
    if ($Bytes -contains 0) { throw 'Unexpected NUL in Diskpart command file.' }
    Write-Output ('Compacting detached Docker disk: ' + $Disk)
    & "$env:WINDIR\System32\diskpart.exe" /s $CommandFile
    if ($LASTEXITCODE -ne 0) { throw 'Diskpart did not complete successfully.' }
} finally {
    Remove-Item -LiteralPath $CommandFile -ErrorAction SilentlyContinue
}
$After = (Get-Item -LiteralPath $Disk).Length
$FreeAfter = $Drive.AvailableFreeSpace
Write-Output ('Docker VHD: before {0:N2} GiB, after {1:N2} GiB, reduction {2:N2} GiB.' -f ($Before/1GB), ($After/1GB), (($Before-$After)/1GB))
Write-Output ('Windows free space: before {0:N2} GiB, after {1:N2} GiB.' -f ($FreeBefore/1GB), ($FreeAfter/1GB))
if ($After -ge $Before) {
    Write-Output 'No physical reduction observed. Keep the Diskpart output for diagnosis.'
}
