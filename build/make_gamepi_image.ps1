# Creates the releasable GamePi SD-card image:
#   dump SD card -> PiShrink (WSL) -> Release\Omnipet_GamePi_Ver_<Version> (Image).zip
#
# NOT part of the build_all workflow -- run manually with the master SD card
# inserted, from an *elevated* PowerShell (raw disk reads require admin):
#
#   .\build\make_gamepi_image.ps1 -Version "1.0"
#
# Options:
#   -Version <v>      Version string used in the file names (default "1.0").
#   -Image <path>     Skip the SD dump and use an existing .img instead.
#                     NOTE: the file is shrunk IN PLACE and consumed by the
#                     pipeline (moved/zipped); pass a copy if you want to keep it.
#   -DiskNumber <n>   Skip auto-detection and dump this disk number (must be USB).
#   -KeepImage        Keep the shrunk .img next to the zip instead of deleting it.
#
# Requirements: WSL2 (loop devices), python on PATH (raw disk dump), 7-Zip or
# WSL zip. pishrink.sh is downloaded into WSL automatically on first use.

param(
    [string]$Version = "1.0",
    [string]$Image = "",
    [int]$DiskNumber = -1,
    [switch]$KeepImage
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ReleaseDir = Join-Path $ProjectRoot "Release"
$StagingDir = Join-Path $ReleaseDir "staging"
$BuildName = "Omnipet_GamePi_Ver_$Version"
$FinalImg = Join-Path $StagingDir "$BuildName.img"
$FinalZip = Join-Path $ReleaseDir "$BuildName (Image).zip"
$SevenZip = "C:\Program Files\7-Zip\7z.exe"

function Write-Status($msg) { Write-Host "=== $msg ===" -ForegroundColor Cyan }

function Convert-ToWslPath([string]$winPath) {
    $resolved = (Resolve-Path $winPath).Path
    $drive = $resolved.Substring(0, 1).ToLower()
    "/mnt/$drive" + $resolved.Substring(2).Replace("\", "/")
}

New-Item -ItemType Directory -Force -Path $ReleaseDir, $StagingDir | Out-Null

# ---------------------------------------------------------------------------
# [1/4] Obtain the raw image (dump the SD card, or take the -Image file)
# ---------------------------------------------------------------------------
if ($Image) {
    if (-not (Test-Path $Image)) { throw "Image file not found: $Image" }
    Write-Status "[1/4] Using existing image: $Image (will be shrunk in place)"
    $WorkImg = (Resolve-Path $Image).Path
} else {
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
        ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        throw "Dumping the SD card reads the raw disk and requires an elevated PowerShell. Re-run as Administrator (or pass -Image <path> to skip the dump)."
    }

    # Locate the SD card: USB-attached disks only, as a safety rail.
    $usbDisks = @(Get-Disk | Where-Object { $_.BusType -eq 'USB' })
    if ($DiskNumber -ge 0) {
        $disk = Get-Disk -Number $DiskNumber
        if ($disk.BusType -ne 'USB') { throw "Disk $DiskNumber is not USB-attached ($($disk.BusType)). Refusing to dump a non-USB disk." }
    } elseif ($usbDisks.Count -eq 1) {
        $disk = $usbDisks[0]
    } elseif ($usbDisks.Count -eq 0) {
        throw "No USB-attached disk found. Insert the SD card (via a USB reader) and try again."
    } else {
        Write-Host "Multiple USB disks found:" -ForegroundColor Yellow
        $usbDisks | Format-Table Number, FriendlyName, @{n='SizeGB';e={[math]::Round($_.Size/1GB,1)}} -AutoSize | Out-Host
        $num = Read-Host "Enter the disk number to dump"
        $disk = Get-Disk -Number ([int]$num)
        if ($disk.BusType -ne 'USB') { throw "Disk $num is not USB-attached. Aborting." }
    }

    $sizeGB = [math]::Round($disk.Size / 1GB, 1)
    Write-Status "[1/4] SD card: Disk $($disk.Number) '$($disk.FriendlyName)' $sizeGB GB (USB)"
    $confirm = Read-Host "Dump this disk? [y/N]"
    if ($confirm -ne 'y') { Write-Host "Aborted."; exit 1 }

    # Raw-read \\.\PhysicalDriveN with python (sector-aligned unbuffered reads).
    $WorkImg = Join-Path $StagingDir "gamepi_dump.img"
    if (Test-Path $WorkImg) { Remove-Item $WorkImg -Force }
    $dumpPy = Join-Path $env:TEMP "omnipet_sd_dump.py"
    @'
import sys, time
disk_number, total, out_path = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
CHUNK = 4 * 1024 * 1024
start = time.time()
done = 0
with open(rf"\\.\PhysicalDrive{disk_number}", "rb", buffering=0) as src, \
     open(out_path, "wb") as dst:
    while done < total:
        want = min(CHUNK, total - done)
        data = src.read(want)
        if not data:
            break
        dst.write(data)
        done += len(data)
        if done % (512 * 1024 * 1024) < CHUNK:
            mb_s = done / 1048576 / max(time.time() - start, 0.001)
            print(f"  {done/1073741824:.1f} / {total/1073741824:.1f} GB ({mb_s:.0f} MB/s)", flush=True)
    dst.flush()
if done < total:
    print(f"ERROR: short read at {done} of {total} bytes", flush=True)
    sys.exit(1)
print(f"Dump complete: {done/1073741824:.1f} GB in {time.time()-start:.0f}s", flush=True)
'@ | Set-Content -Path $dumpPy -Encoding ascii

    Write-Host "Dumping \\.\PhysicalDrive$($disk.Number) -> $WorkImg"
    python $dumpPy $disk.Number $disk.Size $WorkImg
    if ($LASTEXITCODE -ne 0) { throw "SD dump failed (exit $LASTEXITCODE)." }
    Remove-Item $dumpPy -Force -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------------------
# [2/4] Ensure PiShrink is available inside WSL
# ---------------------------------------------------------------------------
Write-Status "[2/4] Preparing PiShrink (WSL)"
wsl -u root bash -c "test -x /usr/local/bin/pishrink.sh || (curl -fsSL https://raw.githubusercontent.com/Drewsif/PiShrink/master/pishrink.sh -o /usr/local/bin/pishrink.sh && chmod +x /usr/local/bin/pishrink.sh)"
if ($LASTEXITCODE -ne 0) { throw "Could not install pishrink.sh into WSL (internet required on first run)." }

# ---------------------------------------------------------------------------
# [3/4] Shrink the image (in place). PiShrink also re-enables the
# expand-on-first-boot behavior, so any card size works for end users.
# ---------------------------------------------------------------------------
Write-Status "[3/4] Shrinking image with PiShrink"
$wslImg = Convert-ToWslPath $WorkImg
wsl -u root bash -c "pishrink.sh '$wslImg'"
if ($LASTEXITCODE -ne 0) {
    # losetup on /mnt/<drive> (drvfs) can fail on some WSL builds; retry from
    # the ext4 filesystem inside the WSL VM.
    Write-Host "PiShrink failed on the Windows filesystem; retrying inside WSL ext4 (slower)..." -ForegroundColor Yellow
    wsl -u root bash -c "cp '$wslImg' /tmp/gamepi_shrink.img && pishrink.sh /tmp/gamepi_shrink.img && cp /tmp/gamepi_shrink.img '$wslImg'; rc=`$?; rm -f /tmp/gamepi_shrink.img; exit `$rc"
    if ($LASTEXITCODE -ne 0) { throw "PiShrink failed (exit $LASTEXITCODE)." }
}

# ---------------------------------------------------------------------------
# [4/4] Rename + zip
# ---------------------------------------------------------------------------
Write-Status "[4/4] Creating release zip"
if (Test-Path $FinalImg) { Remove-Item $FinalImg -Force }
Move-Item $WorkImg $FinalImg
if (Test-Path $FinalZip) { Remove-Item $FinalZip -Force }

if (Test-Path $SevenZip) {
    & $SevenZip a -tzip -mx=9 "$FinalZip" "$FinalImg"
    if ($LASTEXITCODE -ne 0) { throw "7-Zip failed (exit $LASTEXITCODE)." }
} else {
    # Fallback: zip from WSL (zip64-capable, unlike Compress-Archive on PS 5.1)
    $wslReleaseDir = Convert-ToWslPath $ReleaseDir
    $wslFinalImg = Convert-ToWslPath $FinalImg
    wsl bash -c "zip -9 -j '$wslReleaseDir/$BuildName (Image).zip' '$wslFinalImg'"
    if ($LASTEXITCODE -ne 0) { throw "zip failed (exit $LASTEXITCODE)." }
}

if (-not $KeepImage) {
    Remove-Item $FinalImg -Force
    Write-Host "Intermediate image deleted (use -KeepImage to keep it)."
} else {
    Write-Host "Shrunk image kept at: $FinalImg"
}

$zipSize = [math]::Round((Get-Item $FinalZip).Length / 1GB, 2)
Write-Status "Done: $FinalZip ($zipSize GB)"
