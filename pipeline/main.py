"""Command-line entry point for the ScoringDiscrepNHL pipeline.

Usage:
  python3 -m pipeline.main update [--days N] [--max-games N] [--force-rebaseline]
  python3 -m pipeline.main probe
  python3 -m pipeline.main validate
  python3 -m pipeline.main serve [--port 8000]
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import shutil
import socketserver
import sys
import tempfile
from pathlib import Path

from . import config


def cmd_update(args) -> int:
    from . import monitor

    stats = monitor.update(days=args.days, max_games=args.max_games,
                           force_rebaseline=args.force_rebaseline)
    print(json.dumps(stats, indent=2))
    if stats["errors"]:
        # Surface source problems loudly (CI sees the non-zero exit), but keep the
        # data files that were written.
        return 1
    return 0


def cmd_probe(_args) -> int:
    from . import coverage_probe

    report = coverage_probe.run_probe()
    print(json.dumps(report["summary"], indent=2))
    ok = sum(1 for r in report["results"] if r["status"] == "ok")
    print(f"probe complete: {ok}/{len(report['results'])} sources reachable; "
          f"full results in {config.COVERAGE_PATH}")
    return 0


def cmd_validate(_args) -> int:
    from . import validate

    errors, stats = validate.validate_database()
    print(f"records: {stats['records']}  pending_review: {stats['pending_review']}  "
          f"confirmed: {stats['confirmed']}  errors: {stats['errors']}")
    for err in errors:
        print(f"  ERROR: {err}")
    return 1 if errors else 0


def cmd_serve(args) -> int:
    """Assemble site/ + data/ into one directory and serve it locally."""
    repo_root = config.REPO_ROOT
    build_dir = Path(tempfile.mkdtemp(prefix="sdnhl-site-"))
    shutil.copytree(repo_root / "site", build_dir, dirs_exist_ok=True)
    data_dest = build_dir / "data"
    if (repo_root / "data").exists():
        shutil.copytree(repo_root / "data", data_dest, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("snapshots"))
    os.chdir(build_dir)
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("0.0.0.0", args.port), handler) as httpd:
        print(f"Serving assembled site from {build_dir} on http://0.0.0.0:{args.port}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline.main",
                                     description="ScoringDiscrepNHL monitor pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    p_update = sub.add_parser("update", help="run one monitor cycle")
    p_update.add_argument("--days", type=int, default=None,
                          help=f"lookback window in days (default "
                               f"{config.DEFAULT_LOOKBACK_DAYS})")
    p_update.add_argument("--max-games", type=int, default=None,
                          help="cap games processed this cycle")
    p_update.add_argument("--force-rebaseline", action="store_true",
                          help="refresh snapshots without emitting alerts")
    p_update.set_defaults(func=cmd_update)

    p_probe = sub.add_parser("probe", help="probe official sources for coverage")
    p_probe.set_defaults(func=cmd_probe)

    p_validate = sub.add_parser("validate", help="validate data files")
    p_validate.set_defaults(func=cmd_validate)

    p_serve = sub.add_parser("serve", help="serve the site locally for development")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
