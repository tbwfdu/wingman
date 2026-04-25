# Refreshing RAG Stores on macOS

## Per-product release notes

The `v{version}_rn.txt` workflow described below is **UEM-only**. Release
notes for all other products (Horizon, App Volumes, UAG, DEM, ThinApp,
Access, Intelligence, Identity Service) are scraped automatically from
`docs.omnissa.com` — no local files needed.

To rebuild just one product's release notes:

    wingman-mcp ingest horizon_rn

To rebuild all products' release notes:

    wingman-mcp ingest rn

---

This guide walks through an **incremental refresh** of the Chroma vector stores on a macOS machine, then syncing the updated stores to Azure Files so the hosted wingman-mcp container serves fresh data.

Embeddings are generated locally using [sentence-transformers](https://www.sbert.net/) with the `all-MiniLM-L6-v2` model (≈90 MB, CPU-only). **No Azure OpenAI / external embedding service is used.**

---

## 1. Prerequisites

- macOS with Python 3.10 or newer (`python3 --version`)
- ~5 GB free disk space (existing stores + model + scratch)
- The bundle zip: `~/Desktop/wingman-mcp-ingest-bundle.zip`
  (contains all source, existing `stores/`, and the `.env` file)
- `azcopy` for syncing to Azure Files (optional, only for deploy step):
  ```bash
  brew install azcopy
  ```

---

## 2. One-time setup

```bash
# Unzip the bundle
cd ~/Desktop
unzip wingman-mcp-ingest-bundle.zip -d wingman-mcp-ingest
cd wingman-mcp-ingest

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install the package with the 'ingest' extras
pip install --upgrade pip
pip install -e ".[ingest]"
```

The first ingest run will download the embedding model (~90 MB) into your HuggingFace cache — that's expected.

---

## 3. Check first — is a rebuild worth it?

Before running a full refresh, use the `check` command to see how much has
actually changed upstream. It makes no writes — it just compares the live
sources against what's already in your stores and prints a verdict.

```bash
# Check all three stores
wingman-mcp check

# Or one at a time
wingman-mcp check api
wingman-mcp check uem
wingman-mcp check release_notes
```

What each check does:

| Store          | What it compares                                                                       |
|----------------|----------------------------------------------------------------------------------------|
| `api`          | Live Swagger `(METHOD, path)` signatures vs those stored in the Chroma metadata        |
| `uem`          | Live Omnissa sitemap URLs vs `source` metadata in the Chroma store                     |
| `release_notes`| Configured versions + SHA-256 of each local `v{version}_rn.txt` vs stored hashes       |

The verdict is one of:
- `no changes — rebuild not needed`
- `trivial changes — rebuild not urgent` (<1% changed)
- `minor changes — rebuild optional` (1–5% changed)
- `significant changes — rebuild recommended` (≥5% changed or 50+ pages changed)

Release-notes content hashes are written next to the store (`.content-hashes.txt`)
on each ingest, so the second and subsequent runs of `check release_notes` can
tell you whether any version's page has been updated.

---

## 4. What gets refreshed how

| Store          | Source                              | Manual files needed?          |
|----------------|-------------------------------------|-------------------------------|
| `api`          | Live scrape of Omnissa API docs     | No — fully automated          |
| `uem`          | Omnissa UEM docs sitemap            | No — fully automated          |
| `release_notes`| UEM release-notes HTML (per version)| **Yes — see next section**    |

Incremental behaviour:
- `api` / `uem`: the scraper re-fetches pages. Chroma is rebuilt based on what's in the store directory — for a true incremental refresh you keep the existing `stores/` directory from the bundle (already included).
- `release_notes`: the ingester **deletes entries for each version before re-adding**, so it's safe to re-run. Only versions with a matching `v{version}_rn.txt` file are touched — other versions remain untouched.

---

## 5. Download release notes manually

The release-notes ingester looks for `v{version}_rn.txt` files containing the plain text of each release-notes page. Download these **before** running the release_notes ingest.

Versions (from `src/wingman_mcp/ingest/ingest_release_notes.py`):

| Version | URL                                                                                                                 |
|---------|---------------------------------------------------------------------------------------------------------------------|
| 2506    | https://docs.omnissa.com/bundle/Workspace-ONE-UEM-Release-NotesV2506/page/WorkspaceONEUEM-ReleaseNotes.html         |
| 2509    | https://docs.omnissa.com/bundle/Workspace-ONE-UEM-Release-NotesV2509/page/WorkspaceONEUEM-ReleaseNotes.html         |
| 2602    | https://docs.omnissa.com/bundle/Workspace-ONE-UEM-Release-NotesV2602/page/WorkspaceONEUEM-ReleaseNotes.html         |

For each version:

1. Open the URL in a browser.
2. Wait for the page to fully render (it's a JS-loaded docs portal).
3. Select all visible content (⌘A) and copy it (⌘C).
4. Save it as plain text named `v{version}_rn.txt` **in the repo root** (the same directory you'll run `wingman-mcp ingest` from). So you should end up with:

```
wingman-mcp-ingest/v2506_rn.txt
wingman-mcp-ingest/v2509_rn.txt
wingman-mcp-ingest/v2602_rn.txt
```

If a version file is missing, that version will simply be skipped (existing entries for it stay intact).

When a new UEM version ships, add it to `VERSION_MAP` in `src/wingman_mcp/ingest/ingest_release_notes.py`, download its page into `v{version}_rn.txt`, and rerun.

---

## 6. Run the ingestion

Make sure your venv is active (`source .venv/bin/activate`) and you're in the repo root.

### Refresh everything

```bash
wingman-mcp ingest
```

### Or refresh one store at a time

```bash
wingman-mcp ingest api
wingman-mcp ingest release_notes
wingman-mcp ingest uem
```

### Tuning flags (uem ingest only)

- `--max-workers N`  parallel fetch workers (default 50 — reduce if you hit rate limits)
- `--batch-size N`   embedding batch size (default 500)

Example:
```bash
wingman-mcp ingest uem --max-workers 20 --batch-size 200
```

### Check status

```bash
wingman-mcp status
```

You should see all three stores reporting sizes in MB.

---

## 7. Sync refreshed stores to Azure Files

The hosted container reads stores from the Azure File Share mounted at `/mnt/wingman-stores`. After a successful refresh, sync the `stores/` directory up.

```bash
# Authenticate azcopy once (opens browser)
azcopy login

# Sync — adjust the URL to your storage account + share name
azcopy sync ./stores \
  "https://<storage-account>.file.core.windows.net/wingman-stores" \
  --recursive \
  --delete-destination true
```

`--delete-destination true` ensures deleted chunks are removed from the share — safe because the share is for wingman-stores only.

---

## 8. Restart the container (optional)

Chroma reads its SQLite DB on every query, so most changes appear immediately. If you want a clean restart:

```bash
az containerapp revision restart \
  --name <container-app-name> \
  --resource-group <resource-group> \
  --revision <latest-revision>
```

Or trigger a new revision by touching any env var:
```bash
az containerapp update \
  --name <container-app-name> \
  --resource-group <resource-group> \
  --set-env-vars STORES_REFRESHED_AT=$(date +%s)
```

---

## 9. Troubleshooting

- **`ModuleNotFoundError: No module named 'requests'`**
  You didn't install the `[ingest]` extras. Rerun `pip install -e ".[ingest]"`.

- **HuggingFace download hangs / 429s**
  First run downloads `all-MiniLM-L6-v2`. Re-run — the cache persists under `~/.cache/huggingface/`.

- **UEM ingest is slow / rate-limited**
  Drop `--max-workers` to 10 or 20.

- **Release notes entries look empty**
  The `v{version}_rn.txt` file was probably captured before the JS finished rendering. Scroll to the bottom of the page, wait a few seconds, then re-select and save.

- **`stores/` directory missing from bundle**
  That's fine — ingest will create a fresh store. You just lose the incremental advantage (first full run takes longer).

---

## 10. Quick reference — full refresh cycle

```bash
cd ~/Desktop/wingman-mcp-ingest
source .venv/bin/activate

# See what would change before committing to a rebuild
wingman-mcp check

# (Update v*_rn.txt files in repo root if refreshing release notes)

wingman-mcp ingest
wingman-mcp status

azcopy sync ./stores \
  "https://<storage-account>.file.core.windows.net/wingman-stores" \
  --recursive --delete-destination true
```
