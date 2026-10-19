#requires -Version 5.1
[CmdletBinding()]
param([switch]$Json)
$ErrorActionPreference = 'Stop'
function Try-Read([scriptblock]$Operation) {
    try { & $Operation } catch { 'unknown: ' + $_.Exception.GetType().Name }
}
$osInfo = Get-CimInstance Win32_OperatingSystem
$computerInfo = Get-CimInstance Win32_ComputerSystem
$cpuInfo = @(Get-CimInstance Win32_Processor | Select-Object Name, VirtualizationFirmwareEnabled, SecondLevelAddressTranslationExtensions, VMMonitorModeExtensions)
$hyperV = Try-Read { (Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All).State.ToString() }
$wslFeature = Try-Read { (Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux).State.ToString() }
$vmPlatform = Try-Read { (Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform).State.ToString() }
$docker = Try-Read {
    if (Get-Command docker -ErrorAction SilentlyContinue) {
        & docker version --format '{{.Client.Version}}'; & docker info --format '{{.OSType}}'
    } else { 'not installed' }
}
$wsl = Try-Read {
    if (Get-Command wsl -ErrorAction SilentlyContinue) { & wsl --list --verbose } else { 'not installed' }
}
$ports = Try-Read { @(Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -in @(8080,8000,5432,9000) } | Select-Object LocalAddress, LocalPort, OwningProcess) }
$report = [ordered]@{
    ReadOnly = $true
    Windows = [ordered]@{ Caption=$osInfo.Caption; Version=$osInfo.Version; Build=$osInfo.BuildNumber; Architecture=$osInfo.OSArchitecture }
    MemoryGiB = [math]::Round($computerInfo.TotalPhysicalMemory / 1GB, 1)
    HypervisorPresent = $computerInfo.HypervisorPresent
    CPUs = $cpuInfo
    HyperV = $hyperV
    WSLFeature = $wslFeature
    VirtualMachinePlatform = $vmPlatform
    WSL = $wsl
    Docker = $docker
    ListeningPorts = $ports
    Disks = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | Select-Object DeviceID, @{Name='FreeGiB';Expression={[math]::Round($_.FreeSpace/1GB,1)}})
    Network = Try-Read { @(Get-NetIPConfiguration | Select-Object InterfaceAlias, IPv4Address, IPv4DefaultGateway) }
    Firewall = Try-Read { @(Get-NetFirewallProfile | Select-Object Name, Enabled, DefaultInboundAction) }
    RunningServices = @(Get-Service | Where-Object Status -eq Running | Select-Object Name, DisplayName)
    Recommendation = 'Dauerbetrieb: Ubuntu-VM, 4 vCPU / 6 GB RAM / 40 GB Disk empfohlen; Hyper-V nur bei kompatibler Edition/Hardware. WSL2 nur Entwicklung. Keine Installation ausgefuehrt.'
    Notes = @('Windows 10 ist ausserhalb des regulaeren Supports; keine oeffentliche Freigabe.', 'Unbekannte Featurewerte ggf. mit administrativer PowerShell erneut nur pruefen.', 'Port 8080 muss frei sein. Bei VM gilt dies auch innerhalb der VM.', 'Autostart, Neustart und Netzwerkkonzept muessen am echten Host geprueft werden.')
}
if ($Json) { $report | ConvertTo-Json -Depth 7 } else { $report | ConvertTo-Json -Depth 7; Write-Host 'Preflight abgeschlossen. Keine Aenderungen vorgenommen.' }
