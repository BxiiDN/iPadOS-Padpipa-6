<#
SPDX-License-Identifier: MIT

iPadOS-Padpipa-6: Windows 11 entry point. Builds run in WSL2 (scripts/wsl/build.sh); adb and fastboot run on Windows
(Android SDK Platform-Tools), so no USB passthrough into WSL is needed.

  .\scripts\windows\pipa.ps1 doctor                  check WSL2, the distribution, adb/fastboot, Python
  .\scripts\windows\pipa.ps1 setup                   one time: packages + UniXNU's Linux toolchain inside WSL2 (hours)
  .\scripts\windows\pipa.ps1 collect                 READ-ONLY: this tablet's memory banks, GPT, panel -> unit-facts.json
  .\scripts\windows\pipa.ps1 firmware                READ-ONLY: copy firmware from the tablet into .cache\firmware, print SHA-256
  .\scripts\windows\pipa.ps1 backup                  READ-ONLY: pull /sdcard and record `fastboot getvar all` before any write
  .\scripts\windows\pipa.ps1 build <step>            bootstrap | board | firmware | stage1 | kernel | payload | check | all
  .\scripts\windows\pipa.ps1 boot <image>            TEMPORARY: validate, then `fastboot boot` (writes nothing to the tablet)
  .\scripts\windows\pipa.ps1 log [-Reader img]       fetch the ramoops log through UniXNU-pipa's log reader (PIPALOG disk)
  .\scripts\windows\pipa.ps1 flash-userdata <img> -IUnderstandDataLoss
                                                     PERMANENT: erases Android's userdata. Gated, typed confirmation.

Never used by this script: fastboot flash boot/vendor_boot/dtbo/vbmeta/persist/modem/bluetooth/dsp, erase, oem, flashing
lock/unlock. Bootloader, calibration (persist) and the other slot stay untouched.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)] [string] $Command = "help",
    [Parameter(Position = 1)] [string] $Arg,
    [string] $Distro = "Ubuntu-24.04",
    [string] $Unit = "pipa-8g256",
    [string] $Serial = $env:PIPA_SERIAL,
    [string] $Reader,
    [switch] $IUnderstandDataLoss
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$UnitDir = Join-Path $Root "device\$Unit"
$Logs = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $Logs | Out-Null
$Stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")

function Fail([string] $msg, [int] $code = 1) { Write-Host "FAIL  $msg" -ForegroundColor Red; exit $code }
function Info([string] $msg) { Write-Host "==  $msg" -ForegroundColor Cyan }

function Find-Tool([string] $name) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($dir in @("$env:LOCALAPPDATA\Android\Sdk\platform-tools", "C:\platform-tools", "$Root\.tools\platform-tools")) {
        $p = Join-Path $dir "$name.exe"
        if (Test-Path $p) { return $p }
    }
    return $null
}
$Adb = Find-Tool "adb"
$Fastboot = Find-Tool "fastboot"

function WslPath([string] $winPath) {
    $p = (& wsl.exe -d $Distro -- wslpath -a ($winPath -replace '\\', '/')) 2>$null
    if (-not $p) { Fail "wslpath failed for $winPath (is the $Distro distribution installed?)" }
    return $p.Trim()
}
function Invoke-Wsl([string] $bashCommand) {
    $wroot = WslPath $Root
    & wsl.exe -d $Distro --cd $wroot -- bash -lc $bashCommand
    if ($LASTEXITCODE -ne 0) { Fail "WSL command failed ($LASTEXITCODE): $bashCommand" $LASTEXITCODE }
}

function Fastboot-Args { if ($Serial) { @("-s", $Serial) } else { @() } }
# fastboot prints getvar results on stderr; Windows PowerShell 5.1 turns redirected stderr into errors under "Stop".
function Run-Native([string] $exe, [string[]] $argv) {
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    try { $out = & $exe @argv 2>&1 | ForEach-Object { "$_" } } finally { $ErrorActionPreference = $old }
    return @($out)
}
function Require-Fastboot-Pipa {
    if (-not $Fastboot) { Fail "fastboot.exe not found: install Android SDK Platform-Tools" }
    $devs = @(& $Fastboot devices | Where-Object { $_ -match "\sfastboot$" })
    if ($Serial) { $devs = @($devs | Where-Object { $_ -like "$Serial*" }) }
    if ($devs.Count -ne 1) { Fail "expected exactly one tablet in fastboot, found $($devs.Count) (set -Serial)" }
    $product = (Run-Native $Fastboot (@(Fastboot-Args) + @("getvar", "product")) | Select-String "^product:" | Select-Object -First 1)
    $product = "$product"
    if ($product -notmatch "product:\s*pipa\s*$") { Fail "the device in fastboot is not a pipa ($product)" }
    return ($devs[0] -split "\s+")[0]
}
function Require-Adb-Pipa {
    if (-not $Adb) { Fail "adb.exe not found: install Android SDK Platform-Tools" }
    $state = (Run-Native $Adb @("get-state") | Select-Object -First 1)
    if ($state -ne "device") { Fail "no tablet in Android with USB debugging (adb get-state: $state)" }
    $product = (& $Adb shell getprop ro.product.device).Trim()
    if ($product -ne "pipa") { Fail "the connected device is '$product', not pipa" }
}

