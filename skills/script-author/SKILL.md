---
name: script-author
description: Author Workspace ONE UEM scripts — code that runs on managed devices to install, remediate, enforce, or clean up state. Use whenever the user wants to create, design, write, or scaffold a UEM script (install Homebrew, clear quarantine attributes, enforce a registry key, restart a service, remove malware, apply a config change, or any other action that modifies device state) on macOS, Windows, or Linux. Also use when the user says "push this out to my fleet," "remediate X on my devices," "make sure Y is the case on every Mac," or any variation where the goal is to change device state via a Workspace ONE-delivered script. Pair with sensor-author for detection and openclaw-style-detection for detect+remediate workflows.
---

# Script Author

A UEM script is code that UEM runs on a managed device to *do* something — install software, change configuration, remediate a known issue, clean up state. Scripts are the action arm of UEM; they complement sensors (which report state) and profiles (which declare desired state at the MDM level).

This skill exists because authoring a good UEM script requires several decisions that interact in non-obvious ways (platform, language, execution context, idempotence, timeout), and because the `uem_create_script` tool currently has a known HTTP 400 bug on enum validation that requires a specific workaround. The skill walks the decisions, points at the working tool path, and lands with the right call.

## Scripts vs sensors vs profiles

Before authoring, sanity-check the shape of the problem. The three artifact types have distinct purposes and it's common for users to conflate them:

- **Script** — an *action*. Changes device state: installs, remediates, enforces, cleans up. Runs on a schedule or on-demand via Smart Group assignment. Can be run repeatedly if designed to be idempotent.
- **Sensor** — a *probe*. Reports a single typed value back on a schedule. Read-only by design. See the `sensor-author` skill. If the user says "sensor" but describes an action (install, clear, fix, enforce), they want a script.
- **Profile** — a *declaration*. Tells UEM the desired MDM-level state and lets UEM enforce it through the MDM framework (e.g. "WiFi must be configured this way," "FileVault must be on"). Profiles are the right layer when MDM has a native payload for the thing — it's more durable and auditable than scripting the same outcome.

Rule of thumb: if there's a profile payload that does the thing, use the profile. If the thing is outside MDM's reach (unstage a quarantined app, clear a specific registry key, run a vendor installer), it's a script. If you want to *check* the thing, it's a sensor. If you want to detect and then fix, it's a sensor + script pair (see `openclaw-style-detection`).

When the user's ask is ambiguous ("make sure Homebrew is installed"), don't guess — ask whether they want to *report* the state (sensor) or *enforce* it (script). Getting this wrong means either a sensor with dangerous side effects, a script with no visible outcome, or a profile that doesn't exist for the payload.

## The four decisions

Every script is defined by four choices. Work through them in this order before writing the script body.

### 1. Platform

One of `macOS`, `Windows`, `Linux`. These map to UEM's internal values `APPLE_OSX`, `WIN_RT`, `LINUX` — worth remembering because those are the values that appear in exported JSON and that the round-trip path needs.

A script targets exactly one platform. A "cross-platform" remediation is two scripts, one per platform, usually assigned to two Smart Groups that compose upward.

### 2. Script type (language)

- **macOS**: `BASH` or `ZSH` for shell; `PYTHON` for anything needing real parsing. Zsh is the default shell on modern macOS but bash is more portable across older/mixed fleets and bash 3.2 is preinstalled everywhere. Python3 is *not* preinstalled on recent macOS — don't assume it, or if you use it, check for it at the top.
- **Windows**: `POWERSHELL`. That's effectively the only option that belongs in UEM — batch/cmd is legacy.
- **Linux**: `BASH` or `PYTHON`.

Match the language to what's reliably installed across the target fleet. A script that crashes because `python3` isn't installed is indistinguishable from a script that ran but did nothing.

### 3. Execution context

`SYSTEM` or `USER`. Default is `SYSTEM`.

- **SYSTEM** — runs as root (macOS/Linux) or SYSTEM (Windows). Use for anything touching system state: installing packages, writing to `/Library/` or `HKLM:`, restarting services, modifying launchd or scheduled tasks.
- **USER** — runs as the logged-in user. Use for anything in user space: user defaults, user login items, per-user app preferences.

The trap here is different from sensors. With sensors, getting the context wrong usually means you read someone else's state. With scripts, getting the context wrong can mean permission-denied failures (trying to write `/etc/` as USER) or writing to root's home instead of the user's (`~/` as SYSTEM is `/var/root/` on macOS — not what you want).

Rule of thumb: if it needs elevated permissions or touches system-wide state, SYSTEM. If it's per-user configuration, USER.

### 4. Idempotence (critical)

A script that UEM assigns to a Smart Group may run many times on the same device — when the device check-in fires, when the assignment is updated, when the user triggers it manually, when the compliance engine re-evaluates. **Idempotent scripts are safe to re-run; non-idempotent scripts cause drift, duplicate installs, or worse.**

