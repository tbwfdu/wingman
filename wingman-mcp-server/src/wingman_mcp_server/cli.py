"""CLI for the wingman-mcp server (private / maintainer use).

Exposes the HTTP transport (`serve`) for hosted deployments and the RAG
ingestion commands (`ingest`, `check`) used to build and audit the vector
stores. This package is private; the public wingman-mcp CLI has none of
these subcommands.
"""
import argparse
import asyncio
import sys
import time


def cmd_serve(args):
    """Run the MCP server over Streamable HTTP."""
    from wingman_mcp_server.http_server import run_http_server
    asyncio.run(run_http_server(host=args.host, port=args.port))


def cmd_ingest(args):
    """Run ingestion scripts to build the RAG stores."""
    from wingman_mcp.embeddings import LocalEmbeddings
    from wingman_mcp.config import get_store_dir, get_store_keys
    from wingman_mcp.products import PRODUCTS, list_product_slugs

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
                print(f"Error: unknown store '{k}'. Run 'wingman-mcp-server ingest --list' for options.")
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
        print("Nothing to do. Run 'wingman-mcp-server ingest --list' to see options.")
        return

    print(f"\nIngesting across {total_steps} step(s)...")
    t_start = time.time()
    step = 0

    # --- Phase 1: per-product docs ---
    for slug in ordered_docs:
        step += 1
        print(f"\n[{step}/{total_steps}] Ingesting {slug} documentation")
        from wingman_mcp_server.ingest.ingest_docs import ingest_product
        ingest_product(
            product=PRODUCTS[slug],
            store_dir=get_store_dir(slug),
            embeddings=embeddings,
            max_workers=args.max_workers,
            batch_size=args.batch_size,
        )

    # --- Phase 2: API references (one step per product) ---
    if api_targets:
        from wingman_mcp_server.ingest.ingest_api import ingest_api, ingest_api_for_product
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
        from wingman_mcp_server.ingest.ingest_release_notes import ingest_release_notes
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
    from wingman_mcp_server.ingest.check import check_all
    from wingman_mcp.config import get_store_keys
    from wingman_mcp.products import PRODUCTS, list_product_slugs

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


def main():
    parser = argparse.ArgumentParser(
        prog="wingman-mcp-server",
        description="wingman-mcp HTTP server and RAG ingestion (maintainer use)",
    )
    sub = parser.add_subparsers(dest="command")

    serve_p = sub.add_parser("serve", help="Run the MCP server over Streamable HTTP")
    serve_p.add_argument("--host", default="0.0.0.0",
                         help="Bind host (default: 0.0.0.0)")
    serve_p.add_argument("--port", type=int, default=8000,
                         help="Bind port (default: 8000)")

    ingest_p = sub.add_parser("ingest", help="Build the RAG vector stores")
    ingest_p.add_argument("stores", nargs="*",
                          help="Stores/targets to ingest (default: all)")
    ingest_p.add_argument("--list", action="store_true",
                          help="List available stores and exit")
    ingest_p.add_argument("--max-workers", type=int, default=50)
    ingest_p.add_argument("--batch-size", type=int, default=500)

    check_p = sub.add_parser("check", help="Report what would change on a rebuild")
    check_p.add_argument("stores", nargs="*",
                         help="Stores/targets to check (default: all)")

    args = parser.parse_args()
    if args.command == "serve":
        cmd_serve(args)
    elif args.command == "ingest":
        cmd_ingest(args)
    elif args.command == "check":
        cmd_check(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
