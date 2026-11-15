<#
SPDX-License-Identifier: MIT
Library behind pipa.ps1. Every external command goes through Invoke-Native (exit code checked), every adb/fastboot call
carries -s <serial> of the ONE selected device, and identity is re-checked before anything that writes. Compatible with
Windows PowerShell 5.1 and PowerShell 7. Tested by tests/windows/PipaLib.Tests.ps1.
#>
Set-StrictMode -Version 1.0


function Invoke-Native {
    <# Run an external program; return @{ ExitCode; Output = string[] }. Throws on a non-zero exit unless -AllowFail. #>
    param([Parameter(Mandatory)] [string] $Exe, [string[]] $ArgumentList = @(), [switch] $AllowFail)
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"   # PS 5.1 turns redirected native stderr into terminating errors under "Stop"
    try {
        $lines = @(& $Exe @ArgumentList 2>&1 | ForEach-Object { "$_" })
        $code = $LASTEXITCODE
    } catch {
        $lines = @("$_"); $code = -1
    } finally { $ErrorActionPreference = $old }
    if ($null -eq $code) { $code = 0 }
    $res = [pscustomobject]@{ ExitCode = [int]$code; Output = $lines }
    if ($code -ne 0 -and -not $AllowFail) {
        throw [System.InvalidOperationException]::new("$([IO.Path]::GetFileName($Exe)) $($ArgumentList -join ' ') failed (exit $code): $(($lines | Select-Object -Last 3) -join ' | ')")
    }
    return $res
}

function Get-DeviceList {
    <# Parse `adb devices` / `fastboot devices` into @{ Serial; State }. #>
    param([Parameter(Mandatory)] [string] $Exe, [ValidateSet("adb", "fastboot")] [string] $Kind)
    $r = Invoke-Native -Exe $Exe -ArgumentList @("devices")
    $out = @()
    foreach ($line in $r.Output) {
        if ($line -match '^\s*$' -or $line -match '^List of devices' -or $line -match '^\*') { continue }
        $parts = $line.Trim() -split '\s+'
        if ($parts.Count -ge 2) { $out += [pscustomobject]@{ Serial = $parts[0]; State = $parts[1] } }
    }
    return , $out
}

function Select-Device {
    <# Exactly one usable device, or the one named by -Serial. Ambiguous, missing, offline or unauthorized -> throw. #>
    param([object[]] $Devices = @(), [string] $Serial, [Parameter(Mandatory)] [string] $ReadyState)
    $Devices = @($Devices)
    if ($Serial) {
        $match = @($Devices | Where-Object { $_.Serial -ceq $Serial })
        if ($match.Count -eq 0) { throw [System.InvalidOperationException]::new("device $Serial is not connected (connected: $(($Devices | ForEach-Object { $_.Serial }) -join ', '))") }
        if ($match[0].State -ne $ReadyState) { throw [System.InvalidOperationException]::new("device $Serial is '$($match[0].State)', need '$ReadyState'") }
        return $Serial
    }
    if ($Devices.Count -eq 0) { throw [System.InvalidOperationException]::new("no device connected (need one in '$ReadyState')") }
    if ($Devices.Count -gt 1) { throw [System.InvalidOperationException]::new("$($Devices.Count) devices connected: choose one with -Serial ($(($Devices | ForEach-Object { $_.Serial }) -join ', '))") }
    if ($Devices[0].State -ne $ReadyState) { throw [System.InvalidOperationException]::new("device $($Devices[0].Serial) is '$($Devices[0].State)', need '$ReadyState'") }
    return $Devices[0].Serial
}

function Invoke-Adb { param([string] $Adb, [Parameter(Mandatory)] [string] $Serial, [string[]] $ArgumentList, [switch] $AllowFail)
    Invoke-Native -Exe $Adb -ArgumentList (@("-s", $Serial) + $ArgumentList) -AllowFail:$AllowFail }
function Invoke-Fastboot { param([string] $Fastboot, [Parameter(Mandatory)] [string] $Serial, [string[]] $ArgumentList, [switch] $AllowFail)
    Invoke-Native -Exe $Fastboot -ArgumentList (@("-s", $Serial) + $ArgumentList) -AllowFail:$AllowFail }

function Get-FastbootVar {
    param([string] $Fastboot, [string] $Serial, [string] $Name)
    $r = Invoke-Fastboot -Fastboot $Fastboot -Serial $Serial -ArgumentList @("getvar", $Name)
    foreach ($line in $r.Output) {
        if ($line -match ('^' + [regex]::Escape($Name) + ':\s*(.*?)\s*$')) { return $Matches[1] }
    }
    throw [System.InvalidOperationException]::new("fastboot getvar $Name gave no value")
}

function Get-StringSha256 { param([string] $Text)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { -join ($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)) | ForEach-Object { $_.ToString("x2") }) } finally { $sha.Dispose() } }

