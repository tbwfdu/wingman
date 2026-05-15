# Script library

Ready-to-adapt reference scripts covering the most common UEM use cases. Each entry includes the four decisions (platform, script_type, execution_context, idempotence pattern) and the script body.

Adapt these rather than writing from scratch when the user's ask is close to something in the library — the tribal-knowledge parts (which idempotence pattern to use, where the gotchas are, what prerequisites to check) are already baked in.

## Table of contents

**Install**
- [macOS — install Homebrew](#macos--install-homebrew)
- [macOS — install a pkg from a URL](#macos--install-a-pkg-from-a-url)
- [Windows — install an MSI from a URL](#windows--install-an-msi-from-a-url)

**Configuration enforcement**
- [macOS — set a defaults value at system level](#macos--set-a-defaults-value-at-system-level)
- [Windows — ensure a registry DWORD value](#windows--ensure-a-registry-dword-value)
- [macOS — ensure a LaunchDaemon is loaded](#macos--ensure-a-launchdaemon-is-loaded)
- [Windows — ensure a service is running and set to automatic](#windows--ensure-a-service-is-running-and-set-to-automatic)

**Remediation**
- [macOS — clear the quarantine attribute in a directory](#macos--clear-the-quarantine-attribute-in-a-directory)
- [Windows — force Group Policy refresh](#windows--force-group-policy-refresh)
- [macOS — restart a misbehaving launchd job](#macos--restart-a-misbehaving-launchd-job)

**Cleanup**
- [macOS — remove a known vendor's leftover files](#macos--remove-a-known-vendors-leftover-files)
- [Windows — remove a vendor's registry footprint](#windows--remove-a-vendors-registry-footprint)

---

## Install

### macOS — install Homebrew

- Platform: APPLE_OSX, Type: BASH, Context: SYSTEM, Idempotent: yes (Pattern 1)
- Suggested name: `macOS.install.homebrew`
- Timeout: 600

```bash
#!/bin/bash
set -eo pipefail
LOG="[homebrew-install]"
echo "$LOG host=$(hostname) date=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

if [ "$(/usr/bin/arch)" = "arm64" ]; then
    BREW_PREFIX="/opt/homebrew"
else
    BREW_PREFIX="/usr/local"
fi

if [ -x "${BREW_PREFIX}/bin/brew" ]; then
    echo "$LOG Homebrew already installed at ${BREW_PREFIX}. Exiting."
    exit 0
fi

echo "$LOG Installing Homebrew to ${BREW_PREFIX}..."
NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

if [ -x "${BREW_PREFIX}/bin/brew" ]; then
    echo "$LOG Install succeeded."
    exit 0
else
    echo "$LOG Install failed." >&2
    exit 1
fi
```

### macOS — install a pkg from a URL

- Platform: APPLE_OSX, Type: BASH, Context: SYSTEM, Idempotent: yes (Pattern 1)
- Suggested name pattern: `macOS.install.<product>`
- Timeout: 600

Replace `PKG_URL`, `EXPECTED_RECEIPT`, and optionally the sha256 check. The receipt check uses macOS's `pkgutil` to detect prior installs without relying on filesystem probing.

```bash
#!/bin/bash
set -eo pipefail
LOG="[pkg-install]"
PKG_URL="https://example.com/company-cli.pkg"
EXPECTED_RECEIPT="com.example.company-cli"
EXPECTED_SHA256=""  # optional; leave empty to skip

echo "$LOG host=$(hostname) date=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

if /usr/sbin/pkgutil --pkg-info "$EXPECTED_RECEIPT" >/dev/null 2>&1; then
    echo "$LOG Receipt $EXPECTED_RECEIPT already present. Exiting."
    exit 0
fi

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT
PKG="$TMPDIR/install.pkg"

echo "$LOG Downloading $PKG_URL..."
curl -fsSL "$PKG_URL" -o "$PKG"

if [ -n "$EXPECTED_SHA256" ]; then
    ACTUAL=$(shasum -a 256 "$PKG" | awk '{print $1}')
    if [ "$ACTUAL" != "$EXPECTED_SHA256" ]; then
        echo "$LOG sha256 mismatch: expected $EXPECTED_SHA256, got $ACTUAL" >&2
        exit 1
    fi
fi

echo "$LOG Installing..."
/usr/sbin/installer -pkg "$PKG" -target /
exit $?
```

### Windows — install an MSI from a URL

- Platform: WIN_RT, Type: POWERSHELL, Context: SYSTEM, Idempotent: yes (Pattern 1)
- Suggested name pattern: `Windows.install.<product>`
- Timeout: 600

Replace `$msiUrl` and `$displayNamePattern`. The check uses the uninstall registry to detect prior installs.

```powershell
$msiUrl = 'https://example.com/company-cli.msi'
$displayNamePattern = '*Company CLI*'

$paths = @(
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
$installed = Get-ItemProperty -Path $paths -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -like $displayNamePattern }

if ($installed) {
    Write-Output "Already installed: $($installed.DisplayName) $($installed.DisplayVersion). Exiting."
    exit 0
}

$temp = Join-Path $env:TEMP ([IO.Path]::GetRandomFileName() + '.msi')
try {
    Write-Output "Downloading $msiUrl..."
    Invoke-WebRequest -Uri $msiUrl -OutFile $temp -UseBasicParsing

    Write-Output "Installing $temp..."
    $p = Start-Process msiexec.exe -ArgumentList "/i `"$temp`" /qn /norestart" -Wait -PassThru
    if ($p.ExitCode -ne 0 -and $p.ExitCode -ne 3010) {
        # 3010 = success with reboot pending
        Write-Error "msiexec exit code $($p.ExitCode)"
        exit 1
    }
    Write-Output "Install complete (exit $($p.ExitCode))."
    exit 0
}
finally {
    Remove-Item $temp -Force -ErrorAction SilentlyContinue
}
```

---

## Configuration enforcement

### macOS — set a defaults value at system level

- Platform: APPLE_OSX, Type: BASH, Context: SYSTEM, Idempotent: yes (Pattern 2)
- Suggested name pattern: `macOS.enforce.<domain>_<key>`

Example: set login-window retries-until-hint to 0.

```bash
#!/bin/bash
DOMAIN="/Library/Preferences/com.apple.loginwindow"
KEY="RetriesUntilHint"
DESIRED="0"

CURRENT=$(/usr/bin/defaults read "$DOMAIN" "$KEY" 2>/dev/null || echo "")

if [ "$CURRENT" = "$DESIRED" ]; then
    echo "$KEY already $DESIRED. No action."
    exit 0
fi

echo "Setting $KEY from '$CURRENT' to '$DESIRED'."
/usr/bin/defaults write "$DOMAIN" "$KEY" -int "$DESIRED"
```

### Windows — ensure a registry DWORD value

- Platform: WIN_RT, Type: POWERSHELL, Context: SYSTEM, Idempotent: yes (Pattern 2)
- Suggested name pattern: `Windows.enforce.<area>_<key>`

Example: ensure screen inactivity lock at 15 minutes.

```powershell
$path = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System'
$name = 'InactivityTimeoutSecs'
$desired = 900

if (-not (Test-Path $path)) {
    New-Item -Path $path -Force | Out-Null
}

$current = (Get-ItemProperty -Path $path -Name $name -ErrorAction SilentlyContinue).$name
if ($current -eq $desired) {
    Write-Output "$name already $desired. No action."
    exit 0
}

Write-Output "Setting $name: $current -> $desired"
New-ItemProperty -Path $path -Name $name -Value $desired -PropertyType DWord -Force | Out-Null
exit 0
```

### macOS — ensure a LaunchDaemon is loaded

- Platform: APPLE_OSX, Type: BASH, Context: SYSTEM, Idempotent: yes (Pattern 3)
- Suggested name pattern: `macOS.service.<label>_loaded`

```bash
#!/bin/bash
LABEL="com.company.updater"
PLIST="/Library/LaunchDaemons/${LABEL}.plist"

if [ ! -f "$PLIST" ]; then
    echo "LaunchDaemon plist missing at $PLIST." >&2
    exit 1
fi

if /bin/launchctl list | grep -q "$LABEL"; then
    echo "LaunchDaemon $LABEL already loaded."
    exit 0
fi

echo "Loading LaunchDaemon $LABEL."
/bin/launchctl load "$PLIST"
exit $?
```

### Windows — ensure a service is running and set to automatic

- Platform: WIN_RT, Type: POWERSHELL, Context: SYSTEM, Idempotent: yes (Pattern 3)
- Suggested name pattern: `Windows.service.<n>_running`

```powershell
$svcName = 'Spooler'
$desiredStatus = 'Running'
$desiredStartType = 'Automatic'

$svc = Get-Service -Name $svcName -ErrorAction SilentlyContinue
if (-not $svc) {
    Write-Error "Service $svcName not found."
    exit 1
}

if ($svc.StartType -ne $desiredStartType) {
    Write-Output "StartType: $($svc.StartType) -> $desiredStartType"
    Set-Service -Name $svcName -StartupType $desiredStartType
}

$svc.Refresh()
if ($svc.Status -ne $desiredStatus) {
    Write-Output "Status: $($svc.Status) -> $desiredStatus"
    if ($desiredStatus -eq 'Running') {
        Start-Service -Name $svcName
    } else {
        Stop-Service -Name $svcName -Force
    }
} else {
    Write-Output "$svcName already $desiredStatus."
}
exit 0
```

---

## Remediation

### macOS — clear the quarantine attribute in a directory

- Platform: APPLE_OSX, Type: BASH, Context: SYSTEM, Idempotent: yes (no-op if nothing is quarantined)
- Suggested name: `macOS.remediate.clear_quarantine_applications`

Uses a depth-limited `find` for performance — walking all of /Applications can be slow on devices with large bundles.

```bash
#!/bin/bash
TARGET_DIR="/Applications"
echo "Clearing com.apple.quarantine on items under $TARGET_DIR"

# -maxdepth 3 is enough to cover /Applications/App.app/Contents/* without diving deep.
/usr/bin/find "$TARGET_DIR" -maxdepth 3 \
    -exec /usr/bin/xattr -d com.apple.quarantine {} \; 2>/dev/null || true

echo "Done."
exit 0
```

### Windows — force Group Policy refresh

- Platform: WIN_RT, Type: POWERSHELL, Context: SYSTEM, Idempotent: yes (safe to re-run)
- Suggested name: `Windows.remediate.gpupdate_force`
- Timeout: 300

```powershell
Write-Output "Running gpupdate /force..."
$result = & gpupdate.exe /force 2>&1
Write-Output $result

if ($LASTEXITCODE -ne 0) {
    Write-Error "gpupdate returned $LASTEXITCODE"
    exit $LASTEXITCODE
}
exit 0
```

### macOS — restart a misbehaving launchd job

- Platform: APPLE_OSX, Type: BASH, Context: SYSTEM, Idempotent: yes
- Suggested name pattern: `macOS.remediate.restart_<label>`

Useful as a remediation paired with a sensor that reports "service X not responsive."

```bash
#!/bin/bash
LABEL="com.company.worker"

if ! /bin/launchctl list | grep -q "$LABEL"; then
    echo "LaunchDaemon $LABEL is not loaded — nothing to restart."
    exit 0
fi

echo "Kickstarting $LABEL..."
/bin/launchctl kickstart -k "system/$LABEL"
exit $?
```

---

## Cleanup

### macOS — remove a known vendor's leftover files

- Platform: APPLE_OSX, Type: BASH, Context: SYSTEM, Idempotent: yes (Pattern 4)
- Suggested name pattern: `macOS.cleanup.<vendor>_leftovers`

```bash
#!/bin/bash
echo "Removing stale VendorCorp artifacts..."

TARGETS=(
    "/Library/LaunchDaemons/com.vendorcorp.agent.plist"
    "/Library/LaunchAgents/com.vendorcorp.ui.plist"
    "/Library/Application Support/VendorCorp"
    "/Library/Preferences/com.vendorcorp.agent.plist"
    "/usr/local/bin/vendorcorp-cli"
)

for t in "${TARGETS[@]}"; do
    if [ -e "$t" ]; then
        echo "  Removing $t"
        rm -rf "$t"
    fi
done

# Per-user cleanup
for home in $(dscl . list /Users NFSHomeDirectory 2>/dev/null | awk '$1 !~ /^_/ {print $2}'); do
    [ -d "$home" ] || continue
    for rel in "Library/Application Support/VendorCorp" "Library/Preferences/com.vendorcorp.ui.plist"; do
        path="$home/$rel"
        if [ -e "$path" ]; then
            echo "  Removing $path"
            rm -rf "$path"
        fi
    done
done

echo "Done."
exit 0
```

### Windows — remove a vendor's registry footprint

- Platform: WIN_RT, Type: POWERSHELL, Context: SYSTEM, Idempotent: yes (Pattern 4)
- Suggested name pattern: `Windows.cleanup.<vendor>_registry`

```powershell
$keys = @(
    'HKLM:\SOFTWARE\VendorCorp\OldProduct',
    'HKLM:\SOFTWARE\WOW6432Node\VendorCorp\OldProduct',
    'HKCU:\SOFTWARE\VendorCorp'
)

foreach ($k in $keys) {
    if (Test-Path $k) {
        Write-Output "Removing $k"
        Remove-Item -Path $k -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Output "Done."
exit 0
```
