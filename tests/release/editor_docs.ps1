<#
Regenerates each release module's documentation with the Module Editor, headless.

Checklist DOC-01: "module documentation regenerated from the editor after the
module fixes". Loads the built editor assembly and calls what the Generate
Documentation button calls (HTMLGenerator.GenerateDocumentation, then
DeviceGenerator.GenerateDevicesPage), without the dialogs.

This WRITES modules/<MODULE>/documentation/. Each existing documentation folder
is first copied to <BackupRoot>/<MODULE>_<yyyyMMdd_HHmmss>/ (dated, never
overwritten; utilities/ is not shipped).

    powershell -NoProfile -ExecutionPolicy Bypass -File tests/release/editor_docs.ps1 [-Modules DMC,IC] [-Exe path]

Exit 1 when any module fails to generate.
#>
param(
    [string[]]$Modules = @("D-3","DM20","DMC","DMGZ","DMH","DMM","DMOG","DMRV","DMX","DMXW",
                           "DW1","IC","PEN20","PENC","PENGZ","PENOG","PENZ","VB","VBE","VH"),
    [string]$Exe = "E:\Omnipet Module Editor\OmnipetModuleEditor\bin\Release\OmnipetModuleEditor.exe",
    [string]$ModulesRoot = "",
    [string]$BackupRoot = ""
)
$ErrorActionPreference = "Stop"
# -File passes "DMC,IC" as one string
$Modules = @($Modules | ForEach-Object { $_ -split "," } | Where-Object { $_ })
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $ModulesRoot) { $ModulesRoot = Join-Path $root "modules" }
if (-not $BackupRoot) { $BackupRoot = Join-Path $root "utilities\claude\backups\documentation" }
if (-not (Test-Path $Exe)) { Write-Error "Editor build not found: $Exe (build it with MSBuild first)" }

# The .exe.config binding redirects do not apply inside PowerShell: resolve
# every dependency from the editor's own bin folder, whatever version is asked.
$bin = Split-Path $Exe
$handler = [System.ResolveEventHandler]{
    param($s, $e)
    $name = (New-Object System.Reflection.AssemblyName($e.Name)).Name
    $path = Join-Path $bin "$name.dll"
    if (Test-Path $path) { return [System.Reflection.Assembly]::LoadFrom($path) }
    return $null
}
[System.AppDomain]::CurrentDomain.add_AssemblyResolve($handler)
$asm = [System.Reflection.Assembly]::LoadFrom($Exe)

$static = [System.Reflection.BindingFlags]"Public, NonPublic, Static"
$htmlType = $asm.GetType("OmnipetModuleEditor.controls.HTMLGenerator")
$deviceType = $asm.GetType("OmnipetModuleEditor.docgenerators.DeviceGenerator")
if ($htmlType -eq $null -or $deviceType -eq $null) { Write-Error "Generators not found in the editor build" }
$generate = $htmlType.GetMethod("GenerateDocumentation", $static, $null, [type[]]@([string]), $null)
$devices = $deviceType.GetMethod("GenerateDevicesPage", $static, $null, [type[]]@([string], [string]), $null)

# The generators read and write relative to the working directory in places.
$failed = 0
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
foreach ($m in $Modules) {
    $dir = Join-Path $ModulesRoot $m
    $docDir = Join-Path $dir "documentation"
    if (-not (Test-Path (Join-Path $dir "module.json"))) { "{0,-6} no module.json" -f $m; $failed++; continue }
    if (Test-Path $docDir) {
        $dest = Join-Path $BackupRoot "${m}_$stamp"
        if (Test-Path $dest) { "{0,-6} backup {1} exists" -f $m, $dest; $failed++; continue }
        New-Item -ItemType Directory -Force (Split-Path $dest) | Out-Null
        Copy-Item -Recurse $docDir $dest
    }
    $prev = [Environment]::CurrentDirectory
    try {
        [Environment]::CurrentDirectory = $dir
        [void]$generate.Invoke($null, @([string]$dir))
        [void]$devices.Invoke($null, @([string]$docDir, [string]$dir))
        $pages = @(Get-ChildItem -Recurse -File $docDir -Filter *.html).Count
        "{0,-6} ok, {1} pages" -f $m, $pages
    } catch {
        "{0,-6} FAILED: {1}" -f $m, $_.Exception.GetBaseException().Message
        $failed++
    } finally {
        [Environment]::CurrentDirectory = $prev
    }
}
if ($failed) { exit 1 }
