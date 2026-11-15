<#
SPDX-License-Identifier: MIT

iPadOS-Padpipa-6: Windows 11 entry point. Builds run in WSL2 (scripts/wsl/build.sh); adb and fastboot run on Windows.
Every device command targets ONE device: -Serial, or the only one connected; ambiguous, offline, unauthorized or
non-pipa devices are refused. Every external command's exit code is checked (PipaLib.psm1, Invoke-Native).

  .\scripts\windows\pipa.ps1 doctor
  .\scripts\windows\pipa.ps1 setup                      one time: packages + UniXNU's Linux Mach-O toolchain in WSL2
  .\scripts\windows\pipa.ps1 collect   [-Serial S]      READ-ONLY: memory banks, GPT, panel -> device\<unit>\unit-facts.json
  .\scripts\windows\pipa.ps1 firmware  [-Serial S]      READ-ONLY: firmware -> work\UniXNU-pipa\.cache\firmware + report
  .\scripts\windows\pipa.ps1 backup    [-Serial S]      READ-ONLY: /sdcard with manifest (sizes, SHA-256), verified
  .\scripts\windows\pipa.ps1 backup-fastboot [-Serial S] READ-ONLY: getvar all
  .\scripts\windows\pipa.ps1 build <step>               bootstrap | board | firmware | stage1 | kernel | payload | userdata | check | all
  .\scripts\windows\pipa.ps1 boot <image> [-Serial S]   validate, then `fastboot boot` (RAM only; prints what the image can write)
  .\scripts\windows\pipa.ps1 log [-Reader img] [-Serial S]
  .\scripts\windows\pipa.ps1 flash-userdata <img> -IUnderstandDataLoss [-Serial S]
                                                        PERMANENT, erases Android's userdata; every gate must pass

Never used: fastboot flash of any other partition, erase, oem, flashing lock/unlock, set_active.
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
Import-Module (Join-Path $PSScriptRoot "PipaLib.psm1") -Force
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$UnitDir = Join-Path $Root "device\$Unit"
$Logs = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $Logs, $UnitDir | Out-Null
$Stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
if ($Unit -notmatch '^[A-Za-z0-9._-]+$') { throw "unit name '$Unit' must be [A-Za-z0-9._-]" }

function Fail([string] $msg, [int] $code = 1) { Write-Host "FAIL  $msg" -ForegroundColor Red; exit $code }
function Info([string] $msg) { Write-Host "==  $msg" -ForegroundColor Cyan }

function Find-Tool([string] $name) {
    $cmd = Get-Command "$name.exe" -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($dir in @("$env:LOCALAPPDATA\Android\Sdk\platform-tools", "C:\platform-tools", (Join-Path $Root ".tools\platform-tools"))) {
        $p = Join-Path $dir "$name.exe"
        if (Test-Path -LiteralPath $p) { return $p }
    }
    return $null
}
$Adb = Find-Tool "adb"
$Fastboot = Find-Tool "fastboot"
function Need-Adb { if (-not $Adb) { Fail "adb.exe not found: install Android SDK Platform-Tools" } }
function Need-Fastboot { if (-not $Fastboot) { Fail "fastboot.exe not found: install Android SDK Platform-Tools" } }

function WslPath([string] $winPath) {
    $r = Invoke-Native -Exe "wsl.exe" -ArgumentList @("-d", $Distro, "--", "wslpath", "-a", $winPath)
    $p = ($r.Output -join "").Trim()
    if (-not $p.StartsWith("/")) { Fail "wslpath gave '$p' for $winPath" }
    return $p
}
function Invoke-Wsl([string] $bashScript) {
    # Arguments are embedded with ConvertTo-BashQuoted (single quotes). A double quote would be mangled by Windows
    # PowerShell 5.1's native argument passing, so it is refused instead of silently changing the command.
    if ($bashScript.Contains('"')) { throw "internal: WSL script must not contain double quotes: $bashScript" }
    $wroot = WslPath $Root
    & wsl.exe -d $Distro --cd $wroot -- bash -lc "set -euo pipefail; $bashScript"
    if ($LASTEXITCODE -ne 0) { Fail "WSL command failed (exit $LASTEXITCODE): $bashScript" $LASTEXITCODE }
}
function Q([string] $s) { ConvertTo-BashQuoted $s }
function Load-Facts {
    $f = Join-Path $UnitDir "unit-facts.json"
    if (-not (Test-Path -LiteralPath $f)) { Fail "no unit facts ($f): run 'pipa.ps1 collect' with the tablet in Android" }
    return (Get-Content -LiteralPath $f -Raw -Encoding UTF8 | ConvertFrom-Json)
}
function Round-Log([string] $line) {
    Add-Content -LiteralPath (Join-Path $Logs "device-rounds.log") -Value "$Stamp $line" -Encoding UTF8
}

