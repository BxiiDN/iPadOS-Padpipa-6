# SPDX-License-Identifier: MIT
# Pester 5 tests for scripts/windows/PipaLib.psm1 (run by .github/workflows/build.yml on Windows PowerShell 5.1 and 7).
# Every test reproduces a real failure the earlier pipa.ps1 had: no -s on adb/fastboot, unchecked exit codes, stale
# cached firmware reported as fresh, a backup folder taken as proof, BOM in files read by Python, paths with spaces.

BeforeAll {
    Import-Module (Join-Path $PSScriptRoot "..\..\scripts\windows\PipaLib.psm1") -Force
    function global:New-Out([string[]] $lines, [int] $code = 0) { [pscustomobject]@{ ExitCode = $code; Output = $lines } }
}

Describe "Invoke-Native exit codes" {
    BeforeAll {
        $script:cmd = Join-Path $TestDrive "fails.cmd"
        Set-Content -LiteralPath $script:cmd -Value "@echo off`r`necho boom 1>&2`r`nexit /b 7" -Encoding ASCII
        $script:okcmd = Join-Path $TestDrive "ok with space.cmd"
        Set-Content -LiteralPath $script:okcmd -Value "@echo off`r`necho hello" -Encoding ASCII
    }
    It "throws on a non-zero exit" { { Invoke-Native -Exe $script:cmd } | Should -Throw "*exit 7*" }
    It "returns the code with -AllowFail" { (Invoke-Native -Exe $script:cmd -AllowFail).ExitCode | Should -Be 7 }
    It "captures stderr" { (Invoke-Native -Exe $script:cmd -AllowFail).Output -join " " | Should -Match "boom" }
    It "runs a program whose path has spaces" { (Invoke-Native -Exe $script:okcmd).Output | Should -Contain "hello" }
    It "reports a missing program as a failure" { { Invoke-Native -Exe (Join-Path $TestDrive "nope.exe") } | Should -Throw }
}

Describe "Device selection" {
    It "picks the only ready device" {
        Select-Device -Devices @([pscustomobject]@{ Serial = "abc"; State = "device" }) -ReadyState device | Should -Be "abc"
    }
    It "refuses two devices without -Serial" {
        { Select-Device -Devices @([pscustomobject]@{ Serial = "a"; State = "device" }, [pscustomobject]@{ Serial = "b"; State = "device" }) -ReadyState device } |
            Should -Throw "*choose one with -Serial*"
    }
    It "uses -Serial among several" {
        Select-Device -Devices @([pscustomobject]@{ Serial = "a"; State = "device" }, [pscustomobject]@{ Serial = "b"; State = "device" }) -Serial b -ReadyState device | Should -Be "b"
    }
    It "refuses a disconnected -Serial" {
        { Select-Device -Devices @([pscustomobject]@{ Serial = "a"; State = "device" }) -Serial z -ReadyState device } | Should -Throw "*not connected*"
    }
    It "refuses unauthorized and offline" {
        { Select-Device -Devices @([pscustomobject]@{ Serial = "a"; State = "unauthorized" }) -ReadyState device } | Should -Throw "*unauthorized*"
        { Select-Device -Devices @([pscustomobject]@{ Serial = "a"; State = "offline" }) -Serial a -ReadyState device } | Should -Throw "*offline*"
    }
    It "refuses no device" { { Select-Device -Devices @() -ReadyState fastboot } | Should -Throw "*no device*" }
    It "parses adb devices output" {
        Mock -ModuleName PipaLib Invoke-Native { New-Out @("List of devices attached", "abc123`tdevice", "def`tunauthorized", "") }
        $d = Get-DeviceList -Exe adb -Kind adb
        $d.Count | Should -Be 2
        $d[1].State | Should -Be "unauthorized"
    }
}

Describe "Every adb/fastboot call carries -s" {
    It "Invoke-Adb prepends -s" {
        Mock -ModuleName PipaLib Invoke-Native { New-Out @(($ArgumentList -join " ")) }
        (Invoke-Adb -Adb adb -Serial S1 -ArgumentList @("shell", "id")).Output | Should -Be "-s S1 shell id"
    }
    It "Connect-PipaAdb checks product and ro.serialno against the selected serial" {
        Mock -ModuleName PipaLib Invoke-Native {
            $a = $ArgumentList -join " "
            if ($a -eq "devices") { return New-Out @("S1`tdevice") }
            if ($a -eq "-s S1 shell getprop ro.product.device") { return New-Out @("pipa") }
            if ($a -eq "-s S1 shell getprop ro.serialno") { return New-Out @("OTHER") }
            throw "unexpected call without -s: $a"
        }
        { Connect-PipaAdb -Adb adb } | Should -Throw "*ro.serialno is OTHER*"
    }
    It "Connect-PipaFastboot refuses a non-pipa" {
        Mock -ModuleName PipaLib Invoke-Native {
            $a = $ArgumentList -join " "
            if ($a -eq "devices") { return New-Out @("F1`tfastboot") }
            if ($a -eq "-s F1 getvar product") { return New-Out @("product: liuqin", "Finished.") }
            throw "unexpected: $a"
        }
        { Connect-PipaFastboot -Fastboot fastboot } | Should -Throw "*not pipa*"
    }
}

