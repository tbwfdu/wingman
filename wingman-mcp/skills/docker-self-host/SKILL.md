---
name: docker-self-host
description: Walk a user through self-hosting the wingman-mcp-server container end to end — checking whether Docker is available, installing Docker Engine (not Docker Desktop) if it isn't, optionally pointing to Rancher Desktop for a UI, pulling the image from GHCR, generating a docker-compose.yml and access key, and deploying locally. Use when the user asks to "install Wingman," "self-host Wingman," "set up the Wingman container," "run Wingman locally," "deploy Wingman with Docker," or wants to get the wingman-mcp-server Docker image running on their own machine instead of using the local stdio package or a hosted server.
---

# Docker Self-Host Walkthrough

This is an install walkthrough, not a one-shot script — react to what each command actually reports rather than assuming success, and confirm with the user before anything that installs system packages or starts long-running services with an open port.

## Step 1: check whether Docker is available

Run `docker info`. This checks both that the CLI exists and that a daemon is actually reachable — a Docker CLI can be installed with no running daemon behind it, and that's a different problem than "not installed at all."

- **Succeeds** → Docker is ready. Skip to Step 3.
- **Command not found** → no Docker CLI at all. Go to Step 2.
- **CLI exists but the daemon doesn't respond** (e.g. "Cannot connect to the Docker daemon…") → an engine is installed but not running. This is common right after a fresh install (the VM/service hasn't been started yet) — tell the user what to start (`colima start`, launching Rancher Desktop, `sudo systemctl start docker`, whichever applies) rather than treating it as a fresh install from scratch.

## Step 2: no Docker found — install the engine, not Docker Desktop

The user wants the CLI/engine only, not the Docker Desktop GUI application. Present the commands for their OS and let them run them (or confirm before running anything yourself that needs elevated privileges) — installing system packages is a machine-level change, not something to push through silently.

**macOS.** macOS can't run Linux containers natively, so *something* has to provide a small Linux VM underneath — Docker Desktop is one way to do that, but not the only one. The standard non-Desktop combo is [Colima](https://github.com/abiosoft/colima) (a lightweight VM manager) plus the plain Docker CLI:

```bash
brew install colima docker docker-compose
colima start
```

`colima start` is the piece that actually launches the Linux VM and its Docker daemon; `docker`/`docker-compose` are just the client talking to it. Re-run `docker info` afterward to confirm.

**Known gap with this combo: `docker compose` (the space-separated subcommand form used throughout this walkthrough) often isn't recognized out of the box**, even though `docker-compose` (hyphenated) is installed and works fine — Homebrew's formula doesn't automatically register it as a CLI plugin. Fix it once by symlinking the plugin in:

```bash
mkdir -p ~/.docker/cli-plugins
ln -sfn "$(brew --prefix)/opt/docker-compose/bin/docker-compose" ~/.docker/cli-plugins/docker-compose
```

Then confirm with `docker compose version`. If it's still not picked up, don't keep fighting the plugin wiring — just use `docker-compose` (hyphenated) in place of every `docker compose` command in the rest of this walkthrough; the standalone binary does the same thing.

**Linux.** Docker Engine is the native, default install here — Docker Desktop is the optional add-on, not the norm, so this is already the "not Desktop" path. Follow the official engine install instructions for the distro at https://docs.docker.com/engine/install/, or use Docker's convenience script:

```bash
curl -fsSL https://get.docker.com | sh
```

After installing, add the user to the `docker` group so `sudo` isn't needed for every command, then log out and back in:

```bash
sudo usermod -aG docker $USER
```

**Windows.** The non-Desktop equivalent is running Docker Engine inside WSL2 directly, rather than installing Docker Desktop's Windows integration. This needs one WSL-specific step before the Linux instructions above will work: WSL2 distros don't run an init system by default, and Docker Engine expects one to manage the daemon as a service. Enable it first:

1. Install a distro if one isn't already there: `wsl --install` (from PowerShell), or `wsl --install -d Ubuntu` for a specific one.
2. Inside that distro, edit (or create) `/etc/wsl.conf` and add:
   ```
   [boot]
   systemd=true
   ```
