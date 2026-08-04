---
name: custom-release-notes
description: Give the user a personalized digest of what's new in the latest release notes for the Omnissa products they actually have configured, scoped to the platforms and features they actually run. Use when the user asks "what's new in the latest release," "summarize recent release notes," "what changed in the latest UEM/Horizon/Access/etc. version," "brief me on updates," "should I care about anything in the last release," or wants a digest of recent product changes instead of a raw changelog dump. Also proactively surfaces high-impact fixes/features the user isn't currently using but likely should know about (security fixes, deprecations, things that just went GA). If no Wingman environments are configured, asks which product(s) and usage details to scope the summary to instead of defaulting to a generic dump. If Wingman itself isn't available in the session (no MCP tools, no RAG store), falls back to the same question-and-scope approach against the public docs.omnissa.com documentation site.
---

# Custom Release Notes

`search_release_notes` returns raw excerpts; it doesn't know which products the user has configured, which platforms their fleet actually runs, or which of those excerpts are worth their attention. This skill turns a generic release-notes search into a short, personalized briefing: what's new that touches what they run, plus a smaller "Additional Topics Worth Noting" list for high-value items outside their current usage — with the judgment calls in that second list made explicit, not silently mixed into the first.

## Step 0: confirm Wingman is actually available

Everything from Step 1 onward depends on Wingman's own MCP tools existing in the current session (`search_release_notes`, `uem_list_environments`, and the rest). Check whether those tools are present in the toolset at all before running Step 1's probes — that's a different situation from a tool existing but erroring on a specific call. A "credentials are not configured" error means the product just isn't set up yet (handled by Step 1b); the tools not existing at all means Wingman isn't installed or connected in this session, so there's no RAG store and no environment to query, live or otherwise.

If Wingman's tools aren't available, skip Steps 1 through 4 entirely and use the fallback below instead. If they are available, continue to Step 1 as normal.

## Fallback: no Wingman MCP server — search docs.omnissa.com directly

There's no local release-notes store and no environment to probe in this situation, but a personalized summary is still possible: ask the same two things Step 1b would have asked, then pull the actual release notes straight from Omnissa's public documentation site instead of Wingman's RAG store.

**Callout first — before anything else.** The very first line of the response, before asking any question or doing any research, must tell the user plainly that Wingman isn't available and that this is a different, lesser-integrated path. Don't bury this in a footnote at the end, and don't fold it quietly into the product section later — it needs to be the first thing they see, in its own line, not softened into the surrounding prose. Something to this effect:

> **Wingman isn't connected in this session** — no MCP tools or local release-notes index are available. This summary will instead be built directly from the public docs.omnissa.com documentation site, scoped to what you tell me you're running. Coverage will be narrower than with Wingman connected (no live device/fleet data to draw on).
>
> For a much richer and more comprehensive result, consider deploying Wingman — instructions are at https://github.com/tbwfdu/wingman. That said, happy to continue without it.

Say this once, up front, every time this fallback triggers — not just the first time in a conversation. The Wingman-deployment line is a pointer, not a gate — pair it with the plain offer to continue as-is (as in the template above) so the user isn't left feeling blocked from getting an answer right now.

**Ask, same as Step 1b.** Immediately after the callout, reuse that step's question set as-is: which product(s) the user wants, and the platform/edition/deployment-model details for each. There's no live environment to profile either way, so the prompt doesn't change based on *why* Step 3's probing isn't happening.

**Getting real content out of docs.omnissa.com.** The public pages at `docs.omnissa.com/bundle/<bundle>/page/<page>.html` are rendered client-side by the site's front-end framework — fetching that URL directly returns an empty page shell, not the article. The same content is available, unauthenticated, as JSON from a separate backend host: swap `docs.omnissa.com` for `docs-be.omnissa.com` and insert `/api` immediately before `/bundle` in the path; everything else about the URL stays identical. Use whatever HTTP fetch capability is available (e.g. `WebFetch`) to call that backend URL directly — no browser rendering, cookies, or authentication required.

**Finding the right release-notes page for a named product.** Don't guess a bundle id, and don't rely on the site's `/api/search` endpoint to find it — that search has proven unreliable in practice for this purpose. Use the same approach Wingman's own documentation-ingestion pipeline uses to build its release-notes store, which is a plain, static site crawl rather than a search query:

