# Idempotence patterns

A UEM script that's assigned to a Smart Group can be triggered many times on the same device. An idempotent script handles that cleanly — it checks current state before acting, and only acts if the state is not already what it should be. A non-idempotent script causes drift: duplicate installs, log spam, unnecessary reboots, or in the worst case, corrupted state.

This file catalogues the six most common idempotence patterns. For each, the shape of the check, the shape of the action, and concrete examples in bash and PowerShell.

## Pattern 1: Check-then-install

**Use when**: the script installs software.

**Shape**: check whether the software is already installed via a reliable signal (binary present at expected path, package registered with the OS package manager, registry key present). If yes, exit 0. If no, install, then verify.

**bash (macOS — VS Code as example)**:

```bash
APP_PATH="/Applications/Visual Studio Code.app"
if [ -d "$APP_PATH" ]; then
    echo "VS Code already installed at $APP_PATH. Exiting."
    exit 0
fi
echo "VS Code not found. Installing..."
# ... installer commands ...
if [ -d "$APP_PATH" ]; then
    exit 0
else
    echo "Install did not produce expected app bundle." >&2
    exit 1
fi
```

**PowerShell (Windows — check uninstall registry for a DisplayName)**:

```powershell
$name = '*Visual Studio Code*'
$paths = @(
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
$installed = Get-ItemProperty -Path $paths -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -like $name }
if ($installed) {
    Write-Output "VS Code already installed. Exiting."
    exit 0
}
Write-Output "VS Code not found. Installing..."
# ... installer commands ...
```

**Gotcha**: don't use "has this installer run" as the check (e.g., presence of a log file). Use "is the software actually installed," because the installer may have failed halfway last time and you want the script to try again.

## Pattern 2: Configure-if-different

**Use when**: the script sets a configuration value (registry key, defaults value, config file line).

**Shape**: read current value. Compare to desired value. Write only if different. This matters because writing unconditionally can trigger side effects — LaunchAgents reload, services restart, the registry hive gets a modification timestamp bump.

**bash (macOS defaults)**:

```bash
CURRENT=$(/usr/bin/defaults read /Library/Preferences/com.apple.loginwindow RetriesUntilHint 2>/dev/null || echo "")
DESIRED="0"
if [ "$CURRENT" = "$DESIRED" ]; then
    echo "RetriesUntilHint already $DESIRED. No action."
    exit 0
fi
echo "Setting RetriesUntilHint from '$CURRENT' to '$DESIRED'."
/usr/bin/defaults write /Library/Preferences/com.apple.loginwindow RetriesUntilHint -int "$DESIRED"
```

**PowerShell (registry)**:

```powershell
$path = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System'
$name = 'InactivityTimeoutSecs'
$desired = 900
$current = (Get-ItemProperty -Path $path -Name $name -ErrorAction SilentlyContinue).$name
if ($current -eq $desired) {
    Write-Output "$name already $desired. No action."
    exit 0
}
Write-Output "Setting $name from '$current' to '$desired'."
New-ItemProperty -Path $path -Name $name -Value $desired -PropertyType DWord -Force | Out-Null
```

**Gotcha**: empty string vs null vs absent-key are three different states. Handle them explicitly — `"" -eq $null` behaves differently in PowerShell than in bash.

## Pattern 3: Service convergence

**Use when**: the script ensures a service is in a specific state (running, stopped, disabled).

**Shape**: query current service state. Compare. Only act if different. Set start-up type separately from the running state.

**PowerShell**:

```powershell
$svcName = 'Spooler'
$desiredStatus = 'Running'
$desiredStartType = 'Automatic'

$svc = Get-Service -Name $svcName -ErrorAction SilentlyContinue
if (-not $svc) {
    Write-Error "Service $svcName not found."
    exit 1
}

# Converge start type
if ($svc.StartType -ne $desiredStartType) {
    Write-Output "Setting $svcName start type: $($svc.StartType) -> $desiredStartType"
    Set-Service -Name $svcName -StartupType $desiredStartType
}

# Converge running state
$svc.Refresh()
if ($svc.Status -ne $desiredStatus) {
    Write-Output "Setting $svcName state: $($svc.Status) -> $desiredStatus"
    if ($desiredStatus -eq 'Running') {
        Start-Service -Name $svcName
    } else {
        Stop-Service -Name $svcName -Force
    }
}
```

