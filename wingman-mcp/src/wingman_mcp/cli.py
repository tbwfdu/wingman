"""CLI entry point for wingman-mcp."""
import argparse
import asyncio
import getpass
import sys


def cmd_serve(args):
    """Run the MCP server."""
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

    from wingman_mcp.config import get_store_dir

    embeddings = LocalEmbeddings()
    targets = args.stores if args.stores else ["uem", "api", "release_notes"]

    if "api" in targets:
        print("\n--- Ingesting API reference ---")
        from wingman_mcp.ingest.ingest_api import ingest_api
        ingest_api(store_dir=get_store_dir("api"), embeddings=embeddings)

    if "release_notes" in targets:
        print("\n--- Ingesting release notes ---")
        from wingman_mcp.ingest.ingest_release_notes import ingest_release_notes
        ingest_release_notes(store_dir=get_store_dir("release_notes"), embeddings=embeddings)

    if "uem" in targets:
        print("\n--- Ingesting UEM documentation ---")
        from wingman_mcp.ingest.ingest_docs import ingest_docs
        ingest_docs(store_dir=get_store_dir("uem"), embeddings=embeddings,
                    max_workers=args.max_workers, batch_size=args.batch_size)

    print("\nIngestion complete.")


def cmd_status(args):
    """Show store status."""
    from wingman_mcp.config import get_store_dir, STORE_KEYS
    from wingman_mcp.credentials import get_status
    from pathlib import Path

    print("RAG Stores:")
    for key in STORE_KEYS:
        store_dir = Path(get_store_dir(key))
        db_file = store_dir / "chroma.sqlite3"
        if db_file.exists():
            size_mb = db_file.stat().st_size / (1024 * 1024)
            print(f"  {key}: {store_dir} ({size_mb:.1f} MB)")
        else:
            print(f"  {key}: not found ({store_dir})")

    print("\nUEM Auth:")
    status = get_status()
    for k, v in status.items():
        print(f"  {k}: {v}")


# ---------------------------------------------------------------------------
# auth subcommands
# ---------------------------------------------------------------------------

def cmd_auth(args):
    """Dispatch auth subcommands."""
    action = getattr(args, "auth_action", None)
    if action == "set":
        _auth_set()
    elif action == "status":
        _auth_status()
    elif action == "clear":
        _auth_clear()
    elif action == "test":
        _auth_test()
    else:
        print("Usage: wingman-mcp auth {set,status,clear,test}")
        sys.exit(1)


def _auth_set():
    from wingman_mcp.credentials import save_credentials

    print("Configure UEM API credentials")
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

    save_credentials(client_id, client_secret, token_url, api_base_url)
    print("\nCredentials saved.")


def _auth_status():
    from wingman_mcp.credentials import get_status

    status = get_status()
    for k, v in status.items():
        print(f"  {k}: {v}")


def _auth_clear():
    from wingman_mcp.credentials import clear_credentials

    clear_credentials()
    print("Credentials cleared.")


def _auth_test():
    from wingman_mcp.credentials import load_credentials
    from wingman_mcp.auth import UEMAuth

    creds = load_credentials()
    if creds is None:
        print("Error: UEM credentials not configured. Run 'wingman-mcp auth set' first.")
        sys.exit(1)

    print(f"Testing connection to {creds['token_url']} ...")
    auth = UEMAuth(creds)
    result = auth.test_connection()

    if result["success"]:
        print(f"  Success! Token valid for ~{result['expires_in']}s")
        print(f"  API base URL: {result['api_base_url']}")
    else:
        print(f"  Failed: {result['error']}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(prog="wingman-mcp", description="Workspace ONE UEM documentation search MCP server")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("serve", help="Run the MCP server (stdio transport)")
    sub.add_parser("setup", help="Download pre-built RAG stores")
    sub.add_parser("status", help="Show store and auth status")

    ingest_parser = sub.add_parser("ingest", help="Build RAG stores from source")
    ingest_parser.add_argument("stores", nargs="*", choices=["uem", "api", "release_notes"], help="Stores to ingest (default: all)")
    ingest_parser.add_argument("--max-workers", type=int, default=50, help="Parallel fetch workers (default: 50)")
    ingest_parser.add_argument("--batch-size", type=int, default=500, help="Embedding batch size (default: 500)")

    auth_parser = sub.add_parser("auth", help="Manage UEM API credentials")
    auth_sub = auth_parser.add_subparsers(dest="auth_action")
    auth_sub.add_parser("set", help="Set UEM API credentials (interactive)")
    auth_sub.add_parser("status", help="Show current auth configuration")
    auth_sub.add_parser("clear", help="Remove stored credentials")
    auth_sub.add_parser("test", help="Test OAuth token fetch")

    args = parser.parse_args()

    if args.command == "serve":
        cmd_serve(args)
    elif args.command == "setup":
        cmd_setup(args)
    elif args.command == "ingest":
        cmd_ingest(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "auth":
        cmd_auth(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
