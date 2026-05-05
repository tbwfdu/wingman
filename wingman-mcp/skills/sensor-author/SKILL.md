---
name: sensor-author
description: Author Workspace ONE UEM sensors — scripts that run on managed devices and return a typed value for reporting, Smart Group criteria, or compliance. Use whenever the user wants to create, design, write, or scaffold a UEM sensor (battery health, FileVault status, BitLocker state, Rosetta presence, installed app version, last patch date, certificate expiry, custom telemetry, etc.) on macOS, Windows, or Linux. Also use when the user says "check X on my devices," "report whether Y is installed," "expose Z as a Smart Group attribute," or any variation where the end goal is a device-side probe whose result shows up in UEM. Pair with sensor-deploy or openclaw-style-detection for assignment and remediation workflows.
---

# Sensor Author

A sensor is a short script that runs on a managed device on a schedule and reports a single typed value back to UEM. That value then shows up in device records, Intelligence dashboards, and — most usefully — as a Smart Group criterion. Sensors are the cleanest way to expose anything you can query from the OS as a first-class attribute of the device.

This skill exists because authoring a sensor well requires getting several dimensions right at once (platform, language, return type, execution context, output contract) and one wrong choice silently produces a useless sensor. The skill walks through those decisions in order, then hands over a working script and the right tool call to create it.

## When to reach for a sensor vs something else

Before authoring anything, sanity-check the shape of the problem. The single most important distinction is sensor vs script, because both "run code on the device" and users frequently say "sensor" when they mean "script":

- **Sensor** — a *probe*. Reports a single typed value back on a schedule. Read-only by design. Feeds Smart Groups, Intelligence dashboards, and compliance inputs.
- **Script** (via `uem_create_script` / `uem_create_script_from_json`) — an *action*. Changes device state: installs, remediates, cleans up, configures. Assigned to Smart Groups and run on-demand or on a schedule.
- **Compliance policy** — the *reaction layer*. Sits on top of a sensor (or other signals) to automatically warn, restrict, or wipe.

The sensor/script distinction sounds obvious but the failure mode is common: someone says "I want a sensor that makes sure X is installed" or "a sensor that clears Y." Those are scripts — the verb is "make sure" or "clear," not "report." Two tests to apply:

1. **The side-effects test.** Does the device state change as a result of running this? If yes, it's a script. Sensors run on a schedule (often several times a day) and must be safe to run repeatedly with no impact — anything with side effects does not belong in a sensor.
2. **The output test.** What shows up on the device record after this runs? If the answer is "a value I can filter on in a Smart Group," it's a sensor. If the answer is "nothing, the device is just in a different state now," it's a script.

If the user's ask is really "check X and if it's broken, fix it," that's a sensor + script pair — a detection sensor scopes a Smart Group, and a remediation script is assigned to that group. See the `openclaw-style-detection` skill for that pattern. This skill focuses on the probe half.

When the user's phrasing is ambiguous ("make sure Homebrew is installed"), don't guess — ask them whether they want to *report* the state or *enforce* it. Those are different artifacts and getting it wrong means either a sensor with dangerous side effects or a script that produces no visible outcome.

## The five decisions

Every sensor is defined by five choices. Work through them in this order before writing any script content — getting platform wrong invalidates the language choice, getting response_type wrong invalidates the script's output format, and so on.

### 1. Platform

One of `macOS`, `Windows`, `Linux`. These map to UEM's internal values `APPLE_OSX`, `WIN_RT`, `LINUX`, but `uem_create_sensor` accepts the friendly names and does the mapping.

A sensor targets exactly one platform. If the user wants "FileVault on Macs and BitLocker on Windows," that's two sensors, not one — and usually two Smart Groups that compose upward.

### 2. Query type (language)

Which script language runs on the device:

- **macOS**: `BASH`, `ZSH`, or `PYTHON`. Zsh is the macOS default shell since Catalina, but BASH is fine and more portable across older/mixed fleets. Python is available on older macOS versions but has been removed from system defaults on recent macOS — prefer shell unless you need real parsing.
- **Windows**: `POWERSHELL`. That's effectively the only practical option.
- **Linux**: `BASH` or `PYTHON`.

Match the language to what's reliably installed. The sensor runs on every device in scope — if even 5% of the fleet is missing the interpreter, you get a silently-failing sensor.

### 3. Response type

This is the single most common place to go wrong. The response type tells UEM how to parse and index the script's stdout:

- `STRING` — free text. Safe default, works for anything. Shows up in Smart Groups as string-match criteria (equals, contains, starts with).
- `INTEGER` — whole number. Gives you numeric Smart Group operators (greater than, less than, between). Script must output *only* digits, nothing else.
- `BOOLEAN` — `true` or `false` (lowercase). Best for yes/no probes like "is FileVault on." Script must output exactly `true` or `false`.
- `DATETIME` — ISO 8601 timestamp. Use when you genuinely need date arithmetic in Smart Groups (e.g., "last patched more than 30 days ago"). Script must output a parseable timestamp.

Full detail and the output contract for each type is in `references/response-types.md` — read it if the user needs anything other than STRING, because each non-string type has a specific format the script output has to conform to or the sensor silently breaks.

**Default to STRING when unsure.** You can always parse a string in a Smart Group criterion; you cannot recover a malformed integer.

### 4. Execution context

`SYSTEM` or `USER`. Default is `SYSTEM`.

- **SYSTEM** — runs as root (macOS/Linux) or SYSTEM (Windows). Use for anything touching system state: disk encryption, system preferences, installed packages, hardware, certificates in the system keychain/store.
- **USER** — runs as the logged-in user. Use for anything in user space: user defaults, user-installed apps in `~/Applications`, user keychain items, per-user config files.

