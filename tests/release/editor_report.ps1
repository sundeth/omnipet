<#
Runs the Module Editor's own load + report on every release module, headless.

Checklist MOD-08: "no errors on the Module Editor (loading and the report
function)". Loads the built editor assembly, deserialises each module file into
the editor's models exactly as its tabs do, then calls
ModuleReportGenerator.Generate() - the Report button without the dialog (and
without the SaveAll() that button does first, so nothing is written).

    powershell -NoProfile -ExecutionPolicy Bypass -File tests/release/editor_report.ps1 [-Modules DMC,IC] [-OutDir path] [-Exe path]

Writes <OutDir>/<MODULE>.txt (the report) and <OutDir>/editor_report.json
({module, load_errors[], errors, warnings, infos, error_lines[]}). Exit 1 when
any module has a load error or an [Error] line.
#>
param(
    [string[]]$Modules = @("D-3","DM20","DMC","DMGZ","DMH","DMM","DMOG","DMRV","DMX","DMXW",
                           "DW1","IC","PEN20","PENC","PENGZ","PENOG","PENZ","VB","VBE","VH"),
    [string]$OutDir = "",
    [string]$Exe = "E:\Omnipet Module Editor\OmnipetModuleEditor\bin\Release\OmnipetModuleEditor.exe",
    [string]$ModulesRoot = ""
)
$ErrorActionPreference = "Stop"
# -File passes "DMC,IC" as one string
$Modules = @($Modules | ForEach-Object { $_ -split "," } | Where-Object { $_ })
$root =(Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $ModulesRoot) { $ModulesRoot = Join-Path $root "modules" }
if (-not $OutDir) { $OutDir = Join-Path $root "tmp\release-reports\editor" }
New-Item -ItemType Directory -Force $OutDir | Out-Null
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
$stj = [System.Reflection.Assembly]::LoadFrom((Join-Path $bin "System.Text.Json.dll"))

$moduleType = $asm.GetType("OmnipetModuleEditor.Models.Module")
$reportType = $asm.GetType("OmnipetModuleEditor.Reports.ModuleReportGenerator")
$serializer = $stj.GetType("System.Text.Json.JsonSerializer")
$docType = $stj.GetType("System.Text.Json.JsonDocument")

# JsonSerializer.Deserialize(string, Type, JsonSerializerOptions)
$deserialize = $serializer.GetMethods() | Where-Object {
    $_.Name -eq "Deserialize" -and -not $_.IsGenericMethod -and
    ($_.GetParameters() | ForEach-Object { $_.ParameterType.Name }) -join "," -eq "String,Type,JsonSerializerOptions"
} | Select-Object -First 1

function Read-As([string]$path, [System.Type]$type) {
    $json = [IO.File]::ReadAllText($path)
    return $deserialize.Invoke($null, @($json, $type, $null))
}

# The model each file's list deserialises into, as the tabs load them.
$fileModels = @(
    @{ file = "monster.json";  root = "monster";  type = "OmnipetModuleEditor.Models.Pet" },
    @{ file = "battle.json";   root = "enemies";  type = "BattleEnemy" },
    @{ file = "item.json";     root = "item";     type = "OmnipetModuleEditor.Models.Item" },
    @{ file = "quests.json";   root = "quests";   type = "OmnipetModuleEditor.Models.Quest" },
    @{ file = "events.json";   root = "events";   type = "OmnipetModuleEditor.Models.Event" },
    @{ file = "devices.json";  root = "devices";  type = "OmnipetModuleEditor.Models.DeviceDefinition" },
    @{ file = "shop.json";     root = "currency"; type = "OmnipetModuleEditor.Models.Currency" },
    @{ file = "shop.json";     root = "shop";     type = "OmnipetModuleEditor.Models.Shop" }
)
$listType = [System.Collections.Generic.List``1]
$validUnlockTypes = @("egg","adventure","evolution","digidex","battle","group","pvp","versus","encounter")

