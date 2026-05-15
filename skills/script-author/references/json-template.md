# JSON template for `uem_create_script_from_json`

Ready-to-fill template for creating a UEM script via the round-trip path. Use this rather than `uem_create_script` until the known enum-validation HTTP 400 bug is resolved.

## Minimal template

```json
{
  "name": "platform.domain.action",
  "description": "What this script does. Include idempotence guarantees and any assumptions about prerequisites.",
  "platform": "APPLE_OSX",
  "script_type": "BASH",
  "organization_group_uuid": "<og-uuid-here>",
  "script_data": "<base64-encoded-script>",
  "execution_context": "SYSTEM",
  "is_idempotent": true,
  "timeout": 300,
  "allowed_in_catalog": false,
  "user_interaction": false,
  "script_variables": []
}
```

## Field reference

**`name`** — letters, numbers, periods, underscores, and spaces only. No hyphens, no slashes. Pick a naming convention early; `<platform>.<domain>.<action>` works well (e.g. `macOS.install.homebrew`, `Windows.remediate.spooler_restart`).

**`description`** — free text, but treat it as documentation that survives reorgs. Include what the script does, whether it's idempotent, any prerequisites, and whether it pairs with a detection sensor.

**`platform`** — API-native values only: `APPLE_OSX`, `WIN_RT`, `LINUX`. The round-trip path doesn't translate the friendly names.

**`script_type`** — `BASH`, `ZSH`, `POWERSHELL`, or `PYTHON`. Match to platform (no BASH on WIN_RT, no POWERSHELL on APPLE_OSX).

**`organization_group_uuid`** — the OG where the script is created. Ask the user if not specified; creating at the wrong OG leaks inheritance into places you didn't intend.

**`script_data`** — base64-encoded script source. See the encoding section below. The content should be the raw script with its shebang; no BOM; LF line endings preferred.

**`execution_context`** — `SYSTEM` or `USER`. Default `SYSTEM`.

**`is_idempotent`** — `true` if the script is safe to re-run without side effects (it should be). UEM uses this to decide re-run behaviour on assignment updates. Setting `true` on a non-idempotent script causes subtle bugs — be honest.

**`timeout`** — seconds. UEM enforces this: the script is killed if it exceeds. Common values:
- Quick checks or config changes: `60`–`120`
- Installs: `300`–`900`
- Large downloads or migrations: `1200`+

**`allowed_in_catalog`** — `false` for remediation/enforcement scripts. `true` only if the script is user-facing and you want it visible in the Workspace ONE Catalog as a self-service action.

**`user_interaction`** — `false` almost always. Set `true` only if the script legitimately needs a UI session (e.g. it prompts or relies on a logged-in user's environment). Setting `true` on an unattended remediation script causes it to wait for a session that isn't there.

**`script_variables`** — `[]` unless parameterising. See the parameterisation section below.

## Base64-encoding the script content

The `script_data` field needs the raw script content, base64-encoded, as a single string (no line breaks inside the base64).

**macOS/Linux (bash)**:
```bash
base64 -i script.sh | tr -d '\n'
```
The `-i` flag tells macOS `base64` to read from a file; the `tr -d '\n'` strips line breaks to produce a single-line output that drops cleanly into JSON.

**macOS/Linux inline (pipe script through)**:
```bash
cat script.sh | base64 | tr -d '\n'
```

**Linux GNU base64 (no line wrapping by default with `-w 0`)**:
```bash
base64 -w 0 script.sh
```

**PowerShell**:
```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes('script.ps1'))
```

**Python**:
```python
import base64
with open('script.sh', 'rb') as f:
    encoded = base64.b64encode(f.read()).decode('ascii')
print(encoded)
```

**Gotchas**:
- **Line endings**: PowerShell scripts authored on Windows have CRLF. Most target devices handle CRLF fine, but some parsers don't. If in doubt, convert to LF before encoding (`dos2unix` or `(Get-Content script.ps1 -Raw) -replace "`r`n", "`n" | Set-Content -NoNewline`).
- **BOMs**: a UTF-8 BOM at the start of a script will confuse some shells. Save as "UTF-8 without BOM" or strip the BOM before encoding.
- **Line wrapping in the base64 output**: JSON strings don't want embedded newlines. Always strip newlines from your base64 before inserting.

## Parameterisation with `script_variables`

The `script_variables` field lets the script receive values set at the UEM console (or at assignment time) rather than hardcoding them. Useful when the same script applies across OGs or groups that need different inputs.

Shape:
```json
"script_variables": [
  {
    "name": "CORPORATE_DOMAIN",
    "type": "STRING",
    "value": "corp.example.com",
    "sensitive": false
  },
  {
    "name": "API_TOKEN",
    "type": "STRING",
    "value": "",
    "sensitive": true
  }
]
```

Each variable becomes an environment variable available to the script at runtime. `sensitive: true` tells UEM to redact the value from logs and the console UI.

**When to parameterise vs hardcode**:
- Parameterise if the same script is used across multiple OGs with different values.
- Parameterise for anything sensitive (tokens, credentials) — hardcoding them in the script body embeds them in base64 in the script record.
- Hardcode when the value is truly fixed and unlikely to vary.

**Don't parameterise for flexibility you don't need**. Every parameter is another field someone has to set correctly at assignment time; unused flexibility is just extra surface area for mistakes.

## Round-tripping an existing script

If you're duplicating or promoting an existing script (common pattern: "copy this from UAT to Prod"):

1. `uem_get_script` with the source script's UUID.
2. Take the returned JSON, strip read-only fields (`script_uuid`, `version`, `assignment_count`, `created_or_modified_by`, `created_or_modified_on`, `organization_group_name`) — the tool will strip them automatically but it's cleaner to omit them.
3. Change `organization_group_uuid` to the destination OG.
4. Change `name` if the destination is the same environment (names must be unique per OG hierarchy, and collisions will fail).
5. Pass to `uem_create_script_from_json`.

For bulk migration across environments, use `uem_migrate_scripts` instead — it does the search + get + create loop and skips name collisions automatically.