function Connect-PipaAdb {
    <# Select the Android device, check it is a pipa and that its ro.serialno is the selected serial. Returns the serial. #>
    param([string] $Adb, [string] $Serial)
    $s = Select-Device -Devices (Get-DeviceList -Exe $Adb -Kind adb) -Serial $Serial -ReadyState "device"
    $prod = ((Invoke-Adb -Adb $Adb -Serial $s -ArgumentList @("shell", "getprop", "ro.product.device")).Output -join "").Trim()
    if ($prod -ne "pipa") { throw [System.InvalidOperationException]::new("device $s reports ro.product.device='$prod', not pipa") }
    $sn = ((Invoke-Adb -Adb $Adb -Serial $s -ArgumentList @("shell", "getprop", "ro.serialno")).Output -join "").Trim()
    if ($sn -and $sn -cne $s) { throw [System.InvalidOperationException]::new("adb serial $s but ro.serialno is ${sn}: refusing (USB/TCP alias?)") }
    return $s
}

function Connect-PipaFastboot {
    param([string] $Fastboot, [string] $Serial)
    $s = Select-Device -Devices (Get-DeviceList -Exe $Fastboot -Kind fastboot) -Serial $Serial -ReadyState "fastboot"
    $prod = Get-FastbootVar -Fastboot $Fastboot -Serial $s -Name "product"
    if ($prod -ne "pipa") { throw [System.InvalidOperationException]::new("device $s reports product '$prod', not pipa") }
    return $s
}

function Test-UnitIdentity {
    <# The unit facts must belong to this serial (collector stores sha256 of ro.serialno). Returns problems. #>
    param([Parameter(Mandatory)] $Facts, [Parameter(Mandatory)] [string] $Serial)
    $p = @()
    $want = $Facts.device.serial_sha256
    if (-not $want) { $p += "unit facts carry no serial hash: collect them again with this script" }
    elseif ($want -ne (Get-StringSha256 $Serial)) { $p += "unit facts were measured on another device (serial hash differs)" }
    if ($Facts.provenance.source -ne "measured") { $p += "unit facts are '$($Facts.provenance.source)', not measured on the tablet" }
    return $p
}

function ConvertFrom-FastbootSize { param([string] $Text)
    if ($Text -match '^0x([0-9a-fA-F]+)$') { return [Convert]::ToInt64($Matches[1], 16) }
    if ($Text -match '^\d+$') { return [long]$Text }
    throw [System.InvalidOperationException]::new("unparseable fastboot size '$Text'") }

function Test-UserdataLive {
    <# Re-read userdata from the bootloader and compare with the measured GPT before a write. Returns problems. #>
    param([string] $Fastboot, [string] $Serial, [Parameter(Mandatory)] $Facts)
    $p = @()
    $st = $Facts.storage
    if ($st.source -ne "measured" -or -not $st.userdata) { return @("userdata window not measured") }
    # [long] throughout: mixing UInt64 with Int32 makes PowerShell fall back to Double.
    $lba = [long]$st.lba_bytes
    $first = [Convert]::ToInt64(($st.userdata.first_lba -replace '^0x', ''), 16)
    $last = [Convert]::ToInt64(($st.userdata.last_lba -replace '^0x', ''), 16)
    $want = [long](($last - $first + [long]1) * $lba)
    $size = ConvertFrom-FastbootSize (Get-FastbootVar -Fastboot $Fastboot -Serial $Serial -Name "partition-size:userdata")
    if ($size -ne $want) { $p += "bootloader reports userdata $size bytes, measured window is $want bytes" }
    $r = Invoke-Fastboot -Fastboot $Fastboot -Serial $Serial -ArgumentList @("getvar", "logical-block-size") -AllowFail
    $lbs = $null
    foreach ($line in $r.Output) { if ($line -match '^logical-block-size:\s*(\S+)') { $lbs = ConvertFrom-FastbootSize $Matches[1] } }
    if ($null -eq $lbs) { $p += "bootloader does not report logical-block-size: cannot confirm $lba-byte sectors" }
    elseif ($lbs -ne $lba) { $p += "bootloader logical-block-size $lbs != measured $lba" }
    $slot = (Invoke-Fastboot -Fastboot $Fastboot -Serial $Serial -ArgumentList @("getvar", "current-slot") -AllowFail).Output -join " "
    if ($Facts.device.PSObject.Properties.Name -contains "slot_suffix" -and $Facts.device.slot_suffix -and $slot -notmatch [regex]::Escape(($Facts.device.slot_suffix -replace '^_', ''))) {
        $p += "active slot changed since measurement ($slot vs $($Facts.device.slot_suffix))"
    }
    return $p
}

function Write-Utf8NoBom { param([string] $Path, [string] $Text)
    [IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding($false))) }

function ConvertTo-BashQuoted {
    <# One bash word, single-quoted: safe for spaces, $, `, " and ' in paths. #>
    param([AllowEmptyString()] [string] $Text)
    return "'" + ($Text -replace "'", "'\''") + "'" }