switch ($Command) {
    "doctor" {
        Info "Windows $([Environment]::OSVersion.Version)"
        $wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
        if (-not $wsl) { Fail "WSL is not installed: run 'wsl --install -d $Distro' as administrator, then reboot" }
        $distros = (& wsl.exe -l -q) -replace "`0", "" | Where-Object { $_ }
        if ($distros -notcontains $Distro) { Write-Host "MISSING  WSL distribution $Distro (wsl --install -d $Distro)" -ForegroundColor Yellow }
        else { Info "WSL distribution $Distro present"; Invoke-Wsl "python3 --version && git --version && (command -v clang || echo 'clang: run setup')" }
        Info ("adb: " + ($(if ($Adb) { $Adb } else { "MISSING (Android SDK Platform-Tools)" })))
        Info ("fastboot: " + ($(if ($Fastboot) { $Fastboot } else { "MISSING (Android SDK Platform-Tools)" })))
        if (Test-Path (Join-Path $UnitDir "unit-facts.json")) { Info "unit facts: $UnitDir\unit-facts.json" }
        else { Write-Host "MISSING  unit facts: run '.\scripts\windows\pipa.ps1 collect' with the tablet in Android" -ForegroundColor Yellow }
    }
    "setup" { Invoke-Wsl "scripts/wsl/build.sh setup" }
    "collect" {
        Require-Adb-Pipa
        $script = Join-Path $Root "scripts\device\collect-unit-facts.sh"
        $kv = Join-Path $UnitDir "collected-$Stamp.kv"
        # The collector is piped over stdin (LF line ends): nothing is copied to the tablet.
        $text = [IO.File]::ReadAllText($script).Replace("`r`n", "`n")
        $mode = if ((& $Adb shell "command -v su" 2>$null)) { Read-Host "su found. Run the collector as root for the DT memory banks? (y/N)" } else { "n" }
        $remote = if ($mode -eq "y") { "su -c 'sh -s'" } else { "sh -s" }
        $text | & $Adb shell $remote | Out-File -Encoding utf8 $kv
        Info "raw facts: $kv"
        Invoke-Wsl ("python3 tools/unitfacts.py from-adb '" + (WslPath $kv) + "' -o device/$Unit/unit-facts.json && python3 tools/unitfacts.py show device/$Unit/unit-facts.json | tail -2")
    }
    "firmware" {
        Require-Adb-Pipa
        $cache = Join-Path $Root "work\UniXNU-pipa\.cache\firmware"
        $items = @(
            @("/vendor/firmware/a650_gmu.bin", "gpu\a650_gmu.bin"), @("/vendor/firmware/a650_zap.elf", "gpu\a650_zap.elf"),
            @("/vendor/firmware/aw882xx_acf.bin", "audio\aw882xx_acf.bin"),
            @("/vendor/firmware/amss.bin", "wifi\amss.bin"), @("/vendor/firmware/m3.bin", "wifi\m3.bin"),
            @("/vendor/firmware/bdwlan.bin", "wifi\bdwlan.bin"))
        $report = @()
        foreach ($it in $items) {
            $dst = Join-Path $cache $it[1]
            New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
            $null = Run-Native $Adb @("pull", $it[0], $dst)
            if (Test-Path $dst) { $h = (Get-FileHash -Algorithm SHA256 $dst).Hash.ToLower(); $report += "$h  $($it[1])  <- $($it[0])" }
            else { $report += "MISSING  $($it[1])  <- $($it[0])" }
        }
        $fp = (& $Adb shell getprop ro.build.fingerprint).Trim()
        $out = Join-Path $Logs "firmware-$Stamp.txt"
        ($report + "fingerprint: $fp") | Out-File -Encoding utf8 $out
        $report | ForEach-Object { Write-Host $_ }
        Info "pin the digests in manifest\firmware.toml; touch firmware and linux-firmware a650_sqe.fw: see docs\HARDWARE.md"
    }
    "backup" {
        Require-Adb-Pipa
        $dst = Join-Path $Root "backup\$Stamp"
        New-Item -ItemType Directory -Force -Path $dst | Out-Null
        & $Adb shell getprop | Out-File -Encoding utf8 (Join-Path $dst "getprop.txt")
        Info "pulling /sdcard (photos, downloads, documents) to $dst\sdcard; app data needs the apps' own backup"
        & $Adb pull /sdcard (Join-Path $dst "sdcard")
        Info "now reboot to fastboot (adb reboot bootloader) and run: pipa.ps1 backup-fastboot"
    }
    "backup-fastboot" {
        $null = Require-Fastboot-Pipa
        $dst = Join-Path $Root "backup\$Stamp"
        New-Item -ItemType Directory -Force -Path $dst | Out-Null
        Run-Native $Fastboot (@(Fastboot-Args) + @("getvar", "all")) | Out-File -Encoding utf8 (Join-Path $dst "getvar-all.txt")
        Info "recorded $dst\getvar-all.txt (current slot, partition sizes, unlock state)"
    }
    "build" {
        if (-not $Arg) { Fail "build needs a step: bootstrap | board | firmware | stage1 | kernel | payload | check | all" }
        Invoke-Wsl "UNIT=$Unit scripts/wsl/build.sh $Arg"
    }
    "boot" {
        if (-not $Arg -or -not (Test-Path $Arg)) { Fail "boot needs an image path" }
        $img = (Resolve-Path $Arg).Path
        $stage1 = if ((Split-Path $img -Leaf) -like "*stage1*") { "--stage1" } else { "" }
        Invoke-Wsl ("python3 tools/checks/check_bootimg.py '" + (WslPath $img) + "' $stage1")
        $serial = Require-Fastboot-Pipa
        $hash = (Get-FileHash -Algorithm SHA256 $img).Hash.ToLower()
        Write-Host "Temporary boot of $img (sha256 $hash) on $serial. 'fastboot boot' writes nothing to the tablet;"
        Write-Host "if it hangs, hold Power + Volume Down for ~10 s to get back to fastboot."
        if ((Read-Host "Type BOOT to continue") -ne "BOOT") { Fail "cancelled" 0 }
        "$Stamp boot $img $hash $serial" | Out-File -Append -Encoding utf8 (Join-Path $Logs "device-rounds.log")
        & $Fastboot @(Fastboot-Args) boot $img
    }
    "log" {
        # UniXNU-pipa scripts/read-pipa-log.py does this on macOS (/Volumes/PIPALOG); here the disk gets a drive letter.
        if ($Reader) {
            $null = Require-Fastboot-Pipa
            Info "booting the log reader $Reader (temporary)"
            & $Fastboot @(Fastboot-Args) boot $Reader
        }
        Info "waiting up to 180 s for the PIPALOG disk"
        $vol = $null
        for ($i = 0; $i -lt 180 -and -not $vol; $i++) { $vol = Get-Volume -FileSystemLabel "PIPALOG" -ErrorAction SilentlyContinue; Start-Sleep 1 }
        if (-not $vol) { Fail "no PIPALOG volume appeared" }
        $src = "$($vol.DriveLetter):\"
        $status = Get-Content (Join-Path $src "STATUS.TXT") -Raw -ErrorAction SilentlyContinue
        if ($status -notmatch "pipa") { Fail "STATUS.TXT on $src is not the pipa reader's; left alone" }
        $dst = Join-Path $Logs "device\$Stamp"
        New-Item -ItemType Directory -Force -Path $dst | Out-Null
        Copy-Item (Join-Path $src "LOG.BIN"), (Join-Path $src "STATUS.TXT") $dst
        Info "copied to $dst; ejecting (the reader then restarts into fastboot)"
        (New-Object -ComObject Shell.Application).Namespace(17).ParseName("$($vol.DriveLetter):").InvokeVerb("Eject")
    }
    "flash-userdata" {
        if (-not $IUnderstandDataLoss) { Fail "flash-userdata ERASES Android's userdata. Re-run with -IUnderstandDataLoss after 'backup'." }
        if (-not $Arg -or -not (Test-Path $Arg)) { Fail "flash-userdata needs the userdata image path" }
        $facts = Join-Path $UnitDir "unit-facts.json"
        if (-not (Test-Path $facts)) { Fail "no measured unit facts ($facts): run collect first" }
        Invoke-Wsl ("python3 tools/flash_gate.py --unit $Unit --image '" + (WslPath (Resolve-Path $Arg).Path) + "'")
        $backups = Get-ChildItem (Join-Path $Root "backup") -Directory -ErrorAction SilentlyContinue
        if (-not $backups) { Fail "no backup\ folder: run 'pipa.ps1 backup' first" }
        $serial = Require-Fastboot-Pipa
        $size = "$(Run-Native $Fastboot (@(Fastboot-Args) + @("getvar", "partition-size:userdata")) | Select-String "partition-size" | Select-Object -First 1)"
        $img = (Resolve-Path $Arg).Path
        Write-Host "About to ERASE and write userdata on $serial ($size) with $img ($((Get-Item $img).Length) bytes)."
        Write-Host "Android's apps and data on this tablet are lost. Recovery: docs\RECOVERY.md (fastboot -w or the stock ROM)."
        $last4 = $serial.Substring([Math]::Max(0, $serial.Length - 4))
        $phrase = "HAPUS USERDATA $last4"
        if ((Read-Host "Type '$phrase' to continue") -ne $phrase) { Fail "cancelled" 0 }
        "$Stamp flash-userdata $img $serial" | Out-File -Append -Encoding utf8 (Join-Path $Logs "device-rounds.log")
        & $Fastboot @(Fastboot-Args) flash userdata $img
    }
    default { Get-Help $MyInvocation.MyCommand.Path -Detailed | Out-String | Write-Host; (Get-Content $PSCommandPath -TotalCount 22) -join "`n" | Write-Host }
}