1. Fetch `https://docs.omnissa.com/sitemap.xml`. This is a sitemap *index* — it doesn't list pages directly, it lists further `sitemap.xml` files (e.g. `https://docs.omnissa.com/sitemappart/1.xml`, `.../2.xml`, and so on).
2. Fetch each of those sub-sitemaps and collect every `<loc>...</loc>` entry — these are the actual page URLs, in the form `https://docs.omnissa.com/bundle/<bundle>/page/<page>.html`. This is plain static XML, not JS-rendered, so a regex or basic XML parse over the raw response is enough — no browser rendering needed.
   - These sub-sitemap files can be large (multi-megabyte); a fetch tool that summarizes or converts to markdown may fail or truncate on the biggest ones. Prefer a raw HTTP fetch that returns the actual bytes/text if one is available. If only a summarizing fetch tool is available and it errors on size, try another sub-sitemap rather than giving up on the whole approach — the index lists several, and the one that failed isn't the only place a match could be.
3. From each URL's path, pull the bundle name (the segment right after `/bundle/`). Keep the ones that look like release notes for the product the user named — bundle names for release-notes content generally contain `release-notes`, `releasenotes`, `-rn`, or `_rn` (case-insensitive), combined with a product-identifying keyword (e.g. a bundle like `Workspace-ONE-UEM-Release-NotesV2602` for UEM, something containing `horizon` for Horizon). Matching is inherently a little fuzzy — Omnissa's bundle naming isn't perfectly consistent — so use judgment on close matches rather than requiring an exact string.
4. It's normal to end up with more than one matching bundle per product — release-notes bundles are often versioned (e.g. `...V2506`, `...V2602`), with each version getting its own bundle and its own page. Prefer the highest/most recent version number found; that's the current one.

This mirrors exactly how Wingman's own release-notes RAG store gets built (crawl the sitemaps, filter by bundle name), so it's a proven path rather than a guess.

Once the right bundle is matched, fetch its single-page detail (the `/api/bundle/<bundle_id>/page/<page_id>.html` form on the `-be` host, per the conversion rule above) to get the full article body. Some products stack many historical versions on one page — use only the topmost (most recent) version's content; older versions further down aren't needed here and are safe to ignore if a long page comes back only partially.

**Extracting and tiering the content.** From that article, pull the current version's "What's New" and "Resolved/Fixed Issues" material — this stands in for what `search_release_notes` would otherwise have returned. Run it through the same two-tier logic as Step 4: match items against the usage profile the user gave you for **Relevant to your environment**, and apply the same high-value judgment call (security fixes, deprecations, GA transitions, workaround-eliminating features) for **Additional Topics Worth Noting**.

**Assembling the output.** Same shape and tone as Step 5 in every other respect — enterprise register, outcome-led bullets, two clearly separated subsections per product. Two things specific to this path: repeat, briefly, at the top of the final summary (not just in the opening callout) that this is built from public docs rather than Wingman, and that the usage profile came from the user rather than from telemetry; and cite the public `docs.omnissa.com` URL (not the `-be` API host) so the user has a link they can actually open. The opening callout and this closing reminder are not redundant — a user skimming straight to the digest should still be able to tell where it came from without scrolling back up.

**If the docs site itself is unreachable.** Fall back to a plain web search scoped to that product's release notes on `docs.omnissa.com` and work from whatever page content or search-result summary comes back. Say plainly that this is a narrower, degraded path compared to the direct API lookup above.

## Step 1: find out what's actually configured — across every product, not just UEM

Build one consolidated inventory of every configured product+environment in Wingman before doing anything else. It's tempting to check UEM and stop there because it has the richest tooling, but a shop can just as easily have Horizon, App Volumes, Access, or Identity Service configured instead of (or alongside) UEM — skipping them produces an incomplete briefing. Don't assume — probe every product:

