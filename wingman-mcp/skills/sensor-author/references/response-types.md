# Response types: the output contract

UEM's sensor response type controls how stdout is parsed into the value that shows up on a device record and in Smart Group criteria. Get this wrong and the sensor either reports nonsense or becomes unusable as a criterion. This file documents the exact output format for each type and the Smart Group operators each unlocks.

The rule behind all of these: UEM captures the script's stdout, trims trailing whitespace, and attempts to coerce the result into the declared type. Coercion failures usually produce an empty or null value on the device record, not an error — which is why a broken sensor often looks identical to one that hasn't run yet.

## STRING

The forgiving default. Any text is valid. UEM stores it as-is (after trim).

**Script output**: anything. A single line is conventional; multiline works but the value rendered in the console is the raw stdout with newlines preserved, which is rarely useful.

**Smart Group operators**: equals, not equals, contains, does not contain, starts with, ends with, is blank, is not blank.

**When to use**: free-text values like OS build strings, hostnames, installed app versions as version strings ("14.6.1" is a string, not a number), enum-like status words ("encrypted" / "decrypting" / "not_encrypted"), serial numbers, certificate thumbprints.

**Gotchas**: Leading/trailing whitespace is trimmed, but internal whitespace is preserved. If you're comparing against a Smart Group criterion, make sure the criterion uses the exact casing and spacing the script emits.

## INTEGER

A whole number. UEM parses stdout with an integer regex — anything non-numeric and the value is rejected.

**Script output**: digits only, optional leading minus. No decimal point, no units, no label, no thousands separator. Good: `1247`. Bad: `1,247`, `1247 cycles`, `count=1247`, `1247.0`.

**Smart Group operators**: equals, not equals, greater than, less than, greater than or equal, less than or equal, between.

**When to use**: counts (battery cycle count, days since last patch, installed update count), sizes where a bucket makes sense (free disk space in GB — but see note below), integer-valued version components.

**Gotchas**:

- Floats silently fail. If you're computing "free disk space in GB" and the underlying value is 47.3, the script must round or truncate (`echo $(( bytes / 1073741824 ))`) before emitting.
- Negative numbers work but are rare in practice. A sensor that could legitimately return -1 and also legitimately return 0 means you lose the "unknown" sentinel — consider STRING with numeric-looking values instead.
- If the probe fails, don't emit `0` as a sentinel — `0` is a legitimate count for many sensors. Emit nothing (empty stdout) or switch to STRING and use an explicit `"unknown"`.
- **PowerShell specifically**: an object with a numeric property emitted bare (e.g. `$result.Count`) usually prints cleanly, but edge cases like `$null.Count` or objects that auto-format can produce surprising output. Cast explicitly with `[int]` on the last line to guarantee a digits-only stdout. `[int]$count` on the last expression is a reliable pattern.

## BOOLEAN

Exactly `true` or `false`, lowercase. Anything else is rejected.

**Script output**: the literal word `true` or the literal word `false`, no quotes, no capitalisation, no trailing period.

**Smart Group operators**: equals true, equals false.

**When to use**: yes/no probes — "is FileVault on," "is BitLocker on," "is Rosetta installed," "is the device on the corporate network." Anything where the Smart Group question is "show me the ones where this is [true|false]."

**Gotchas**:

- PowerShell's default boolean representation is `True` / `False` (capitalised). Convert explicitly: `$result.ToString().ToLower()`. A sensor that emits `True` returns an unparseable value, and the device record shows nothing.
- Don't get clever with `0` / `1`, `yes` / `no`, or `enabled` / `disabled`. Those are STRING territory.
- If the probe genuinely has three states (yes, no, unknown), BOOLEAN is the wrong type. Use STRING and emit `"true"` / `"false"` / `"unknown"` — you lose the boolean operators but gain honest reporting.

## DATETIME

An ISO 8601 timestamp. UEM parses the output as a date for use in date-arithmetic Smart Group criteria.

**Script output**: ISO 8601 format. UTC with `Z` suffix is the most reliable: `2026-04-17T04:30:00Z`. Offsets also work (`2026-04-17T14:30:00+10:00`). Bare dates (`2026-04-17`) often work but depend on UEM's parser version — safer to include the time.

**Smart Group operators**: before, after, between, within the last N days.

**When to use**: "last patched" dates, certificate expiry, last successful check-in of some secondary system, enrollment anniversary — any case where "is this more than N days old" is the Smart Group question.

**Gotchas**:

- Locale-dependent date formats (`04/17/2026`, `17-04-2026`) will not parse reliably. Always emit ISO 8601.
- Timezone ambiguity bites. If the script reads a local timestamp and emits it without a zone, Smart Group calculations may be off by a day. Either convert to UTC in the script, or include the offset.
- If the probe can't determine a date (e.g., the registry key doesn't exist yet), don't emit epoch (`1970-01-01T00:00:00Z`) as a sentinel — it's technically valid and will match "within the last 20000 days" criteria. Emit nothing.

## Choosing between types

A useful heuristic:

1. Is the Smart Group question a date-arithmetic question? → DATETIME.
2. Is it a pure yes/no question with no third state? → BOOLEAN.
3. Does the Smart Group question involve numeric comparison (greater than, between)? → INTEGER (and make sure the probe really is a whole number).
4. Everything else → STRING.

When in doubt, STRING. A sensor that reports `"1247"` as a string can still be filtered with `contains` and `starts with`, and you can always create a parallel INTEGER sensor later if numeric operators become useful. A sensor that reports INTEGER wrong just reports nothing.