Describe "Measured facts are bound to the device and re-checked live" {
    BeforeAll {
        $script:facts = [pscustomobject]@{
            provenance = [pscustomobject]@{ source = "measured" }
            device = [pscustomobject]@{ product = "pipa"; serial_sha256 = (Get-StringSha256 "F1") }
            storage = [pscustomobject]@{ source = "measured"; lba_bytes = 4096
                userdata = [pscustomobject]@{ first_lba = "0x293000"; last_lba = "0x392fff" } } }
        $global:PipaWant = [long](0x392fff - 0x293000 + 1) * [long]4096
    }
    It "accepts the measured device" { (Test-UnitIdentity -Facts $script:facts -Serial F1).Count | Should -Be 0 }
    It "refuses facts of another device" { (@(Test-UnitIdentity -Facts $script:facts -Serial F2) -join " ") | Should -Match "another device" }
    It "passes when size and block size match" {
        Mock -ModuleName PipaLib Invoke-Native {
            $a = $ArgumentList -join " "
            if ($a -eq "-s F1 getvar partition-size:userdata") { return New-Out @(("partition-size:userdata: 0x{0:x}" -f $global:PipaWant)) }
            if ($a -eq "-s F1 getvar logical-block-size") { return New-Out @("logical-block-size: 0x1000") }
            return New-Out @("current-slot: b")
        }
        (Test-UserdataLive -Fastboot fastboot -Serial F1 -Facts $script:facts).Count | Should -Be 0
    }
    It "refuses a userdata size that differs from the measurement" {
        Mock -ModuleName PipaLib Invoke-Native {
            $a = $ArgumentList -join " "
            if ($a -like "*partition-size:userdata") { return New-Out @("partition-size:userdata: 0x1aa5ff6000") }
            if ($a -like "*logical-block-size") { return New-Out @("logical-block-size: 0x1000") }
            return New-Out @("current-slot: b")
        }
        (@(Test-UserdataLive -Fastboot fastboot -Serial F1 -Facts $script:facts) -join " ") | Should -Match "measured window"
    }
    It "refuses a 512-byte block size" {
        Mock -ModuleName PipaLib Invoke-Native {
            $a = $ArgumentList -join " "
            if ($a -like "*partition-size:userdata") { return New-Out @(("partition-size:userdata: 0x{0:x}" -f $global:PipaWant)) }
            if ($a -like "*logical-block-size") { return New-Out @("logical-block-size: 0x200") }
            return New-Out @("current-slot: b")
        }
        (@(Test-UserdataLive -Fastboot fastboot -Serial F1 -Facts $script:facts) -join " ") | Should -Match "logical-block-size"
    }
}

Describe "Firmware copy never reports a stale cache entry" {
    It "moves the old file aside when the pull fails" {
        $dst = Join-Path $TestDrive "cache dir\gpu\a650_gmu.bin"
        New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
        Set-Content -LiteralPath $dst -Value "old copy"
        Mock -ModuleName PipaLib Invoke-Native { New-Out @("adb: error: remote object does not exist") 1 }
        $r = Save-DeviceFile -Adb adb -Serial S1 -Remote /vendor/firmware/a650_gmu.bin -Destination $dst
        $r.State | Should -Be "missing"
        Test-Path -LiteralPath $dst | Should -BeFalse
        Test-Path -LiteralPath "$dst.stale" | Should -BeTrue
    }
    It "treats an empty pull as missing" {
        $dst = Join-Path $TestDrive "c2\zap.elf"
        Mock -ModuleName PipaLib Invoke-Native { New-Item -ItemType File -Force -Path $ArgumentList[4] | Out-Null; New-Out @("1 file pulled") }
        (Save-DeviceFile -Adb adb -Serial S1 -Remote /x -Destination $dst).State | Should -Be "missing"
    }
    It "replaces the cache entry on success and hashes it" {
        $dst = Join-Path $TestDrive "c3\zap.elf"
        Mock -ModuleName PipaLib Invoke-Native { Set-Content -LiteralPath $ArgumentList[4] -Value "fresh" -NoNewline; New-Out @("1 file pulled") }
        $r = Save-DeviceFile -Adb adb -Serial S1 -Remote /x -Destination $dst
        $r.State | Should -Be "ok"
        $r.Sha256 | Should -Be (Get-StringSha256 "fresh")
    }
}