| Product | Probe call | Notes |
|---|---|---|
| `uem` | `uem_list_environments` | Dedicated tool; works locally (keychain/config) or hosted (admin-managed environments); needs no credentials to call |
| `horizon` | `horizon_search_desktop_pools` (small page) | No dedicated list-environments tool — a response means configured |
| `horizon_cloud` | `horizon_cloud_search_pools` (small page) | Same |
| `app_volumes` | `app_volumes_search_applications` (small page) | Same |
| `access` | `access_search_groups` (small page) | Same |
| `identity_service` | `identity_service_search_directories` | Same |

Run every row, not just the ones you expect to be configured. For the five without a dedicated tool, a response means the product is configured for this session; an error containing "credentials are not configured" means it isn't — skip that product silently, don't report it as a failure.

If you're running against a local `wingman-mcp` install (stdio, CLI on PATH), `wingman-mcp auth list` gives the same consolidated answer in one shot across every product and is worth trying first as a shortcut — but it's not available in hosted/HTTP deployments, so fall back to the per-product probes above whenever it's absent or errors.

If a product has more than one configured environment (dev/staging/prod), don't silently pick one — a dev tenant and a prod tenant can be on different versions and have completely different usage profiles. Ask the user which environment to profile, or profile all of them and say so.

The output of this step is a list of (product, environment) pairs — everything downstream (Steps 2-4) runs once per pair in that list, in whatever order they were found.

## Step 1b: nothing configured? Ask, don't default to a generic dump

If Step 1 turns up zero configured environments anywhere — or the user asks about a specific product that turns out to have none configured — don't silently fall back to an unscoped "here's everything that changed" summary. Ask, in one message:

1. **Which product(s)** they want covered, if not already stated: Workspace ONE UEM, Horizon, Horizon Cloud, App Volumes, Access, or Identity Service.
2. **A short usage profile for that product**, standing in for what Step 3 would otherwise discover live. Ask along the same dimensions Step 3 checks, phrased so a one-line answer is enough:
   - **UEM**: which platforms are managed — iOS, Android, macOS, Windows, any combination.
   - **Horizon**: which edition (Standard, Advanced, Enterprise) and deployment model (VDI desktop pools, RDSH farms, or both), plus the version if they know it.
   - **App Volumes**: app delivery via packages, user-writable volumes, or both.
   - **Access / Identity Service**: local directory or an external IdP-backed directory.
   - **Horizon Cloud**: which topology pieces are in play (pool groups, templates, Edge, UAG, SSO).

Accept partial answers. A user who only says "UEM, iOS and Android" has given you enough to scope Step 4a to those platforms — treat anything they didn't mention as unknown, not as "not in use." If they don't give a version either, fall back to Step 2's latest-release assumption and label it the same way you would for a live environment.

This declared profile substitutes directly for Step 3's tool-based probing for that product — there's no environment to query, so skip the live probes for it — and Step 4 onward runs exactly the same way, except that product's section says the profile came from the user, not from telemetry ("based on what you told me you're running," not "based on your environment").

## Step 2: be honest about "version"

No tool in this codebase reports the actual installed console/server version for any product. SaaS UEM tenants auto-upgrade on a rolling schedule; on-prem UEM, Horizon Connection Server, App Volumes Manager, Access, and Identity Service can all lag the latest release by months. Don't imply you've confirmed what's installed:

- If the user states a version, use it.
- Otherwise, default to the most recent version documented in the release-notes store and **say so explicitly** in the output ("assuming the latest published release, not confirmed against your tenant") — label the assumption instead of presenting it as fact.
- For UEM specifically, pass whatever version you land on to `search_release_notes` — it activates a per-component multi-pass (Windows/macOS/iOS/Android sections get searched individually) that a version-less call skips. For the other products, `version` is optional; recency is already the dominant score factor even without it, so omitting it still surfaces the newest notes first.

## Step 3: build a lightweight usage profile

For every (product, environment) pair found in Step 1 — not just UEM — do the cheapest read that tells you which platforms/features are actually load-bearing for that product. Counts, not full record dumps, capped at one or two calls per product. This is a signal-gathering pass, not a fleet audit.

