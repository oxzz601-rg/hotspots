"""The ``hotspots`` command line."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from . import __version__
from .core import analyze, human_report, render_html


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="hotspots",
        description="Rank files by churn x complexity so you know where refactoring pays off.",
    )
    parser.add_argument("path", nargs="?", default=".", help="repository path (default: current directory)")
    parser.add_argument("--since", help='git date filter, e.g. "1 year ago" or "2024-01-01"')
    parser.add_argument("--ext", action="append", default=[], help="only files ending with this, repeatable")
    parser.add_argument("--top", type=int, default=20, help="how many files to show (default: 20)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    parser.add_argument("--html", help="also write a browsable HTML report")
    parser.add_argument("--version", action="version", version="hotspots {}".format(__version__))
    args = parser.parse_args(argv)

    try:
        report = analyze(args.path, since=args.since, extensions=tuple(args.ext) or None)
    except RuntimeError as exc:
        print("hotspots: {}".format(exc), file=sys.stderr)
        return 2

    if args.json:
        payload = report.to_dict()
        payload["files"] = payload["files"][: args.top]
        print(json.dumps(payload, indent=2))
        return 0

    print(human_report(report, limit=args.top), end="")
    if args.html:
        pathlib.Path(args.html).write_text(render_html(report), encoding="utf-8")
        print("\nwrote {}".format(args.html), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