function Get-FileSha256 { param([string] $Path) (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant() }

function Save-DeviceFile {
    <# adb pull to a temporary name, check the exit code and size, then replace the cache entry. On failure the old
       cached file is moved aside (*.stale), so it can never be mistaken for a fresh copy. Returns a record. #>
    param([string] $Adb, [string] $Serial, [string] $Remote, [string] $Destination)
    $dir = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $tmp = "$Destination.part"
    if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force }
    $r = Invoke-Adb -Adb $Adb -Serial $Serial -ArgumentList @("pull", $Remote, $tmp) -AllowFail
    $ok = ($r.ExitCode -eq 0) -and (Test-Path -LiteralPath $tmp) -and ((Get-Item -LiteralPath $tmp).Length -gt 0)
    if (-not $ok) {
        if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force }
        if (Test-Path -LiteralPath $Destination) { Move-Item -LiteralPath $Destination -Destination "$Destination.stale" -Force }
        return [pscustomobject]@{ Remote = $Remote; Path = $Destination; State = "missing"; Sha256 = $null; Bytes = 0
            Detail = "adb pull exit $($r.ExitCode): $(($r.Output | Select-Object -Last 1))" }
    }
    Move-Item -LiteralPath $tmp -Destination $Destination -Force
    return [pscustomobject]@{ Remote = $Remote; Path = $Destination; State = "ok"; Sha256 = (Get-FileSha256 $Destination)
        Bytes = (Get-Item -LiteralPath $Destination).Length; Detail = "" }
}

function New-BackupManifest {
    <# Hash every file under $Dir\sdcard and record what the tablet said it had, so Test-Backup can prove completeness. #>
    param([string] $Dir, [long] $RemoteFiles, [long] $RemoteBytes, [int] $PullExit, [hashtable] $Device)
    $root = Join-Path $Dir "sdcard"
    $files = @()
    if (Test-Path -LiteralPath $root) {
        $base = (Resolve-Path -LiteralPath $root).Path.TrimEnd('\', '/')
        foreach ($f in Get-ChildItem -LiteralPath $root -Recurse -File -Force) {
            $files += [ordered]@{ path = $f.FullName.Substring($base.Length + 1).Replace('\', '/'); bytes = $f.Length; sha256 = (Get-FileSha256 $f.FullName) }
        }
    }
    $localBytes = [long]0; foreach ($f in $files) { $localBytes += [long]$f.bytes }
    $m = [ordered]@{
        schema = 1; created_utc = (Get-Date).ToUniversalTime().ToString("o"); device = $Device
        covered = @("/sdcard (internal shared storage: DCIM, Download, Documents, Pictures, Music, Movies, app folders under Android/media)")
        not_covered = @("app private data (/data/data, /data/user): use each app's own backup or the Xiaomi/Google account",
            "accounts, Wi-Fi networks and system settings", "Android/data and Android/obb of apps on Android 11+ (not readable over adb)")
        pull_exit = $PullExit; remote_files = $RemoteFiles; remote_bytes = $RemoteBytes
        local_files = [long]$files.Count; local_bytes = $localBytes; files = $files
    }
    $m.complete = ($PullExit -eq 0) -and ([long]$files.Count -ge $RemoteFiles) -and ($RemoteFiles -gt 0)
    Write-Utf8NoBom -Path (Join-Path $Dir "manifest.json") -Text ($m | ConvertTo-Json -Depth 6)
    return $m
}

function Test-Backup {
    <# A backup counts only if its manifest says complete AND every listed file still has its size and checksum. #>
    param([string] $Dir, [string] $SerialSha256)
    $p = @()
    $mf = Join-Path $Dir "manifest.json"
    if (-not (Test-Path -LiteralPath $mf)) { return @("$Dir has no manifest.json") }
    $m = Get-Content -LiteralPath $mf -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $m.complete) { $p += "manifest says the backup is incomplete (pull exit $($m.pull_exit), $($m.local_files)/$($m.remote_files) files)" }
    if ($SerialSha256 -and $m.device.serial_sha256 -ne $SerialSha256) { $p += "backup belongs to another device" }
    $root = Join-Path $Dir "sdcard"
    foreach ($f in @($m.files)) {
        $path = Join-Path $root ($f.path.Replace('/', [IO.Path]::DirectorySeparatorChar))
        if (-not (Test-Path -LiteralPath $path)) { $p += "missing: $($f.path)"; continue }
        if ((Get-Item -LiteralPath $path).Length -ne $f.bytes -or (Get-FileSha256 $path) -ne $f.sha256) { $p += "changed: $($f.path)" }
    }
    return $p
}

Export-ModuleMember -Function Invoke-Native, Get-DeviceList, Select-Device, Invoke-Adb, Invoke-Fastboot, Get-FastbootVar,
    Get-StringSha256, Connect-PipaAdb, Connect-PipaFastboot, Test-UnitIdentity, ConvertFrom-FastbootSize, Test-UserdataLive,
    Write-Utf8NoBom, ConvertTo-BashQuoted, Get-FileSha256, Save-DeviceFile, New-BackupManifest, Test-Backup
