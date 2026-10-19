#requires -Version 5.1
[CmdletBinding(SupportsShouldProcess=$true, ConfirmImpact='High')]
param(
    [ValidateSet('dev-wsl2','server-linux-vm')][string]$Mode = 'server-linux-vm',
    [switch]$Apply,
    [switch]$PrepareWslFeatures
)
$ErrorActionPreference = 'Stop'
& "$PSScriptRoot/preflight.ps1"
Write-Host "Plan: $Mode. Keine Softwaredownloads, Firewallregeln, automatischen Neustarts oder Aenderungen bestehender Dienste."
if ($Mode -eq 'server-linux-vm') {
    Write-Host 'Ubuntu-VM nach docs/windows10-setup.md anlegen. VM-Software, Netzwerk und Autostart nach Hostpruefung manuell konfigurieren.'
    Write-Host 'In Linux: bash scripts/linux/bootstrap.sh --dry-run; danach --apply.'
    if ($PrepareWslFeatures) { throw 'PrepareWslFeatures ist nur fuer dev-wsl2 erlaubt.' }
    return
}
if (-not $Apply -or -not $PrepareWslFeatures) {
    Write-Host 'Dry-run. Optional: .\setup.ps1 -Mode dev-wsl2 -PrepareWslFeatures -Apply -Confirm'
    Write-Host 'Geplante Features: Microsoft-Windows-Subsystem-Linux, VirtualMachinePlatform. Neustart bleibt manuell.'
    return
}
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Fuer Feature-Aktivierung ist eine administrative PowerShell erforderlich.' }
if ($PSCmdlet.ShouldProcess('Windows host', 'WSL2-Voraussetzungen aktivieren (ohne Neustart)')) {
    $logRoot = Join-Path $env:LOCALAPPDATA 'DKMan\Logs'
    New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
    Start-Transcript -Path (Join-Path $logRoot (Get-Date -Format 'yyyyMMdd-HHmmss').ToString())
    try {
        foreach ($feature in @('Microsoft-Windows-Subsystem-Linux','VirtualMachinePlatform')) {
            if ((Get-WindowsOptionalFeature -Online -FeatureName $feature).State -ne 'Enabled') {
                Enable-WindowsOptionalFeature -Online -FeatureName $feature -All -NoRestart | Out-Null
            }
        }
        Write-Host 'Neustart bei Bedarf selbst ausfuehren. Danach WSL/Ubuntu gemaess Microsoft-Anleitung installieren. Rollback-Hinweise: docs/windows10-setup.md.'
    } finally { Stop-Transcript }
}