Idempotence is not a property UEM enforces; it's a property you build into the script. Concretely:

- **Install scripts**: check if the thing is already installed and exit 0 without action if so. Don't blindly run installers.
- **Configuration scripts**: check current state first. Only write if the value differs.
- **Cleanup scripts**: use flags that treat "already gone" as success (`rm -f`, `Remove-Item -ErrorAction SilentlyContinue`).
- **Service scripts**: check the service's current state before starting/stopping it.

A well-written UEM script runs many times, but only *does* anything the first time. Each subsequent run is a confirmation, not a repeat action.

The UEM JSON exposes this via an `is_idempotent` field on scripts. Setting this to `true` is a promise about your script's behaviour — UEM uses it to decide whether to re-run the script on assignment updates. Be honest about it: setting `true` on a non-idempotent script causes subtle bugs.

## Writing the script

### The output expectation

Unlike sensors, UEM does not parse a script's stdout into a typed value. It captures stdout and stderr for logs, and the exit code determines success/failure.

- **Exit 0**: success. UEM records the script as having run successfully.
- **Non-zero exit**: failure. UEM logs the script as failed and may retry depending on assignment config.

Practical implications:

- Be explicit about exit codes. `exit 0` at the end for clear-success paths, `exit 1` (or more specific codes) for error paths.
- Do not suppress errors blindly (`|| true` on everything) just to force a clean exit. UEM's failure signal is useful — preserve it.
- Logs are your debugging surface. Write clear stdout/stderr at key decision points ("Homebrew already installed, exiting 0" / "Installing Homebrew..."). These show up in the device's script run history.

### Defensive patterns

Scripts run across a fleet will encounter every edge case the fleet contains. A few patterns that earn their keep:

- **Check for prerequisites up front.** If the script needs `brew`, `jq`, or a specific PowerShell module, check and either install, skip gracefully, or exit with a clear code.
- **Pin absolute paths.** `$PATH` in UEM's script execution environment is minimal. Use `/usr/local/bin/brew`, `/usr/bin/defaults`, full cmdlet names.
- **Wrap long operations in timeouts.** If a download or install can hang, cap it. UEM has its own timeout (default 300s) but an in-script timeout gives you a clean failure rather than an opaque one.
- **Log a machine-identifying header.** `hostname`, `whoami`, and date at the top of the script make troubleshooting across a fleet tractable.
- **Be explicit about the "already done" path.** An idempotent script that exits early on the happy path should say so in its output — not silence.

## Creating the script

There are two tool paths. **Read this section carefully — the first path currently has a known bug, and the right default is the second.**

### The known enum-validation bug

`uem_create_script` accepts friendly platform names (`macOS`, `Windows`, `Linux`) and friendly script types (`BASH`, `POWERSHELL`, `PYTHON`, `ZSH`). Internally, it needs to resolve these to API-native enum values (`APPLE_OSX`, `WIN_RT`, `LINUX`). Some combinations currently fail that resolution step and the API returns HTTP 400 with an unresolved-enum error — even for combinations that should be valid.

The workaround is to use `uem_create_script_from_json` with a minimal template. The round-trip tool bypasses the friendly-name resolution and takes the API-native values directly, which sidesteps the bug.

### Preferred path: `uem_create_script_from_json`

Build a JSON body in the shape that `uem_get_script` returns and pass it to `uem_create_script_from_json`. Minimal template:

```json
{
  "name": "My.script.name",
  "description": "What this script does and why.",
  "platform": "APPLE_OSX",
  "script_type": "BASH",
  "organization_group_uuid": "<og-uuid-here>",
  "script_data": "<base64-encoded-script-content>",
  "execution_context": "SYSTEM",
  "is_idempotent": true,
  "timeout": 300,
  "allowed_in_catalog": false,
  "user_interaction": false,
  "script_variables": []
}
```

Fields in detail:

- `platform`: use API-native values — `APPLE_OSX`, `WIN_RT`, or `LINUX`. Not the friendly names.
- `script_type`: `BASH`, `POWERSHELL`, `PYTHON`, or `ZSH`.
- `script_data`: the script source code, base64-encoded. Don't include a BOM; LF line endings (not CRLF) work reliably for cross-platform scripts.
- `organization_group_uuid`: the OG where the script should live. Ask the user if they haven't specified — don't guess.
- `is_idempotent`: set based on the script's actual behaviour. `true` if the script is safe to re-run (it should be).
- `timeout`: seconds. 300 is the UEM default; raise for lengthy installers, lower for quick checks.
- `allowed_in_catalog`: `false` for remediation/enforcement; `true` only if you want the script to appear in the self-service Workspace ONE Catalog.
- `user_interaction`: `false` almost always. `true` only if the script legitimately needs a logged-in user and a UI session.
- `script_variables`: `[]` unless you're parameterising. See the parameterisation section below.
- Read-only fields (`script_uuid`, `version`, `assignment_count`, `created_or_modified_*`) are stripped automatically — leave them out.

