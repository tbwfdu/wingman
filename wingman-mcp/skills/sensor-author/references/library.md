# Sensor library

Ready-to-use reference sensors covering the most common UEM use cases. Each entry includes the five decisions (platform, query_type, response_type, execution_context, suggested name) and the script body.

Adapt these rather than writing from scratch when the user's ask is close to something in the library — the tribal-knowledge parts (which command to use, which output to parse, what to return when the probe fails) are already baked in.

## Table of contents

**Security & encryption**
- [macOS — FileVault status](#macos--filevault-status)
- [macOS — FileVault recovery key escrow status](#macos--filevault-recovery-key-escrow-status)
- [Windows — BitLocker status](#windows--bitlocker-status)
- [Windows — BitLocker recovery key backed up to AD/Entra](#windows--bitlocker-recovery-key-backed-up-to-adentra)
- [macOS — Gatekeeper enabled](#macos--gatekeeper-enabled)
- [macOS — SIP enabled](#macos--sip-enabled)

**Hardware & battery**
- [macOS — Rosetta 2 installed](#macos--rosetta-2-installed)
- [macOS — battery cycle count](#macos--battery-cycle-count)
- [macOS — battery health condition](#macos--battery-health-condition)
- [Windows — battery health percentage](#windows--battery-health-percentage)

**Patching & OS state**
- [macOS — days since last software update](#macos--days-since-last-software-update)
- [Windows — days since last Windows Update](#windows--days-since-last-windows-update)
- [macOS — pending OS update available](#macos--pending-os-update-available)

**Inventory**
- [macOS — installed app version (by bundle ID)](#macos--installed-app-version-by-bundle-id)
- [Windows — installed app version (by DisplayName)](#windows--installed-app-version-by-displayname)
- [macOS — free disk space in GB](#macos--free-disk-space-in-gb)
- [Windows — free disk space in GB](#windows--free-disk-space-in-gb)

**Certificates & identity**
- [macOS — days until system keychain cert expiry](#macos--days-until-system-keychain-cert-expiry)
- [Windows — days until LocalMachine cert expiry](#windows--days-until-localmachine-cert-expiry)

---

## Security & encryption

### macOS — FileVault status

- Platform: macOS, Query: BASH, Response: BOOLEAN, Context: SYSTEM
- Name: `macOS.security.filevault_enabled`

```bash
#!/bin/bash
status=$(/usr/bin/fdesetup status 2>/dev/null)
if echo "$status" | grep -q "FileVault is On"; then
    echo "true"
else
    echo "false"
fi
```

### macOS — FileVault recovery key escrow status

- Platform: macOS, Query: BASH, Response: STRING, Context: SYSTEM
- Name: `macOS.security.filevault_escrow_status`

Returns one of: `escrowed`, `not_escrowed`, `filevault_off`.

```bash
#!/bin/bash
if ! /usr/bin/fdesetup status 2>/dev/null | grep -q "FileVault is On"; then
    echo "filevault_off"
    exit 0
fi
if /usr/bin/profiles -P 2>/dev/null | grep -q "com.apple.security.FDERecoveryKeyEscrow"; then
    echo "escrowed"
else
    echo "not_escrowed"
fi
```

### Windows — BitLocker status

- Platform: Windows, Query: POWERSHELL, Response: BOOLEAN, Context: SYSTEM
- Name: `Windows.security.bitlocker_enabled`

Checks the system drive (usually C:). If the user needs all fixed drives covered, split into separate sensors per drive letter.

```powershell
$drive = $env:SystemDrive
try {
    $vol = Get-BitLockerVolume -MountPoint $drive -ErrorAction Stop
    if ($vol.ProtectionStatus -eq 'On') {
        "true"
    } else {
        "false"
    }
} catch {
    "false"
}
```

### Windows — BitLocker recovery key backed up to AD/Entra

- Platform: Windows, Query: POWERSHELL, Response: BOOLEAN, Context: SYSTEM
- Name: `Windows.security.bitlocker_key_backed_up`

Detects whether a recovery password protector exists. Note: this doesn't prove the key reached AD/Entra, only that a recovery password protector is present — the necessary precondition. Pair with an audit on the directory side for full assurance.

```powershell
$drive = $env:SystemDrive
try {
    $vol = Get-BitLockerVolume -MountPoint $drive -ErrorAction Stop
    $hasRecoveryPassword = $vol.KeyProtector | Where-Object { $_.KeyProtectorType -eq 'RecoveryPassword' }
    if ($hasRecoveryPassword) { "true" } else { "false" }
} catch {
    "false"
}
```

### macOS — Gatekeeper enabled

- Platform: macOS, Query: BASH, Response: BOOLEAN, Context: SYSTEM
- Name: `macOS.security.gatekeeper_enabled`

```bash
#!/bin/bash
if /usr/sbin/spctl --status 2>/dev/null | grep -q "assessments enabled"; then
    echo "true"
else
    echo "false"
fi
```

### macOS — SIP enabled

- Platform: macOS, Query: BASH, Response: BOOLEAN, Context: SYSTEM
- Name: `macOS.security.sip_enabled`

```bash
#!/bin/bash
if /usr/bin/csrutil status 2>/dev/null | grep -q "enabled"; then
    echo "true"
else
    echo "false"
fi
```

---

## Hardware & battery

### macOS — Rosetta 2 installed

- Platform: macOS, Query: BASH, Response: BOOLEAN, Context: SYSTEM
- Name: `macOS.hardware.rosetta_installed`

On Intel Macs, Rosetta is not applicable. Emits `false` there, which is correct for "this Mac can run Rosetta workflows."

```bash
#!/bin/bash
arch=$(/usr/bin/arch)
if [ "$arch" != "arm64" ]; then
    echo "false"
    exit 0
fi
if /usr/bin/pgrep -q oahd; then
    echo "true"
else
    echo "false"
fi
```

### macOS — battery cycle count

- Platform: macOS, Query: BASH, Response: INTEGER, Context: SYSTEM
- Name: `macOS.hardware.battery_cycle_count`

Non-laptop Macs don't have a battery; this returns nothing on those, which shows as empty on the device record (correct — no cycles to report).

```bash
#!/bin/bash
/usr/sbin/ioreg -rn AppleSmartBattery 2>/dev/null | /usr/bin/awk -F'= ' '/"CycleCount"/ {print $2; exit}'
```

### macOS — battery health condition

- Platform: macOS, Query: BASH, Response: STRING, Context: SYSTEM
- Name: `macOS.hardware.battery_condition`

Returns `Normal`, `Service Recommended`, `Service Battery`, or empty for non-laptops.

```bash
#!/bin/bash
/usr/sbin/system_profiler SPPowerDataType 2>/dev/null | /usr/bin/awk -F': ' '/Condition/ {print $2; exit}'
```

### Windows — battery health percentage

- Platform: Windows, Query: POWERSHELL, Response: INTEGER, Context: SYSTEM
- Name: `Windows.hardware.battery_health_pct`

Integer percentage (FullChargeCapacity / DesignCapacity × 100). Non-battery devices return nothing.

```powershell
try {
    $full = (Get-WmiObject -Class BatteryFullChargedCapacity -Namespace ROOT\WMI -ErrorAction Stop).FullChargedCapacity
    $design = (Get-WmiObject -Class BatteryStaticData -Namespace ROOT\WMI -ErrorAction Stop).DesignedCapacity
    if ($design -gt 0) {
        [int](($full / $design) * 100)
    }
} catch {}
```

---

## Patching & OS state

### macOS — days since last software update

- Platform: macOS, Query: BASH, Response: INTEGER, Context: SYSTEM
- Name: `macOS.patching.days_since_last_update`

Reads `LastSuccessfulDate` from the Software Update preference plist and computes age in whole days.

```bash
#!/bin/bash
last=$(/usr/bin/defaults read /Library/Preferences/com.apple.SoftwareUpdate LastSuccessfulDate 2>/dev/null)
if [ -z "$last" ]; then
    exit 0
fi
last_epoch=$(/bin/date -j -f "%Y-%m-%d %H:%M:%S %z" "$last" "+%s" 2>/dev/null)
if [ -z "$last_epoch" ]; then
    exit 0
fi
now_epoch=$(/bin/date "+%s")
echo $(( (now_epoch - last_epoch) / 86400 ))
```

### Windows — days since last Windows Update

- Platform: Windows, Query: POWERSHELL, Response: INTEGER, Context: SYSTEM
- Name: `Windows.patching.days_since_last_update`

Uses the Update Session COM object. If no history exists, emits nothing.

```powershell
try {
    $session = New-Object -ComObject Microsoft.Update.Session
    $searcher = $session.CreateUpdateSearcher()
    $count = $searcher.GetTotalHistoryCount()
    if ($count -le 0) { return }
    $history = $searcher.QueryHistory(0, 1)
    $last = $history | Select-Object -First 1
    if ($last -and $last.Date) {
        [int]((Get-Date) - $last.Date).TotalDays
    }
} catch {}
```

### macOS — pending OS update available

- Platform: macOS, Query: BASH, Response: BOOLEAN, Context: SYSTEM
- Name: `macOS.patching.update_available`

```bash
#!/bin/bash
output=$(/usr/sbin/softwareupdate -l 2>&1)
if echo "$output" | /usr/bin/grep -q "No new software available"; then
    echo "false"
else
    echo "true"
fi
```

---

## Inventory

### macOS — installed app version (by bundle ID)

- Platform: macOS, Query: BASH, Response: STRING, Context: SYSTEM
- Name pattern: `macOS.inventory.<appname>_version` (e.g. `macOS.inventory.chrome_version`)

Replace `BUNDLE_ID` with the app's bundle identifier (e.g. `com.google.Chrome`). Returns the CFBundleShortVersionString, or empty if the app isn't installed.

```bash
#!/bin/bash
BUNDLE_ID="com.google.Chrome"
app_path=$(/usr/bin/mdfind "kMDItemCFBundleIdentifier == '$BUNDLE_ID'" 2>/dev/null | /usr/bin/head -n 1)
if [ -z "$app_path" ]; then
    exit 0
fi
/usr/bin/defaults read "$app_path/Contents/Info.plist" CFBundleShortVersionString 2>/dev/null
```

### Windows — installed app version (by DisplayName)

- Platform: Windows, Query: POWERSHELL, Response: STRING, Context: SYSTEM
- Name pattern: `Windows.inventory.<appname>_version`

Replace the `-like` pattern with the app's DisplayName. Checks both 64-bit and 32-bit uninstall registry keys.

```powershell
$name = '*Google Chrome*'
$paths = @(
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
$app = Get-ItemProperty -Path $paths -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -like $name } |
    Select-Object -First 1
if ($app) { $app.DisplayVersion }
```

### macOS — free disk space in GB

- Platform: macOS, Query: BASH, Response: INTEGER, Context: SYSTEM
- Name: `macOS.inventory.free_disk_gb`

```bash
#!/bin/bash
/bin/df -g / | /usr/bin/awk 'NR==2 {print $4}'
```

### Windows — free disk space in GB

- Platform: Windows, Query: POWERSHELL, Response: INTEGER, Context: SYSTEM
- Name: `Windows.inventory.free_disk_gb`

```powershell
$drive = $env:SystemDrive
$vol = Get-Volume -DriveLetter $drive.TrimEnd(':')
[int]($vol.SizeRemaining / 1GB)
```

---

## Certificates & identity

### macOS — days until system keychain cert expiry

- Platform: macOS, Query: BASH, Response: INTEGER, Context: SYSTEM
- Name pattern: `macOS.certs.<certname>_days_to_expiry`

Replace `CERT_CN` with the common name of the cert. Returns days until expiry (negative if already expired). Requires the cert to be in the System keychain.

```bash
#!/bin/bash
CERT_CN="My Corp Root CA"
expiry=$(/usr/bin/security find-certificate -c "$CERT_CN" -p /Library/Keychains/System.keychain 2>/dev/null | \
    /usr/bin/openssl x509 -noout -enddate 2>/dev/null | \
    /usr/bin/cut -d= -f2)
if [ -z "$expiry" ]; then
    exit 0
fi
expiry_epoch=$(/bin/date -j -f "%b %d %H:%M:%S %Y %Z" "$expiry" "+%s" 2>/dev/null)
if [ -z "$expiry_epoch" ]; then
    exit 0
fi
now_epoch=$(/bin/date "+%s")
echo $(( (expiry_epoch - now_epoch) / 86400 ))
```

### Windows — days until LocalMachine cert expiry

- Platform: Windows, Query: POWERSHELL, Response: INTEGER, Context: SYSTEM
- Name pattern: `Windows.certs.<certname>_days_to_expiry`

Replace the `-match` pattern with the cert's subject identifier.

```powershell
$subjectPattern = 'CN=My Corp Root CA'
$cert = Get-ChildItem -Path Cert:\LocalMachine\My -ErrorAction SilentlyContinue |
    Where-Object { $_.Subject -match $subjectPattern } |
    Sort-Object NotAfter -Descending |
    Select-Object -First 1
if ($cert) {
    [int]($cert.NotAfter - (Get-Date)).TotalDays
}
```
