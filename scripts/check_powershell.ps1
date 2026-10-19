# Syntax validation only; does not execute Windows host commands.
$ErrorActionPreference = 'Stop'
foreach ($file in Get-ChildItem (Join-Path $PSScriptRoot 'windows') -Filter '*.ps1') {
    $parseTokens = $null
    $parseErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$parseTokens, [ref]$parseErrors) | Out-Null
    if ($parseErrors.Count -gt 0) {
        $parseErrors | ForEach-Object { Write-Error $_.Message }
        exit 1
    }
    Write-Host "PASS PowerShell syntax: $($file.Name)"
}
