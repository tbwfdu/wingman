"""CLI for the wingman-mcp bridge.

Approved users run `wingman-mcp-bridge` to proxy a local stdio MCP server
to the remote, Entra-protected wingman-mcp HTTP server. Credentials stay
in the OS keychain; nothing sensitive is written to Claude config files.
"""
import argparse
import asyncio
import sys

from wingman_mcp_bridge import bridge, oauth_client
from wingman_mcp_bridge.link import link_claude

DEFAULT_REMOTE_URL = bridge.DEFAULT_REMOTE_URL


def cmd_serve(args):
    """Run the bridge over stdio."""
    asyncio.run(bridge.run(remote_url=args.remote, env_name=args.env))


def cmd_login(args):
    """Sign in to the remote server; cache the token in the keychain."""
    try:
        asyncio.run(oauth_client.login(args.remote))
    except oauth_client.OAuthError as exc:
        sys.stderr.write(f"Sign-in failed: {exc}\n")
        sys.exit(1)


def cmd_logout(args):
    """Clear the cached token for the remote server."""
    oauth_client.clear_bundle(args.remote)
    print(f"Cleared cached token for {oauth_client.host_of(args.remote)}.")


def cmd_link(args):
    """Write the bridge entry into Claude Desktop / Claude Code config."""
    rc = link_claude(
        client=args.client,
        server_url=args.server,
        entry_name=args.entry_name,
        products=args.product,
        env_name=args.env,
        dry_run=args.dry_run,
        legacy_headers=args.legacy_headers,
    )
    sys.exit(rc)


def _add_remote_arg(parser):
    parser.add_argument(
        "--remote", "-r", default=DEFAULT_REMOTE_URL, metavar="URL",
        help="Remote wingman-mcp server URL (default: %(default)s)")


def main():
    parser = argparse.ArgumentParser(
        prog="wingman-mcp-bridge",
        description="Local stdio bridge to a remote wingman-mcp server",
    )
    sub = parser.add_subparsers(dest="command")

    serve_p = sub.add_parser("serve", help="Run the bridge over stdio")
    _add_remote_arg(serve_p)
    serve_p.add_argument(
        "--env", "-e", default="default",
        help="Credentials environment name (default: %(default)s)")

    login_p = sub.add_parser("login", help="Sign in to the remote server")
    _add_remote_arg(login_p)

    logout_p = sub.add_parser("logout", help="Clear the cached token")
    _add_remote_arg(logout_p)

    link_p = sub.add_parser(
        "link", help="Write a Wingman entry into Claude Desktop / Claude Code config")
    link_p.add_argument(
        "--server", "-s", default=DEFAULT_REMOTE_URL,
        help="Remote wingman-mcp server URL (default: %(default)s)")
    link_p.add_argument(
        "--entry-name", "-n", default="wingman",
        help="Name of the mcpServers entry to create/update (default: %(default)s)")
    link_p.add_argument(
        "--client", "-c", choices=("desktop", "code", "both"), default="both",
        help="Which Claude client config to update (default: %(default)s)")
    link_p.add_argument(
        "--product", "-p", action="append", default=None,
        help="(--legacy-headers only) Limit to specific product slug(s). Repeatable.")
    link_p.add_argument(
        "--env", "-e", default="default",
        help="Credentials environment name (default: %(default)s)")
    link_p.add_argument(
        "--legacy-headers", action="store_true",
        help="Write the old type:http entry with credentials inlined as "
             "plaintext headers, instead of the default keychain-backed bridge entry.")
    link_p.add_argument(
        "--dry-run", action="store_true",
        help="Print the resulting config to stdout without writing files")

    args = parser.parse_args()
    if args.command == "serve":
        cmd_serve(args)
    elif args.command == "login":
        cmd_login(args)
    elif args.command == "logout":
        cmd_logout(args)
    elif args.command == "link":
        cmd_link(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
