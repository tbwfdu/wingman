"""CLI entry point for wingman-mcp."""
import argparse
import asyncio
import getpass
import json
import os
import sys
from pathlib import Path


def cmd_serve(args):
    """Run the MCP server."""
    if args.http:
        from wingman_mcp.server import run_http_server
        asyncio.run(run_http_server(host=args.host, port=args.port))
    else:
        from wingman_mcp.server import run_server
        asyncio.run(run_server())


def cmd_setup(args):
    """Download pre-built stores from GitHub Releases."""
    print("Setup: downloading pre-built stores is not yet implemented.")
    print("Use 'wingman-mcp ingest' to build stores from source instead.")


def cmd_ingest(args):
    """Run ingestion scripts to build stores."""
    try:
        from wingman_mcp.embeddings import LocalEmbeddings
    except ImportError:
        print("The ingest command is not available in this distribution.")
        sys.exit(1)

    from wingman_mcp.config import get_store_dir, get_store_keys
    from wingman_mcp.ingest.products import PRODUCTS, list_product_slugs

    if getattr(args, "list", False):
        print("Available stores:\n")
        print("  Product documentation:")
        for slug in list_product_slugs():
            cfg = PRODUCTS[slug]
            print(f"    {slug:<18} {cfg.label}")
        print("\n  Combined stores:")
        print(f"    {'api':<18} REST API references — supports all products with APIs")
        print(f"    {'release_notes':<18} Release notes — supports all products")
        print("\n  Per-product axes (writes to combined stores):")
        print(f"    {'<slug>_rn':<18} e.g. horizon_rn — that product's release notes only")
        print(f"    {'<slug>_api':<18} e.g. horizon_api — that product's API spec only")
        print(f"    {' ':<18} (DEM and ThinApp have no API and reject *_api targets)")
        print("\n  Aliases:")
        print(f"    {'docs':<18} every product's documentation")
        print(f"    {'rn':<18} every product's release notes")
        print(f"    {'all':<18} everything (default when no targets given)")
        return

    product_slugs = list_product_slugs()
    valid_keys = set(get_store_keys())
    aliases = {
        "all": list(valid_keys) + [f"{s}_rn" for s in product_slugs],
        "docs": product_slugs,
        "rn": [f"{s}_rn" for s in product_slugs if PRODUCTS[s].release_notes is not None],
    }

    raw_targets = args.stores or ["all"]
    docs_targets: list[str] = []
    rn_targets: list[str] = []
    other_targets: list[str] = []
    seen: set[str] = set()

    for t in raw_targets:
        expanded = aliases.get(t, [t])
        for k in expanded:
            if k in seen:
                continue
            seen.add(k)
            if k.endswith("_rn"):
                slug = k[:-3]
                if slug not in product_slugs:
                    print(f"Error: unknown product in '{k}'.")
                    sys.exit(1)
                rn_targets.append(slug)
            elif k in valid_keys:
                if k in product_slugs:
                    docs_targets.append(k)
                else:
                    other_targets.append(k)
            else:
                print(f"Error: unknown store '{k}'. Run 'wingman-mcp ingest --list' for options.")
                sys.exit(1)

    embeddings = LocalEmbeddings()

    # Phase 1: per-product docs ingest
    for slug in product_slugs:
        if slug in docs_targets:
            print(f"\n--- Ingesting {slug} documentation ---")
            from wingman_mcp.ingest.ingest_docs import ingest_product
            ingest_product(
                product=PRODUCTS[slug],
                store_dir=get_store_dir(slug),
                embeddings=embeddings,
                max_workers=args.max_workers,
                batch_size=args.batch_size,
            )

    # Phase 2: API reference (single combined store)
    if "api" in other_targets:
        print("\n--- Ingesting API reference (UEM only in this plan) ---")
        from wingman_mcp.ingest.ingest_api import ingest_api
        ingest_api(store_dir=get_store_dir("api"), embeddings=embeddings)

    # Phase 3: release notes (combined store, per-product targets)
    if "release_notes" in other_targets:
        rn_targets = [s for s in product_slugs if PRODUCTS[s].release_notes is not None]
    if rn_targets:
        print(f"\n--- Ingesting release notes for: {', '.join(rn_targets)} ---")
        from wingman_mcp.ingest.ingest_release_notes import ingest_release_notes
        ingest_release_notes(
            store_dir=get_store_dir("release_notes"),
            embeddings=embeddings,
            products=rn_targets,
        )

    print("\nIngestion complete.")