3. Restart WSL from PowerShell: `wsl --shutdown`, then reopen the distro.
4. Now follow the Linux instructions above (the `get.docker.com` script and the `docker` group step) *inside* that distro.
5. Explicitly enable and start the service, since it won't come up on its own the first time: `sudo systemctl enable docker && sudo systemctl start docker`.

Then re-run `docker info` inside the WSL2 distro to confirm — recent WSL2 versions forward `localhost` between Windows and the distro automatically, so `curl localhost:8000/health` later in this walkthrough works from either side without extra networking setup.

**Optional: a UI for managing containers/images.** [Rancher Desktop](https://rancherdesktop.io/) is a common way to get a GUI without Docker Desktop's licensing. One important caveat: Rancher Desktop bundles its *own* container runtime — it isn't a UI layered on top of Colima/plain Docker Engine. If the user installs Rancher Desktop, they don't also need Colima; picking both means two competing runtimes on the same machine. Present it as an alternative to the CLI-only path above, not an addition to it, and let the user choose one.

Once installed, go back to Step 1 to re-verify before continuing.

## Step 3: pull the image

```bash
docker pull ghcr.io/tbwfdu/wingman:latest
```

This is a public image on GHCR — no login or token needed. If the pull fails with an auth-looking error (403, "unauthorized"), that's unusual for a public image and worth surfacing to the user verbatim rather than guessing a fix — it may be a transient GHCR issue or a change in image visibility, not something the local Docker setup did wrong.

## Step 4: generate the compose file and access key

Ask two things up front, with sensible defaults if the user doesn't care:
- **Where** to put the files (default: a new `wingman/` folder in the current directory).
- **Which port** to expose (default `8000`).

Generate an access key:

```bash
openssl rand -hex 32
```

(If `openssl` isn't available, `python3 -c "import secrets; print(secrets.token_hex(32))"` works the same way.)

Write a `.env` file next to the compose file:

```
WINGMAN_MCP_ACCESS_KEY=<the generated key>
```

And a `docker-compose.yml`:

```yaml
services:
  wingman-mcp:
    image: ghcr.io/tbwfdu/wingman:latest
    ports:
      - "8000:8000"
    volumes:
      - wingman-stores:/data/stores
    environment:
      WINGMAN_MCP_ACCESS_KEY: ${WINGMAN_MCP_ACCESS_KEY:?set WINGMAN_MCP_ACCESS_KEY (e.g. in a .env file)}
    restart: unless-stopped

volumes:
  wingman-stores:
```

The `wingman-stores` volume matters — it's what persists the downloaded RAG stores across container restarts so they're only pulled once. Swap the port on both sides of `"8000:8000"` if the user asked for something else, and swap it in every URL from here on too.

Treat the generated key as a secret: it's fine to show it once so the user can copy it into an MCP client config, but don't repeat it back unnecessarily, and remind them not to commit the `.env` file to version control.

If the user wants a read-only key, an admin API, or anything else beyond this common case, point them at the full configuration table in `wingman-container/README.md` rather than expanding this walkthrough to cover every option.

## Step 5: deploy locally

```bash
docker compose up -d
```

Then poll health rather than checking once and giving up:

```bash
curl -s localhost:8000/health
```

**First boot downloads the RAG stores (~1.6 GB) before the server reports healthy — this can take a few minutes depending on the connection.** A non-`ok` response in the first minute or two is expected, not a failure. If it's still not healthy after several minutes, check `docker compose logs -f` before concluding something's wrong.

## Step 6: connect an MCP client

```json
{
  "mcpServers": {
    "wingman": {
      "type": "http",
      "url": "http://localhost:<port>/mcp",
      "headers": { "X-Wingman-Access-Key": "<the generated key>" }
    }
  }
}
```

## Wrap-up

Mention, briefly, that `docker compose logs -f` shows live server output and `docker compose down` stops it (the `wingman-stores` volume survives a `down`, so the RAG stores aren't re-downloaded on the next `up`). Point to `wingman-container/README.md` for anything beyond this common single-user setup — read-only keys, the admin API for shared credentials, or fronting it with a reverse proxy.
