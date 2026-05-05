"""CLI entry point for wingman-mcp."""
import argparse
import asyncio
import getpass
import json
import os
import sys
from pathlib import Path
from typing import Optional


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
        "all": (
            list(valid_keys)
            + [f"{s}_rn" for s in product_slugs]
            + [f"{s}_api" for s in product_slugs if PRODUCTS[s].api is not None]
        ),
        "docs": product_slugs,
        "rn": [f"{s}_rn" for s in product_slugs if PRODUCTS[s].release_notes is not None],
    }

    raw_targets = args.stores or ["all"]
    docs_targets: list[str] = []
    rn_targets: list[str] = []
    api_targets: list[str] = []
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
            elif k.endswith("_api"):
                slug = k[:-4]
                if slug not in product_slugs:
                    print(f"Error: unknown product in '{k}'.")
                    sys.exit(1)
                if PRODUCTS[slug].api is None and slug != "uem":
                    print(f"Error: {slug} has no REST API; '{k}' is not valid.")
                    sys.exit(1)
                api_targets.append(slug)
            elif k in valid_keys:
                if k in product_slugs:
                    docs_targets.append(k)
                else:
                    other_targets.append(k)
            else:
                print(f"Error: unknown store '{k}'. Run 'wingman-mcp ingest --list' for options.")
                sys.exit(1)

    embeddings = LocalEmbeddings()

    # Resolve API + RN target expansion before counting steps so the
    # progress total is accurate.
    if "api" in other_targets:
        api_targets = ["uem"] + [s for s in product_slugs if PRODUCTS[s].api is not None]
    if "release_notes" in other_targets:
        rn_targets = [s for s in product_slugs if PRODUCTS[s].release_notes is not None]

    # docs steps run in registry order; api / RN run in user-input order.
    ordered_docs = [s for s in product_slugs if s in docs_targets]
    total_steps = len(ordered_docs) + len(api_targets) + len(rn_targets)
    if total_steps == 0:
        print("Nothing to do. Run 'wingman-mcp ingest --list' to see options.")
        return

    print(f"\nIngesting across {total_steps} step(s)...")
    import time
    t_start = time.time()
    step = 0

    # --- Phase 1: per-product docs ---
    for slug in ordered_docs:
        step += 1
        print(f"\n[{step}/{total_steps}] Ingesting {slug} documentation")
        from wingman_mcp.ingest.ingest_docs import ingest_product
        ingest_product(
            product=PRODUCTS[slug],
            store_dir=get_store_dir(slug),
            embeddings=embeddings,
            max_workers=args.max_workers,
            batch_size=args.batch_size,
        )

    # --- Phase 2: API references (one step per product) ---
    if api_targets:
        from wingman_mcp.ingest.ingest_api import ingest_api, ingest_api_for_product
        for slug in api_targets:
            step += 1
            print(f"\n[{step}/{total_steps}] Ingesting API reference for {slug}")
            if slug == "uem":
                ingest_api(store_dir=get_store_dir("api"), embeddings=embeddings)
            else:
                ingest_api_for_product(
                    slug=slug,
                    store_dir=get_store_dir("api"),
                    embeddings=embeddings,
                )

    # --- Phase 3: release notes (one step per product) ---
    if rn_targets:
        from wingman_mcp.ingest.ingest_release_notes import ingest_release_notes
        for slug in rn_targets:
            step += 1
            print(f"\n[{step}/{total_steps}] Ingesting release notes for {slug}")
            ingest_release_notes(
                store_dir=get_store_dir("release_notes"),
                embeddings=embeddings,
                products=[slug],
            )

    elapsed = int(time.time() - t_start)
    mins, secs = divmod(elapsed, 60)
    print(f"\nIngestion complete: {step}/{total_steps} steps in {mins}m {secs}s.")


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
        "all": (
            list(valid_keys)
            + [f"{s}_rn" for s in product_slugs]
            + [f"{s}_api" for s in product_slugs if PRODUCTS[s].api is not None]
        ),
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
            elif k.endswith("_api"):
                slug = k[:-4]
                if slug not in product_slugs:
                    print(f"Error: unknown product in '{k}'.")
                    sys.exit(1)
                if PRODUCTS[slug].api is None and slug != "uem":
                    print(f"Error: {slug} has no REST API; '{k}' is not valid.")
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
    from wingman_mcp.credentials import (
        known_products,
        list_product_environments,
        _product_env_status,
    )
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

    print("\nProduct API Credentials:")
    any_configured = False
    for product in known_products():
        envs = list_product_environments(product)
        if not envs:
            continue
        any_configured = True
        print(f"  [{product}]")
        for name in envs:
            status = _product_env_status(product, name)
            url = (status.get("api_base_url")
                   or status.get("server_url")
                   or status.get("manager_url")
                   or status.get("tenant_url")
                   or "(missing)")
            configured = status.get("configured", "no")
            marker = "+" if configured == "yes" else "-"
            print(f"    [{marker}] {name}: {url}")
    if not any_configured:
        print("  No products configured. Run 'wingman-mcp auth set --product <slug>'.")


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