A sensor reading `defaults read com.apple.dock` as SYSTEM will return root's dock config, not the user's — that's almost never what you want. Conversely, reading FileVault status as USER will fail on the `fdesetup` permission check.

Process checks are another place this bites: a sensor asking "is Slack running?" for the logged-in user should run as USER, not SYSTEM. SYSTEM will see every process on the box including those of other users and launch daemons, which makes the probe imprecise; USER sees only the logged-in user's processes, which is what the question actually asks.

If in doubt: system state = SYSTEM, user state (preferences, per-user processes, user keychain) = USER.

### 5. Name and description

Sensor names only accept letters, numbers, periods, underscores, and spaces. No hyphens, no slashes, no parentheses. This is a validation constraint on UEM's side, not a soft convention — the tool rejects names that break this rule.

A naming convention pays off once you have more than ~10 sensors. A useful pattern is `<platform>.<domain>.<thing>`, e.g. `macOS.security.filevault_enabled`, `Windows.inventory.installed_office_version`. Pick a pattern early and stick with it.

## Authoring the script

Once the five decisions are made, the script itself should be the smallest possible thing that prints the right value to stdout and exits 0.

### The output contract

UEM captures stdout. That's it. It does not capture stderr, it does not capture exit code semantics beyond "ran or didn't run," and it does not care about anything the script logs to a file. **The last line of stdout is what UEM parses against the declared response_type.**

Practical consequences:

- Keep the script quiet. Suppress informational output. Redirect diagnostics to `/dev/null` or a log file, not stdout.
- Don't print a trailing newline character zoo — `echo` is fine, but don't `printf "Result: %s\n" "$x"` when the response type is INTEGER and you only want the digits.
- If the probe fails to determine the answer (command missing, permission denied, network unreachable), decide deliberately what to emit: an explicit sentinel string (`"unknown"`, `"error"`) is far better than empty output, because empty output makes the device look indistinguishable from "sensor not yet run."

### Defensive patterns

A sensor that runs across a fleet will hit every edge case the fleet contains. Three patterns that save pain:

- **Short-circuit on missing dependencies.** If `jq` isn't installed on the device, detect that early and emit a known sentinel rather than letting the script crash with a parse error.
- **Pin paths.** Don't rely on `$PATH` — the sensor runs in a minimal environment. Use `/usr/bin/defaults`, `/usr/sbin/system_profiler`, etc.
- **Timeout long-running commands.** If a probe can hang (network calls, spotlight queries), wrap it in `timeout` or a PowerShell `-TimeoutSec` so the sensor doesn't stall the agent.

## Creating the sensor

Two tools, pick based on what you have:

- **`uem_create_sensor`** — the friendly path. Give it plain-text script content, name, platform (`macOS`/`Windows`/`Linux`), query_type, response_type, execution_context, og_uuid, and an optional description. The tool handles base64 encoding of the script and the platform-name mapping. Use this whenever you're authoring a new sensor from scratch.

- **`uem_create_sensor_from_json`** — the round-trip path. Takes a full JSON body in the same shape that `uem_get_sensor` returns. Use this when you're duplicating an existing sensor (get → tweak name/OG → create) or replaying an exported sensor into a different environment. Script content in this JSON must be base64-encoded already; if you're editing the script, decode it, edit, re-encode, put it back in `script_data`. Read-only fields (`uuid`, `is_read_only`) are stripped automatically, so don't worry about those.

If `uem_create_sensor` is ever rejecting with an HTTP 400 on enum validation (platform or query_type), fall back to `uem_create_sensor_from_json` with a minimal template — the round-trip path is less fussy about enum resolution. The `script-author` skill documents the same workaround for the script-creation tool.

You need an OG UUID to create a sensor. If the user hasn't specified one, ask — don't guess, because creating a sensor at the wrong OG means it's inherited by places you didn't intend.

## Reference material

Two reference files are available. Read them into context only when relevant — they're too long to keep loaded by default.

- **`references/response-types.md`** — read this any time the user wants INTEGER, BOOLEAN, or DATETIME. It covers the exact output format each type requires and how Smart Group criteria interact with each.

- **`references/library.md`** — a cookbook of ready-to-use reference sensors: FileVault status, BitLocker status, battery cycle count, battery health, Rosetta presence, last patch date, installed app version, certificate expiry, and more. **Check the library's table of contents first for any sensor ask** — if there's a name match or a close adjacency, start from the library entry rather than authoring from scratch. Adapting a known-good reference is faster and less error-prone, and the entries already encode the right five-decision combination.

## Worked example

User asks: *"I want to know which Macs have FileVault turned on."*

Walking the five decisions:

1. **Platform**: macOS.
2. **Query type**: BASH (`fdesetup` is a shell tool, no need for Python).
3. **Response type**: BOOLEAN — it's a yes/no question, and BOOLEAN gives clean Smart Group operators.
4. **Execution context**: SYSTEM — `fdesetup status` needs root to read the full state.
5. **Name**: `macOS.security.filevault_enabled`.

Script:

```bash
#!/bin/bash
status=$(/usr/bin/fdesetup status 2>/dev/null)
if echo "$status" | grep -q "FileVault is On"; then
    echo "true"
else
    echo "false"
fi
```

Tool call: `uem_create_sensor` with platform=`macOS`, query_type=`BASH`, response_type=`BOOLEAN`, execution_context=`SYSTEM`, og_uuid=`<user's OG>`, name=`macOS.security.filevault_enabled`, and the script above as `script_content`.

Smart Group criterion that falls out of this sensor: "Sensor `macOS.security.filevault_enabled` equals `false`" — a Smart Group of non-compliant Macs, usable directly in a compliance policy or a remediation script's assignment.