**bash (launchd on macOS)**:

```bash
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
```

## Pattern 4: Cleanup with tolerant deletion

**Use when**: the script removes files, registry keys, or other artifacts.

**Shape**: use flags that treat "already gone" as success. Don't let `file-not-found` fail a cleanup script — that's the expected happy-path state after the first run.

**bash**:

```bash
TARGETS=(
    "/Library/LaunchDaemons/com.vendor.old.plist"
    "/Library/Application Support/Vendor/"
    "/usr/local/bin/vendor-cli"
)
for t in "${TARGETS[@]}"; do
    if [ -e "$t" ]; then
        echo "Removing $t"
        rm -rf "$t"
    fi
done
exit 0
```

**PowerShell**:

```powershell
$targets = @(
    'HKLM:\SOFTWARE\VendorCorp\OldProduct',
    'C:\Program Files\VendorCorp\OldProduct',
    'C:\ProgramData\VendorCorp'
)
foreach ($t in $targets) {
    if (Test-Path $t) {
        Write-Output "Removing $t"
        Remove-Item -Path $t -Recurse -Force -ErrorAction SilentlyContinue
    }
}
exit 0
```

**Gotcha**: `rm -rf /` levels of mistake are exactly the kind of thing UEM scripts can propagate at fleet scale. Be paranoid about target paths — hardcode them where you can, and validate any variable that ends up in a delete command.

## Pattern 5: Append-if-missing (config files)

**Use when**: the script adds a line to a config file (`/etc/hosts`, shell profile, sudoers).

**Shape**: check for the line before appending. Use a distinctive marker.

**bash**:

```bash
CONFIG="/etc/sudoers.d/company"
MARKER="# managed-by-ws1"
LINE="%admin ALL=(ALL) NOPASSWD: /usr/bin/softwareupdate"

if [ -f "$CONFIG" ] && grep -q "$MARKER" "$CONFIG"; then
    echo "Already configured."
    exit 0
fi

{
    echo "$MARKER"
    echo "$LINE"
} >> "$CONFIG"
chmod 440 "$CONFIG"
/usr/sbin/visudo -c -f "$CONFIG" || {
    echo "Validation failed, rolling back." >&2
    rm -f "$CONFIG"
    exit 1
}
```

**Gotcha**: appending without checking will append every run. The file grows forever until someone notices.

## Pattern 6: One-shot marker file

**Use when**: the script genuinely should run only once per device (e.g., a migration step that isn't safe to replay).

**Shape**: check for a marker file. If present, exit 0. Otherwise run, then drop the marker.

**bash**:

```bash
MARKER="/var/db/.ws1-migration-v3-done"
if [ -f "$MARKER" ]; then
    echo "Migration already completed on $(cat "$MARKER"). Exiting."
    exit 0
fi

# ... migration steps ...

date -u '+%Y-%m-%dT%H:%M:%SZ' > "$MARKER"
echo "Migration complete. Marker written to $MARKER."
```

**Gotcha**: marker-file idempotence is fragile. The marker can be deleted, the device can be reimaged, the marker can get out of sync with the actual state. Prefer Patterns 1–5 when the underlying state itself is queryable. Use marker files only when you genuinely cannot observe the "was this done" state any other way — e.g., a migration that transforms data in place.

## Deciding between patterns

| Script type | Use pattern |
|---|---|
| Install software | 1 (check-then-install) |
| Uninstall software | 4 (tolerant deletion) + Pattern 1 shape inverted |
| Set a config value | 2 (configure-if-different) |
| Ensure a service state | 3 (service convergence) |
| Remove files / registry keys | 4 (tolerant deletion) |
| Add a line to a config file | 5 (append-if-missing) |
| Migrate data in place | 6 (one-shot marker) |

A complex script may combine patterns: install software (P1), configure it (P2), and ensure its service runs (P3). That's fine — chain them with clear logging at each step.