_FRIENDLY_PROMPTS: dict[str, dict[str, str]] = {
    # Per-product field prompts.  Falls back to the field name if missing.
    "uem": {
        "client_id": "Client ID",
        "client_secret": "Client Secret",
        "token_url": "OAuth Token URL (e.g. https://na.uemauth.workspaceone.com/connect/token)",
        "api_base_url": "UEM API Base URL (e.g. https://as1831.awmdm.com)",
    },
    "horizon": {
        "username": "Horizon admin username",
        "password": "Horizon admin password",
        "server_url": "Connection Server URL (e.g. https://horizon.example.com)",
        "domain": "Active Directory domain (e.g. CORP)",
    },
    "horizon_cloud": {
        "client_id": "CSP API Client ID",
        "client_secret": "CSP API Client Secret",
        "api_base_url": "Horizon Cloud API base (e.g. https://cloud-sg.horizon.omnissa.com)",
        "org_id": "Organization (tenant) ID",
    },
    "app_volumes": {
        "username": "AV Manager admin username",
        "password": "AV Manager admin password",
        "manager_url": "App Volumes Manager URL (e.g. https://av.example.com)",
    },
    "access": {
        "client_id": "OAuth Client ID",
        "client_secret": "OAuth Client Secret",
        "tenant_url": "Access tenant URL (e.g. https://yourtenant.workspaceoneaccess.com)",
        "token_url": "OAuth Token URL",
    },
    "identity_service": {
        "client_id": "OAuth Client ID",
        "client_secret": "OAuth Client Secret",
        "tenant_url": "Identity Service tenant URL",
        "token_url": "OAuth Token URL",
    },
}


def _resolve_product(args) -> str:
    from wingman_mcp.credentials import known_products
    product = getattr(args, "product", None) or "uem"
    if product not in known_products():
        print(f"Error: unknown product '{product}'. Known: {known_products()}")
        sys.exit(1)
    return product


def cmd_auth(args):
    """Dispatch auth subcommands."""
    action = getattr(args, "auth_action", None)
    env_name = getattr(args, "env", "default")
    product = _resolve_product(args)
    if action == "set":
        _auth_set(product, env_name)
    elif action == "status":
        _auth_status(product, env_name)
    elif action == "clear":
        _auth_clear(product, env_name)
    elif action == "test":
        _auth_test(product, env_name)
    elif action == "list":
        _auth_list(getattr(args, "product", None))
    else:
        print("Usage: wingman-mcp auth {set,status,clear,test,list} [--product <slug>]")
        sys.exit(1)


def _prompt_for_field(product: str, field_name: str, secret: bool) -> str:
    label = _FRIENDLY_PROMPTS.get(product, {}).get(field_name, field_name)
    if secret:
        val = getpass.getpass(f"{label}: ").strip()
    else:
        val = input(f"{label}: ").strip()
    if not val:
        print(f"Error: {label} is required.")
        sys.exit(1)
    return val


def _auth_set(product: str, env_name: str):
    from wingman_mcp.credentials import get_schema, save_product_credentials

    schema = get_schema(product)
    print(f"Configure {schema.label} credentials (environment: {env_name})")
    print("(secrets are stored in your OS keychain)\n")

    fields: dict[str, str] = {}
    # Prompt non-secrets first (history-friendly), then secrets.
    for k in schema.config_keys:
        fields[k] = _prompt_for_field(product, k, secret=False)
    for k in schema.secret_keys:
        secret = "secret" in k or "password" in k
        fields[k] = _prompt_for_field(product, k, secret=secret)

    save_product_credentials(product, env_name, **fields)
    print(f"\nCredentials saved: product={product} env={env_name}")