To base64-encode the script content, use whatever's at hand: `base64 < script.sh` on macOS/Linux, `[Convert]::ToBase64String([IO.File]::ReadAllBytes('script.ps1'))` in PowerShell, or a language equivalent. The content should be the raw script — shebang and all.

### Fallback path: `uem_create_script`

Once the enum bug is resolved, `uem_create_script` is the friendlier interface. Its contract accepts plain-text script content (no base64), friendly platform names, and handles the encoding internally. If you're reading this skill after the bug is fixed or for a combination known to work, reach for this tool first — it's cleaner.

If you try `uem_create_script` and get an HTTP 400 with an enum-related error, fall back to `uem_create_script_from_json` without debugging further — the bug is not in your script content, it's in the tool path.

## Reference material

Three reference files are available. Read them into context only when relevant — they're too long to keep loaded by default.

- **`references/library.md`** — a cookbook of canonical scripts: install-if-missing, service enforcement, registry key enforcement, file cleanup, macOS defaults enforcement, and more. **Check the library's table of contents first for any script ask** — if there's a name match or close adjacency, adapt a library entry rather than starting from scratch. The entries already encode idempotence and the right execution context.

- **`references/idempotence-patterns.md`** — read this when authoring a non-trivial script that will be re-run by the assignment engine. Covers the six most common idempotence patterns (check-then-install, configure-if-different, service convergence, etc.) with concrete examples in bash and PowerShell.

- **`references/json-template.md`** — a ready-to-fill JSON body for `uem_create_script_from_json`, plus notes on how to base64-encode scripts in different contexts and how to parameterise with `script_variables`.

## Worked example

User asks: *"I want to push out a script that makes sure Homebrew is installed on all our Macs, since we use it for other tooling."*

Walking the four decisions:

1. **Platform**: macOS (`APPLE_OSX` in the JSON).
2. **Script type**: BASH — Homebrew's official installer is a bash script, no reason to reach for anything else.
3. **Execution context**: SYSTEM — Homebrew installs to `/opt/homebrew` (Apple Silicon) or `/usr/local` (Intel), both of which need root. Note that Homebrew itself prefers to be *used* as a non-root user, but installation needs root to set up the directories; the script sorts out permissions after install.
4. **Idempotence**: yes, this script must be idempotent — UEM may run it many times. Check for existing install first.

Script:

```bash
#!/bin/bash
set -eo pipefail

LOG_PREFIX="[homebrew-install]"
echo "$LOG_PREFIX host=$(hostname) user=$(whoami) date=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

# Detect the expected Homebrew prefix based on architecture
if [ "$(/usr/bin/arch)" = "arm64" ]; then
    BREW_PREFIX="/opt/homebrew"
else
    BREW_PREFIX="/usr/local"
fi

# Idempotence check: if brew is already installed, exit 0
if [ -x "${BREW_PREFIX}/bin/brew" ]; then
    echo "$LOG_PREFIX Homebrew already installed at ${BREW_PREFIX}. Exiting."
    exit 0
fi

echo "$LOG_PREFIX Installing Homebrew to ${BREW_PREFIX}..."

# The official installer requires NONINTERACTIVE=1 for unattended runs
NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Verify
if [ -x "${BREW_PREFIX}/bin/brew" ]; then
    echo "$LOG_PREFIX Install succeeded."
    exit 0
else
    echo "$LOG_PREFIX Install did not produce expected binary at ${BREW_PREFIX}/bin/brew." >&2
    exit 1
fi
```

Tool call: `uem_create_script_from_json` with a body like:

```json
{
  "name": "macOS.install.homebrew",
  "description": "Idempotently installs Homebrew to /opt/homebrew (arm64) or /usr/local (x86_64). No-op if already installed.",
  "platform": "APPLE_OSX",
  "script_type": "BASH",
  "organization_group_uuid": "<user's OG UUID>",
  "script_data": "<base64 of the script above — see references/json-template.md for encoding>",
  "execution_context": "SYSTEM",
  "is_idempotent": true,
  "timeout": 600,
  "allowed_in_catalog": false,
  "user_interaction": false,
  "script_variables": []
}
```

To produce the `script_data` value: run the script content through `base64 | tr -d '\n'` (macOS/Linux) or the PowerShell equivalent. The output must be a single line with no embedded newlines — JSON parsers will reject a multi-line string.

Note `timeout: 600` — the Homebrew installer downloads a fair amount and can exceed the 300-second default on slow networks.

Assign to a Smart Group containing macOS devices. Optionally pair with a sensor that reports Homebrew's installed version (`macOS.inventory.brew_version`) so you can verify coverage via Smart Group criteria.