Describe "Backup is proven by its manifest, not by a folder" {
    BeforeEach {
        $script:dir = Join-Path $TestDrive ("bk " + [guid]::NewGuid())
        New-Item -ItemType Directory -Force -Path (Join-Path $script:dir "sdcard\DCIM") | Out-Null
        Set-Content -LiteralPath (Join-Path $script:dir "sdcard\DCIM\a b.jpg") -Value "photo"
        Set-Content -LiteralPath (Join-Path $script:dir "sdcard\notes.txt") -Value "text"
        $script:dev = @{ serial_sha256 = (Get-StringSha256 "S1"); fingerprint = "Xiaomi/pipa" }
    }
    It "a complete pull verifies" {
        $m = New-BackupManifest -Dir $script:dir -RemoteFiles 2 -RemoteBytes 10 -PullExit 0 -Device $script:dev
        $m.complete | Should -BeTrue
        (Test-Backup -Dir $script:dir -SerialSha256 (Get-StringSha256 "S1")).Count | Should -Be 0
    }
    It "an empty folder is not a backup" {
        $e = Join-Path $TestDrive "empty"; New-Item -ItemType Directory -Force -Path $e | Out-Null
        (@(Test-Backup -Dir $e) -join " ") | Should -Match "no manifest"
    }
    It "a failed pull is incomplete" {
        New-BackupManifest -Dir $script:dir -RemoteFiles 2 -RemoteBytes 10 -PullExit 1 -Device $script:dev | Out-Null
        (@(Test-Backup -Dir $script:dir) -join " ") | Should -Match "incomplete"
    }
    It "fewer files than the tablet reported is incomplete" {
        New-BackupManifest -Dir $script:dir -RemoteFiles 5 -RemoteBytes 10 -PullExit 0 -Device $script:dev | Out-Null
        (@(Test-Backup -Dir $script:dir) -join " ") | Should -Match "incomplete"
    }
    It "a changed or deleted file is detected" {
        New-BackupManifest -Dir $script:dir -RemoteFiles 2 -RemoteBytes 10 -PullExit 0 -Device $script:dev | Out-Null
        Set-Content -LiteralPath (Join-Path $script:dir "sdcard\notes.txt") -Value "tampered"
        Remove-Item -LiteralPath (Join-Path $script:dir "sdcard\DCIM\a b.jpg")
        $p = Test-Backup -Dir $script:dir
        $p | Should -Contain "changed: notes.txt"
        $p | Should -Contain "missing: DCIM/a b.jpg"
    }
    It "a backup of another device does not count" {
        New-BackupManifest -Dir $script:dir -RemoteFiles 2 -RemoteBytes 10 -PullExit 0 -Device $script:dev | Out-Null
        (@(Test-Backup -Dir $script:dir -SerialSha256 (Get-StringSha256 "S2")) -join " ") | Should -Match "another device"
    }
    It "the manifest has no BOM" {
        New-BackupManifest -Dir $script:dir -RemoteFiles 2 -RemoteBytes 10 -PullExit 0 -Device $script:dev | Out-Null
        $b = [IO.File]::ReadAllBytes((Join-Path $script:dir "manifest.json"))
        ($b[0] -eq 0xEF -and $b[1] -eq 0xBB) | Should -BeFalse
    }
}

Describe "Encoding and quoting" {
    It "Write-Utf8NoBom writes no BOM and keeps non-ASCII" {
        $f = Join-Path $TestDrive "x.kv"
        Write-Utf8NoBom -Path $f -Text "panel=ñ`n"
        $b = [IO.File]::ReadAllBytes($f)
        $b[0] | Should -Be ([byte][char]'p')
        [Text.Encoding]::UTF8.GetString($b) | Should -Be "panel=ñ`n"
    }
    It "the serial hash equals the collector's printf %s | sha256sum" {
        Get-StringSha256 "abc" | Should -Be "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    }
    It "ConvertTo-BashQuoted survives spaces, quotes and dollars in bash" {
        $bash = Get-Command bash -ErrorAction SilentlyContinue
        if (-not $bash) { Set-ItResult -Skipped -Because "no bash on PATH"; return }
        $value = "/mnt/c/Users/A B/it's `$HOME `"x`""
        $sh = Join-Path $TestDrive "q.sh"
        Write-Utf8NoBom -Path $sh -Text ("printf '%s' " + (ConvertTo-BashQuoted $value) + "`n")
        $out = & $bash.Source $sh
        ($out -join "") | Should -Be $value
    }
    It "ConvertFrom-FastbootSize reads hex and decimal" {
        ConvertFrom-FastbootSize "0x1000" | Should -Be 4096
        ConvertFrom-FastbootSize "512" | Should -Be 512
        { ConvertFrom-FastbootSize "abc" } | Should -Throw
    }
}