def cmd_check(args):
    """Report what would change if stores were rebuilt."""
    try:
        from wingman_mcp.ingest.check import check_all
    except ImportError:
        print("The check command is not available in this distribution "
              "(ingest extras not installed). Run: pip install -e '.[ingest]'")
        sys.exit(1)

    from wingman_mcp.config import get_store_keys
    from wingman_mcp.ingest.products import PRODUCTS, list_product_slugs

    product_slugs = list_product_slugs()
    valid_keys = set(get_store_keys())
    aliases = {
        "all": list(valid_keys) + [f"{s}_rn" for s in product_slugs],
        "docs": product_slugs,
        "rn": [f"{s}_rn" for s in product_slugs if PRODUCTS[s].release_notes is not None],
    }

    raw_targets = args.stores or ["all"]
    targets: list[str] = []
    seen: set[str] = set()
    for t in raw_targets:
        expanded = aliases.get(t, [t])
        for k in expanded:
            if k in seen:
                continue
            seen.add(k)
            if k.endswith("_rn"):
                slug = k[:-3]
                if slug not in product_slugs:
                    print(f"Error: unknown product in '{k}'.")
                    sys.exit(1)
                targets.append(k)
            elif k in valid_keys:
                targets.append(k)
            else:
                print(f"Error: unknown store '{k}'.")
                sys.exit(1)
    check_all(targets)


def cmd_status(args):
    """Show store status."""
    from wingman_mcp.config import get_store_dir, get_store_keys
    from wingman_mcp.credentials import get_status, list_environments
    from pathlib import Path

    print("RAG Stores:")
    for key in get_store_keys():
        store_dir = Path(get_store_dir(key))
        db_file = store_dir / "chroma.sqlite3"
        if db_file.exists():
            size_mb = db_file.stat().st_size / (1024 * 1024)
            print(f"  {key}: {store_dir} ({size_mb:.1f} MB)")
        else:
            print(f"  {key}: not found ({store_dir})")

    print("\nUEM Auth:")
    envs = list_environments()
    if not envs:
        print("  No environments configured.")
    else:
        all_status = get_status()
        if "environments" in all_status:
            print(f"  {all_status['configured_environments']} environment(s)")
            for name, env_status in all_status["environments"].items():
                api_url = env_status.get("api_base_url", "(missing)")
                configured = env_status.get("configured", "no")
                marker = "+" if configured == "yes" else "-"
                print(f"  [{marker}] {name}: {api_url}")


def cmd_export(args):
    """Export all UEM resources to disk."""
    from wingman_mcp.credentials import load_credentials
    from wingman_mcp.auth import UEMAuth
    from wingman_mcp.export import export_all

    env_name = args.env
    creds = load_credentials(env_name)
    if creds is None:
        print(f"Error: credentials not configured for '{env_name}'. "
              f"Run 'wingman-mcp auth set --env {env_name}'.")
        sys.exit(1)

    auth = UEMAuth(creds)
    resource_types = args.types if args.types else None

    result = export_all(
        auth=auth,
        group_id=args.group_id,
        output_dir=args.output_dir,
        resource_types=resource_types,
        include_app_blobs=not args.no_blobs,
    )
    print(json.dumps(result, indent=2, default=str))


# ---------------------------------------------------------------------------
# auth subcommands
# ---------------------------------------------------------------------------

def cmd_auth(args):
    """Dispatch auth subcommands."""
    action = getattr(args, "auth_action", None)
    env_name = getattr(args, "env", "default")
    if action == "set":
        _auth_set(env_name)
    elif action == "status":
        _auth_status(env_name)
    elif action == "clear":
        _auth_clear(env_name)
    elif action == "test":
        _auth_test(env_name)
    elif action == "list":
        _auth_list()
    else:
        print("Usage: wingman-mcp auth {set,status,clear,test,list}")
        sys.exit(1)


def _auth_set(env_name: str):
    from wingman_mcp.credentials import save_credentials

    print(f"Configure UEM API credentials (environment: {env_name})")
    print("(secrets are stored in your OS keychain)\n")

    api_base_url = input("UEM API Base URL (e.g. https://as1831.awmdm.com): ").strip()
    if not api_base_url:
        print("Error: API base URL is required.")
        sys.exit(1)

    token_url = input("OAuth Token URL (e.g. https://na.uemauth.workspaceone.com/connect/token): ").strip()
    if not token_url:
        print("Error: Token URL is required.")
        sys.exit(1)

    client_id = input("Client ID: ").strip()
    if not client_id:
        print("Error: Client ID is required.")
        sys.exit(1)

    client_secret = getpass.getpass("Client Secret: ").strip()
    if not client_secret:
        print("Error: Client Secret is required.")
        sys.exit(1)

    save_credentials(client_id, client_secret, token_url, api_base_url, env_name=env_name)
    print(f"\nCredentials saved for environment '{env_name}'.")


def _auth_status(env_name: str):
    from wingman_mcp.credentials import get_status

    # If user explicitly passed --env, show that env; otherwise show all
    status = get_status(env_name)
    print(f"  [{env_name}]")
    for k, v in status.items():
        print(f"    {k}: {v}")


def _auth_clear(env_name: str):
    from wingman_mcp.credentials import clear_credentials

    clear_credentials(env_name)
    print(f"Credentials cleared for environment '{env_name}'.")