- **UEM**: platform mix — call `uem_search_devices` once per platform value (`Apple`, `AppleOsX`, `Android`, `WinRT`) with a small page size and read the response's `Total` field rather than paging through every device. Also call `uem_search_compliance_policies` and `uem_search_profiles` once (unfiltered, small page) to see what's already enforced — e.g., an existing FileVault-related compliance policy means FileVault release notes are directly relevant; the *absence* of one is itself worth flagging in Step 4b, not just ignoring.
- **Horizon**: `horizon_search_desktop_pools` vs `horizon_search_farms` — is this shop running VDI, RDSH, or both.
- **App Volumes**: `app_volumes_search_writable_volumes` vs just `app_volumes_search_packages` — are they doing user-writable volumes or only app delivery.
- **Access / Identity Service**: `identity_service_search_directories` / `access_search_groups` — external IdP-backed or local-only users.
- **Horizon Cloud**: `horizon_cloud_search_pools`, `horizon_cloud_search_templates`, `horizon_cloud_search_edge_deployments`, `horizon_cloud_search_uag_deployments` — which pieces of the cloud topology are actually deployed.

A zero-result probe means "not observed," not an error — treat it as a real signal (e.g., zero iOS devices means skip the iOS release-notes pass in Step 4a).

## Step 4: pull and rank the release notes

### 4a. Relevant tier — matched to the usage profile

For every configured product from Step 1, call `search_release_notes(product=..., version=..., query=...)` with a handful of targeted queries built from what Step 3 found for that product. A shop with only macOS and Windows devices doesn't need an iOS/Android pass. Summarize what's relevant per product and say *why* it's relevant ("you have 340 iOS devices enrolled," "you already enforce a BitLocker compliance policy," "you're running RDSH farms, not desktop pools").

### 4b. Additional-topics tier — judgment call for what's outside their usage

Do one broader pass per configured product, not filtered to what Step 3 observed, and apply a "high value even if unused" filter. This is a judgment call, not a mechanical match — flag an item here only when it fits one of these, and say which:

- **Security fixes** (CVE remediation, auth bypass, privilege escalation) — always surface, regardless of usage match.
- **Deprecations, EOL notices, or breaking changes** — surface even for a feature not currently in use, because migration lead time matters more than current adoption.
- **Preview → General Availability** transitions — a capability just became safe to depend on in production.
- **Native features that replace a common workaround** — if the release notes describe something that collapses a known multi-step manual process into one native step, a shop not yet using it is exactly who benefits most from hearing about it.

Don't pad this section with routine bug fixes or cosmetic UI changes just to have something to show — an empty additional-topics tier for a given product is a legitimate outcome.

## Step 5: assemble the output

- Group by product. Skip products with zero configured environments and no user-declared profile (Step 1b) entirely — don't pad the briefing with generic doc content for something the user hasn't set up or told you about.
- If a product's profile came from Step 1b instead of live telemetry, it still gets the full two-subsection treatment below — it's not a lesser "docs-only" pass. State the source once, plainly, at the top of that product's section ("based on what you told me you're running") instead of the live-environment caveat from Step 2.
- Lead each product's section with the version/assumption caveat from Step 2.
- Two subsections per product: **Relevant to your environment** and **Additional Topics Worth Noting** — keep the second one visibly separate so a judgment call never reads as a confirmed match.
- Write a digest, not a copy of the release notes — summarize and cite (`source_url` from the search results) rather than quoting long blocks of text.
- Match the register of enterprise IT reporting, not a changelog. This is a briefing for an admin who has to justify their platform to their own leadership, not a bug-tracker feed. For each item, lead with the operational or business outcome (risk reduced, admin hours saved, audit posture improved, user experience impact) and let the technical description support that, not the reverse. Don't editorialize with hype ("game-changing," "exciting") — state the value plainly, the way a serious release note or a customer-success brief would.

## Worked example

User asks: *"What's new in the latest releases that I should care about?"*