$summary = @()
foreach ($m in $Modules) {
    $dir = Join-Path $ModulesRoot $m
    $loadErrors = @()
    $module = $null
    try {
        $module = Read-As (Join-Path $dir "module.json") $moduleType
        if ($module -eq $null) { $loadErrors += "module.json deserialised to null" }
    } catch {
        $loadErrors += "module.json: " + $_.Exception.GetBaseException().Message
    }
    foreach ($fm in $fileModels) {
        $path = Join-Path $dir $fm.file
        if (-not (Test-Path $path)) { continue }
        try {
            $t = $asm.GetType($fm.type)
            if ($t -eq $null) { $loadErrors += "model $($fm.type) not found in the editor build"; continue }
            $doc = $docType.GetMethod("Parse", [type[]]@([string], $stj.GetType("System.Text.Json.JsonDocumentOptions"))).Invoke($null, @([IO.File]::ReadAllText($path), $null))
            $el = $null
            $rootEl = $doc.RootElement
            $prop = New-Object System.Text.Json.JsonElement
            if ($rootEl.TryGetProperty($fm.root, [ref]$prop)) {
                $lt = $listType.MakeGenericType($t)
                [void]$deserialize.Invoke($null, @($prop.GetRawText(), $lt, $null))
            }
            $doc.Dispose()
        } catch {
            $loadErrors += "$($fm.file)/$($fm.root): " + $_.Exception.GetBaseException().Message
        }
    }
    # The Module tab's unlock type combo throws on anything outside its list.
    if ($module -ne $null -and $module.Unlocks -ne $null) {
        foreach ($u in $module.Unlocks) {
            if ($validUnlockTypes -notcontains $u.Type) {
                $loadErrors += "unlock '$($u.Name)': type '$($u.Type)' is not in the editor's unlock combo"
            }
        }
    }
    $report = ""
    if ($module -ne $null) {
        try {
            $ctor = $reportType.GetConstructor([type[]]@([string], $moduleType))
            $gen = $ctor.Invoke([object[]]@([string]$dir, $module.PSObject.BaseObject))
            $report = $gen.Generate()
        } catch {
            $loadErrors += "report: " + $_.Exception.GetBaseException().Message
        }
    }
    [IO.File]::WriteAllText((Join-Path $OutDir "$m.txt"), $report, (New-Object System.Text.UTF8Encoding($false)))
    $lines = $report -split "`r?`n"
    $errLines = @($lines | Where-Object { $_ -match '^\[Error\]' })
    $warnLines = @($lines | Where-Object { $_ -match '^\[Warning\]' })
    $infoLines = @($lines | Where-Object { $_ -match '^\[Info\]' })
    $count = { param($ls) ($ls | ForEach-Object { if ($_ -match '^\[\w+\]\s+(\d+)\s') { [int]$matches[1] } else { 1 } } | Measure-Object -Sum).Sum }
    $row = [ordered]@{
        module = $m
        load_errors = $loadErrors
        errors = [int](& $count $errLines)
        warnings = [int](& $count $warnLines)
        infos = [int](& $count $infoLines)
        error_lines = $errLines
        warning_lines = $warnLines
    }
    $summary += New-Object PSObject -Property $row
    "{0,-6} load errors {1,2}  report: {2,4} errors {3,5} warnings {4,5} info" -f $m, $loadErrors.Count, $row.errors, $row.warnings, $row.infos
    foreach ($l in $loadErrors) { "         LOAD $l" }
    foreach ($l in $errLines) { "         $l" }
}
$summary | ConvertTo-Json -Depth 5 | Out-File -Encoding utf8 (Join-Path $OutDir "editor_report.json")
$bad = @($summary | Where-Object { $_.load_errors.Count -gt 0 -or $_.errors -gt 0 }).Count
"`n$($summary.Count) modules, $bad with load or report errors. Reports in $OutDir"
if ($bad -gt 0) { exit 1 } else { exit 0 }