def _auth_status(product: str, env_name: str):
    from wingman_mcp.credentials import _product_env_status

    status = _product_env_status(product, env_name)
    print(f"  [{product}/{env_name}]")
    for k, v in status.items():
        print(f"    {k}: {v}")


def _auth_clear(product: str, env_name: str):
    from wingman_mcp.credentials import clear_product_credentials

    clear_product_credentials(product, env_name)
    print(f"Credentials cleared: product={product} env={env_name}")


def _auth_test(product: str, env_name: str):
    """Test that credentials load and (for UEM) acquire a token."""
    from wingman_mcp.credentials import load_product_credentials

    creds = load_product_credentials(product, env_name)
    if creds is None:
        print(f"Error: credentials not configured for product='{product}' env='{env_name}'. "
              f"Run 'wingman-mcp auth set --product {product} --env {env_name}' first.")
        sys.exit(1)

    if product == "uem":
        from wingman_mcp.credentials import load_credentials
        from wingman_mcp.auth import UEMAuth

        uem_creds = load_credentials(env_name)
        print(f"Testing UEM connection for environment '{env_name}' to {uem_creds['token_url']} ...")
        auth = UEMAuth(uem_creds)
        result = auth.test_connection()

        if result["success"]:
            print(f"  Success! Token valid for ~{result['expires_in']}s")
            print(f"  API base URL: {result['api_base_url']}")
        else:
            print(f"  Failed: {result['error']}")
            sys.exit(1)
        return

    # Other products: just confirm fields are loadable.  Token acquisition
    # for non-UEM products is exercised by the per-product API clients
    # (added in later phases).
    print(f"Credentials present for product='{product}' env='{env_name}'.")
    for k, v in creds.items():
        if k in ("password", "client_secret"):
            v = "(set)"
        print(f"  {k}: {v}")


def _auth_list(product: Optional[str]):
    from wingman_mcp.credentials import (
        known_products,
        list_product_environments,
        _product_env_status,
    )

    products = [product] if product else known_products()
    any_configured = False
    for p in products:
        envs = list_product_environments(p)
        if not envs:
            if product:  # only complain when a specific product was asked for
                print(f"  No environments configured for product='{p}'.")
                print(f"  Run 'wingman-mcp auth set --product {p} --env <name>' to add one.")
            continue
        any_configured = True
        print(f"  [{p}] {len(envs)} environment(s):")
        for name in envs:
            status = _product_env_status(p, name)
            url = (status.get("api_base_url")
                   or status.get("server_url")
                   or status.get("manager_url")
                   or status.get("tenant_url")
                   or "(missing)")
            configured = status.get("configured", "no")
            marker = "+" if configured == "yes" else "-"
            print(f"    [{marker}] {name}: {url}")
    if not any_configured and not product:
        print("  No environments configured for any product.")
        print("  Run 'wingman-mcp auth set --product <slug> --env <name>' to add one.")


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

    auth_parser = sub.add_parser("auth", help="Manage product API credentials")
    auth_sub = auth_parser.add_subparsers(dest="auth_action")

    for name, help_text in [
        ("set", "Set product API credentials (interactive)"),
        ("status", "Show auth configuration for a product+env"),
        ("clear", "Remove stored credentials"),
        ("test", "Test credential loading (UEM also tests OAuth token fetch)"),
    ]:
        p = auth_sub.add_parser(name, help=help_text)
        p.add_argument("--product", "-p", default="uem",
                        help="Product slug (default: 'uem'). "
                             "One of: uem, horizon, horizon_cloud, app_volumes, access, identity_service")
        p.add_argument("--env", "-e", default="default",
                        help="Environment name (default: 'default')")

    list_p = auth_sub.add_parser("list", help="List all configured environments")
    list_p.add_argument("--product", "-p", default=None,
                         help="Limit to one product slug (default: show all)")

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