def _auth_test(env_name: str):
    from wingman_mcp.credentials import load_credentials
    from wingman_mcp.auth import UEMAuth

    creds = load_credentials(env_name)
    if creds is None:
        print(f"Error: UEM credentials not configured for environment '{env_name}'. "
              f"Run 'wingman-mcp auth set --env {env_name}' first.")
        sys.exit(1)

    print(f"Testing connection for environment '{env_name}' to {creds['token_url']} ...")
    auth = UEMAuth(creds)
    result = auth.test_connection()

    if result["success"]:
        print(f"  Success! Token valid for ~{result['expires_in']}s")
        print(f"  API base URL: {result['api_base_url']}")
    else:
        print(f"  Failed: {result['error']}")
        sys.exit(1)


def _auth_list():
    from wingman_mcp.credentials import list_environments, get_status

    envs = list_environments()
    if not envs:
        print("  No environments configured.")
        print("  Run 'wingman-mcp auth set --env <name>' to add one.")
        return

    print(f"  {len(envs)} environment(s) configured:\n")
    for name in envs:
        status = get_status(name)
        api_url = status.get("api_base_url", "(missing)")
        configured = status.get("configured", "no")
        marker = "+" if configured == "yes" else "-"
        print(f"  [{marker}] {name}: {api_url}")


def main():
    parser = argparse.ArgumentParser(prog="wingman-mcp", description="Workspace ONE UEM documentation search MCP server")
    sub = parser.add_subparsers(dest="command")

    serve_parser = sub.add_parser("serve", help="Run the MCP server (stdio or HTTP transport)")
    serve_parser.add_argument(
        "--http", action="store_true",
        help="Run over Streamable HTTP instead of stdio (for hosted deployments)",
    )
    serve_parser.add_argument(
        "--host", default="0.0.0.0",
        help="Bind host for HTTP mode (default: 0.0.0.0)",
    )
    serve_parser.add_argument(
        "--port", type=int, default=8000,
        help="Bind port for HTTP mode (default: 8000)",
    )
    sub.add_parser("setup", help="Download pre-built RAG stores")
    sub.add_parser("status", help="Show store and auth status")

    ingest_parser = sub.add_parser(
        "ingest",
        help="Build RAG stores from source (run 'wingman-mcp ingest --list' to see options)",
    )
    ingest_parser.add_argument(
        "stores", nargs="*",
        help="Stores to ingest. Use product slug (e.g. 'uem', 'horizon'), "
             "or aliases 'docs' (all product docs) / 'all' (everything). "
             "Default: all.",
    )
    ingest_parser.add_argument("--list", action="store_true",
                               help="List available product/store slugs and exit")
    ingest_parser.add_argument("--max-workers", type=int, default=50,
                               help="Parallel fetch workers (default: 50)")
    ingest_parser.add_argument("--batch-size", type=int, default=500,
                               help="Embedding batch size (default: 500)")

    check_parser = sub.add_parser("check", help="Report what would change if stores were rebuilt (no writes)")
    check_parser.add_argument(
        "stores", nargs="*",
        help="Stores to check. Same vocabulary as 'ingest'. Default: all.",
    )

    export_parser = sub.add_parser("export", help="Export all UEM resources to disk")
    export_parser.add_argument("--env", "-e", default="default", help="Environment name (default: 'default')")
    export_parser.add_argument("--group-id", "-g", default=None,
                               help="OG group ID code (default: top-level OG for the account)")
    export_parser.add_argument("--output-dir", "-o", default=os.path.join(str(Path.home()), ".wingman-mcp", "exports"),
                               help="Output directory (default: ~/.wingman-mcp/exports)")
    export_parser.add_argument("--types", nargs="+",
                               choices=["scripts", "sensors", "profiles", "apps"],
                               help="Resource types to export (default: all)")
    export_parser.add_argument("--no-blobs", action="store_true",
                               help="Skip downloading app binaries")

    auth_parser = sub.add_parser("auth", help="Manage UEM API credentials")
    auth_sub = auth_parser.add_subparsers(dest="auth_action")

    for name, help_text in [
        ("set", "Set UEM API credentials (interactive)"),
        ("status", "Show auth configuration (all envs if --env not specified)"),
        ("clear", "Remove stored credentials"),
        ("test", "Test OAuth token fetch"),
    ]:
        p = auth_sub.add_parser(name, help=help_text)
        p.add_argument("--env", "-e", default="default",
                        help="Environment name (default: 'default')")

    auth_sub.add_parser("list", help="List all configured environments")

    args = parser.parse_args()

    if args.command == "serve":
        cmd_serve(args)
    elif args.command == "setup":
        cmd_setup(args)
    elif args.command == "ingest":
        cmd_ingest(args)
    elif args.command == "check":
        cmd_check(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "export":
        cmd_export(args)
    elif args.command == "auth":
        cmd_auth(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