try {
switch ($Command) {
    "doctor" {
        Info "Windows $([Environment]::OSVersion.Version), PowerShell $($PSVersionTable.PSVersion)"
        if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { Fail "WSL is not installed: 'wsl --install -d $Distro' as administrator, reboot" }
        $distros = (Invoke-Native -Exe "wsl.exe" -ArgumentList @("-l", "-q") -AllowFail).Output | ForEach-Object { ($_ -replace "`0", "").Trim() } | Where-Object { $_ }
        if (@($distros) -notcontains $Distro) { Fail "WSL distribution $Distro missing: wsl --install -d $Distro" }
        Invoke-Wsl "python3 --version; git --version; command -v clang || echo 'clang: run pipa.ps1 setup'"
        if ($Root.Contains(" ")) { Info "repository path has spaces: $Root (supported)" }
        Info ("adb: " + $(if ($Adb) { $Adb } else { "MISSING" })); Info ("fastboot: " + $(if ($Fastboot) { $Fastboot } else { "MISSING" }))
        if ($Adb) { (Get-DeviceList -Exe $Adb -Kind adb) | ForEach-Object { Info "adb device $($_.Serial): $($_.State)" } }
        if ($Fastboot) { (Get-DeviceList -Exe $Fastboot -Kind fastboot) | ForEach-Object { Info "fastboot device $($_.Serial): $($_.State)" } }
    }
    "setup" { Invoke-Wsl "scripts/wsl/build.sh setup" }
    "collect" {
        Need-Adb
        $s = Connect-PipaAdb -Adb $Adb -Serial $Serial
        Info "collecting from $s (read-only; the script is piped over stdin, nothing is copied to the tablet)"
        $text = [IO.File]::ReadAllText((Join-Path $Root "scripts\device\collect-unit-facts.sh")).Replace("`r`n", "`n")
        $hasSu = (Invoke-Adb -Adb $Adb -Serial $s -ArgumentList @("shell", "command -v su") -AllowFail).ExitCode -eq 0
        $remote = "sh -s"
        if ($hasSu -and (Read-Host "su found. Run the collector as root to read the DT memory banks? (y/N)") -eq "y") { $remote = "su -c 'sh -s'" }
        $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        $out = @($text | & $Adb -s $s shell $remote 2>&1 | ForEach-Object { "$_" }); $rc = $LASTEXITCODE
        $ErrorActionPreference = $old
        if ($rc -ne 0) { Fail "collector failed on $s (adb exit $rc): $($out | Select-Object -Last 2)" }
        if (-not ($out -match '^collector_version=') -or -not ($out -match '^errors=')) { Fail "collector output incomplete (device disconnected?)" }
        $out += "adb_serial_sha256=$(Get-StringSha256 $s)"
        $kv = Join-Path $UnitDir "collected-$Stamp.kv"
        Write-Utf8NoBom -Path $kv -Text (($out -join "`n") + "`n")
        Info "raw facts: $kv"
        Invoke-Wsl ("python3 tools/unitfacts.py from-adb $(Q (WslPath $kv)) -o $(Q "device/$Unit/unit-facts.json") && python3 tools/unitfacts.py show $(Q "device/$Unit/unit-facts.json") | tail -n 2")
    }
    "firmware" {
        Need-Adb
        $s = Connect-PipaAdb -Adb $Adb -Serial $Serial
        $cache = Join-Path $Root "work\UniXNU-pipa\.cache\firmware"
        $items = @(
            @("/vendor/firmware/a650_gmu.bin", "gpu\a650_gmu.bin", $true), @("/vendor/firmware/a650_zap.elf", "gpu\a650_zap.elf", $true),
            @("/vendor/firmware/aw882xx_acf.bin", "audio\aw882xx_acf.bin", $false),
            @("/vendor/firmware/amss.bin", "wifi\amss.bin", $false), @("/vendor/firmware/m3.bin", "wifi\m3.bin", $false),
            @("/vendor/firmware/bdwlan.bin", "wifi\bdwlan.bin", $false))
        $records = @(); $missingRequired = @()
        foreach ($it in $items) {
            $r = Save-DeviceFile -Adb $Adb -Serial $s -Remote $it[0] -Destination (Join-Path $cache $it[1])
            $records += $r
            Write-Host ("{0,-8} {1}  {2}" -f $r.State, $(if ($r.Sha256) { $r.Sha256 } else { $r.Detail }), $it[1])
            if ($r.State -ne "ok" -and $it[2]) { $missingRequired += $it[1] }
        }
        $fp = ((Invoke-Adb -Adb $Adb -Serial $s -ArgumentList @("shell", "getprop", "ro.build.fingerprint")).Output -join "").Trim()
        $report = [ordered]@{ created_utc = (Get-Date).ToUniversalTime().ToString("o"); serial_sha256 = (Get-StringSha256 $s); fingerprint = $fp; files = $records }
        Write-Utf8NoBom -Path (Join-Path $Logs "firmware-$Stamp.json") -Text ($report | ConvertTo-Json -Depth 5)
        if ($missingRequired) { Fail "required firmware not copied: $($missingRequired -join ', ') (try a root shell; stale copies were moved to *.stale)" }
        Info "pin the digests in manifest\firmware.toml; the touch image and linux-firmware a650_sqe.fw: docs\WINDOWS.md"
    }
    "backup" {
        Need-Adb
        $s = Connect-PipaAdb -Adb $Adb -Serial $Serial
        $dst = Join-Path $Root "backup\$Stamp"
        New-Item -ItemType Directory -Force -Path $dst | Out-Null
        $count = ((Invoke-Adb -Adb $Adb -Serial $s -ArgumentList @("shell", "find /sdcard/ -type f 2>/dev/null | wc -l")).Output -join "").Trim()
        $kib = ((Invoke-Adb -Adb $Adb -Serial $s -ArgumentList @("shell", "du -sk /sdcard/ 2>/dev/null | cut -f1")).Output -join "").Trim()
        if ($count -notmatch '^\d+$') { Fail "could not count files on the tablet ('$count')" }
        Info "tablet reports $count files, $kib KiB under /sdcard; pulling to $dst\sdcard"
        $pull = Invoke-Adb -Adb $Adb -Serial $s -ArgumentList @("pull", "/sdcard/", $dst) -AllowFail
        $fp = ((Invoke-Adb -Adb $Adb -Serial $s -ArgumentList @("shell", "getprop", "ro.build.fingerprint")).Output -join "").Trim()
        $bytes = [UInt64]0; if ($kib -match '^\d+$') { $bytes = [UInt64]$kib * 1024 }
        $m = New-BackupManifest -Dir $dst -RemoteFiles ([UInt64]$count) -RemoteBytes $bytes -PullExit $pull.ExitCode `
            -Device @{ serial_sha256 = (Get-StringSha256 $s); fingerprint = $fp }
        $problems = @(Test-Backup -Dir $dst -SerialSha256 (Get-StringSha256 $s))
        if ($problems) { $problems | Select-Object -First 20 | ForEach-Object { Write-Host "  $_" }; Fail "backup NOT valid ($($m.local_files)/$($m.remote_files) files, pull exit $($pull.ExitCode))" }
        Info "backup verified: $($m.local_files) files, $($m.local_bytes) bytes, manifest $dst\manifest.json"
        Info "NOT covered: app private data, accounts, Wi-Fi, settings: back them up in the apps / Xiaomi or Google account"
    }
    "backup-fastboot" {
        Need-Fastboot
        $s = Connect-PipaFastboot -Fastboot $Fastboot -Serial $Serial
        $dst = Join-Path $Root "backup\fastboot-$Stamp"
        New-Item -ItemType Directory -Force -Path $dst | Out-Null
        $r = Invoke-Fastboot -Fastboot $Fastboot -Serial $s -ArgumentList @("getvar", "all")
        Write-Utf8NoBom -Path (Join-Path $dst "getvar-all.txt") -Text ($r.Output -join "`n")
        Info "recorded $dst\getvar-all.txt"
    }
    "build" {
        $steps = @("bootstrap", "board", "firmware", "stage1", "kernel", "payload", "userdata", "check", "all", "setup")
        if ($steps -notcontains $Arg) { Fail "build needs one of: $($steps -join ' | ')" }
        Invoke-Wsl "UNIT=$(Q $Unit) scripts/wsl/build.sh $(Q $Arg)"
    }
    "boot" {
        Need-Fastboot
        if (-not $Arg -or -not (Test-Path -LiteralPath $Arg)) { Fail "boot needs an existing image path" }
        $img = (Resolve-Path -LiteralPath $Arg).Path
        $json = Join-Path $Logs "check-boot-$Stamp.json"
        Invoke-Wsl ("python3 tools/checks/check_bootimg.py $(Q (WslPath $img)) --stage1 --json $(Q (WslPath $json))")
        $check = Get-Content -LiteralPath $json -Raw -Encoding UTF8 | ConvertFrom-Json
        $stage1 = ([Convert]::ToUInt64(($check.info.ramdisk_size -replace '^0x', ''), 16) -eq 0)
        $s = Connect-PipaFastboot -Fastboot $Fastboot -Serial $Serial
        $hash = Get-FileSha256 $img
        if ($stage1) {
            Write-Host "STAGE-1 image: UEFI + UniXNU menu only. It carries NO iPadOS payload. Expected: Mu-Silicium log, then the UniXNU menu."
            Write-Host "What it can write: see docs\WINDOWS.md 'What a booted image can write' (UEFI variables are RAM-backed on pipaPkg)."
        } else {
            Write-Host "FULL image (payload $($check.info.ramdisk_label)). fastboot boot loads it into RAM, but the code it starts CAN write storage:"
            Write-Host "  - with native-ufs-root=1 and sheng-data-persist=2 XNU writes changed Data pages into the userdata store window"
            Write-Host "  - see docs\WINDOWS.md for the full audit of what this payload touches"
        }
        Write-Host "Device $s, image $img, sha256 $hash. A hang: hold Power + Volume Down ~10 s."
        if ((Read-Host "Type BOOT to continue") -ne "BOOT") { Fail "cancelled" 0 }
        Round-Log "boot $(if ($stage1) { 'stage1' } else { 'full' }) $hash serial_sha256=$(Get-StringSha256 $s)"
        Invoke-Fastboot -Fastboot $Fastboot -Serial $s -ArgumentList @("boot", $img) | Out-Null
        Info "booted; collect the log with: pipa.ps1 log -Reader <log-reader.img> -Serial $s"
    }
    "log" {
        if ($Reader) {
            Need-Fastboot
            $s = Connect-PipaFastboot -Fastboot $Fastboot -Serial $Serial
            Info "booting the log reader $Reader (RAM only)"
            Invoke-Fastboot -Fastboot $Fastboot -Serial $s -ArgumentList @("boot", (Resolve-Path -LiteralPath $Reader).Path) | Out-Null
        }
        Info "waiting up to 180 s for the PIPALOG disk"
        $vol = @()
        for ($i = 0; $i -lt 180 -and $vol.Count -eq 0; $i++) { $vol = @(Get-Volume -FileSystemLabel "PIPALOG" -ErrorAction SilentlyContinue); if ($vol.Count -eq 0) { Start-Sleep 1 } }
        if ($vol.Count -eq 0) { Fail "no PIPALOG volume appeared" }
        if ($vol.Count -gt 1) { Fail "more than one PIPALOG volume: unplug the other device" }
        $src = "$($vol[0].DriveLetter):\"
        $status = Get-Content -LiteralPath (Join-Path $src "STATUS.TXT") -Raw -ErrorAction SilentlyContinue
        if ($status -notmatch "pipa") { Fail "STATUS.TXT on $src is not the pipa reader's; left alone" }
        $dst = Join-Path $Logs "device\$Stamp"
        New-Item -ItemType Directory -Force -Path $dst | Out-Null
        Copy-Item -LiteralPath (Join-Path $src "LOG.BIN"), (Join-Path $src "STATUS.TXT") -Destination $dst
        foreach ($f in "LOG.BIN", "STATUS.TXT") { if ((Get-FileSha256 (Join-Path $src $f)) -ne (Get-FileSha256 (Join-Path $dst $f))) { Fail "copy of $f differs" } }
        Info "copied to $dst; ejecting (the reader then restarts into fastboot)"
        (New-Object -ComObject Shell.Application).Namespace(17).ParseName("$($vol[0].DriveLetter):").InvokeVerb("Eject")
    }
    "flash-userdata" {
        Need-Fastboot
        if (-not $IUnderstandDataLoss) { Fail "flash-userdata ERASES Android's userdata. Re-run with -IUnderstandDataLoss after a verified 'backup'." }
        if (-not $Arg -or -not (Test-Path -LiteralPath $Arg)) { Fail "flash-userdata needs the userdata image path" }
        $img = (Resolve-Path -LiteralPath $Arg).Path
        $facts = Load-Facts
        # 1. image vs measured window (sparse images fully parsed and expanded), board vs facts
        Invoke-Wsl ("python3 tools/flash_gate.py --unit $(Q $Unit) --image $(Q (WslPath $img))")
        # 2. the device in fastboot is the measured one, and its userdata is still what was measured
        $s = Connect-PipaFastboot -Fastboot $Fastboot -Serial $Serial
        $problems = @(Test-UnitIdentity -Facts $facts -Serial $s) + @(Test-UserdataLive -Fastboot $Fastboot -Serial $s -Facts $facts)
        # 3. a verified backup of THIS device exists
        $hash = Get-StringSha256 $s
        $backups = @(Get-ChildItem -LiteralPath (Join-Path $Root "backup") -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -notlike "fastboot-*" } | Sort-Object Name -Descending)
        $good = $null
        foreach ($b in $backups) { if (@(Test-Backup -Dir $b.FullName -SerialSha256 $hash).Count -eq 0) { $good = $b.FullName; break } }
        if (-not $good) { $problems += "no verified backup of this device (run 'pipa.ps1 backup' in Android first)" }
        if ($problems) { $problems | ForEach-Object { Write-Host "  REFUSED: $_" -ForegroundColor Red }; Fail "flash-userdata refused" 3 }
        Write-Host "Verified backup: $good"
        Write-Host "About to ERASE and write userdata on $s with $img (sha256 $(Get-FileSha256 $img))."
        Write-Host "Recovery: docs\RECOVERY.md. Bootloader, persist (calibration), modem and boot slots are not touched."
        $phrase = "HAPUS USERDATA " + $s.Substring([Math]::Max(0, $s.Length - 4))
        if ((Read-Host "Type '$phrase' to continue") -cne $phrase) { Fail "cancelled" 0 }
        Round-Log "flash-userdata $(Get-FileSha256 $img) serial_sha256=$hash"
        Invoke-Fastboot -Fastboot $Fastboot -Serial $s -ArgumentList @("flash", "userdata", $img) | Out-Null
        Info "userdata written"
    }
    default { (Get-Content -LiteralPath $PSCommandPath -TotalCount 22) -join "`n" | Write-Host }
}
} catch {
    Fail $_.Exception.Message
}