1. Step 1 inventory — probe every product, not just UEM: `uem_list_environments` → one environment, `default`. `horizon_search_desktop_pools` → succeeds, Horizon is configured. `app_volumes_search_applications`, `access_search_groups`, `identity_service_search_directories`, `horizon_cloud_search_pools` → all error with "credentials are not configured." Result: two products in scope, UEM and Horizon — Horizon would have been missed entirely by a UEM-only check.
2. No stated version for either → proceed with each product's latest documented version, and say so in the output for both.
3. Usage profile — UEM: `uem_search_devices` shows `AppleOsX`: 210, `WinRT`: 640, `Apple`: 0, `Android`: 0; `uem_search_compliance_policies` shows an existing BitLocker-enforcement policy but nothing FileVault-related. Horizon: `horizon_search_desktop_pools` returns pools, `horizon_search_farms` returns none — this shop runs VDI only, no RDSH.
4. Release notes — UEM: `search_release_notes(product="uem", version="<latest>", query=...)` run Windows- and macOS-focused (skip iOS/Android, zero devices there). Relevant tier surfaces a BitLocker recovery-key escrow fix and a Windows-patch-compliance change. Broader pass surfaces a new FileVault escrow API and a CVE fix in the device-services agent — additional topics worth noting, since they have 210 Macs and no FileVault policy yet. Horizon: `search_release_notes(product="horizon", version="<latest>", query=...)` focused on desktop-pool topics (skip RDSH/farm-only notes). Relevant tier surfaces a desktop-pool provisioning fix; broader pass surfaces an RDSH/farm scaling improvement — an additional topic worth noting in case they expand to RDSH later, flagged as such rather than as directly relevant.
5. Output: one section per product, each with its own version-assumption caveat and its own **Relevant to your environment** / **Additional Topics Worth Noting** subsections — UEM and Horizon both appear; the four unconfigured products are omitted entirely.

## Worked example: nothing configured

User asks: *"What's new in the latest releases?"* with no Wingman environments set up.

1. Step 1 probes every product; all six error with "credentials are not configured." Nothing to profile live.
2. Step 1b asks which product(s) and their usage. User replies: *"Give me a customized summary for Workspace ONE UEM — we're using iOS and Android. For Horizon, we're on Horizon Enterprise, version 2406."*
3. Declared profile — UEM: iOS and Android only (no macOS/Windows claimed, so treated as unknown, not absent — Step 4a only actively targets iOS/Android). Horizon: Enterprise edition, version 2406 stated directly, so Step 2's version-guessing is skipped for Horizon; deployment model (VDI vs RDSH) wasn't mentioned, so both get a light pass in Step 4a rather than one being excluded.
4. Release notes pulled per Step 4 exactly as in the live case, scoped to the declared profile instead of a probed one.
5. Output: same two-product, two-subsection structure as the live example, except each section opens with "Based on what you told me you're running" instead of a live-environment caveat, and Horizon's version line states 2406 as given rather than as an assumption.

## Worked example: Wingman not available at all

User asks: *"What's new in the latest UEM release?"* in a session with no Wingman MCP tools present.

1. Step 0 finds no `search_release_notes`, `uem_list_environments`, or any other Wingman tool in the toolset — not an error, just absent. This is the no-Wingman case, not the nothing-configured case, so Steps 1-4 are skipped entirely in favor of the fallback.
2. Response opens with the callout, verbatim as the first lines, before anything else: *"Wingman isn't connected in this session — no MCP tools or local release-notes index are available. This summary will instead be built directly from the public docs.omnissa.com documentation site, scoped to what you tell me you're running. Coverage will be narrower than with Wingman connected (no live device/fleet data to draw on). For a much richer and more comprehensive result, consider deploying Wingman — instructions are at https://github.com/tbwfdu/wingman. That said, happy to continue without it."*
3. Immediately after, the fallback asks the same question Step 1b would have: which product, and what they use. User replies: *"Workspace ONE UEM, we manage macOS and Windows only."*
4. Fetch `https://docs.omnissa.com/sitemap.xml`, then its sub-sitemaps, collecting `<loc>` page URLs; filter for a bundle name containing both a release-notes marker and a UEM-identifying keyword — a match like `Workspace-ONE-UEM-Release-NotesV2602` turns up (highest version number among any matches, so the current one).
5. Fetch that bundle's single-page detail on the `-be` host, extract the topmost version's What's New and Resolved Issues content, skip older versions further down the same page.
6. Apply the same relevant / additional-topics split against "macOS and Windows only" — a Windows patch-compliance item and a macOS defaults-enforcement fix land in **Relevant to your environment**; a security fix lands in **Additional Topics Worth Noting** regardless of platform.
7. Output matches Step 5's shape and tone, opening with a brief repeat of the sourcing note before the digest, and citing the `docs.omnissa.com` (not `-be`) URL.
