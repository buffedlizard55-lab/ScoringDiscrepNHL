#!/usr/bin/env python3
"""Assemble the static site into ``_site/`` (used by the Pages workflow and for
local preview).

    python3 tools/build_site.py
    python3 -m http.server 8080 --directory _site

The build is intentionally trivial: static files plus a copy of the JSON that the
collector commits. There is no bundler and no third-party dependency, so what is
published is byte-for-byte what is in the repository.
"""

from __future__ import annotations

import json
import os
import shutil
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE_SRC = os.path.join(REPO_ROOT, "site")
OUT = os.path.join(REPO_ROOT, "_site")

#: files copied into _site/data/<subpath> ; the site fetches them relative to itself
DATA_FILES = {
    "records/discrepancies.json": "data/records/discrepancies.json",
    "taxonomy.json": "data/taxonomy.json",
    "reference/verified_facts.json": "data/reference/verified_facts.json",
    "reference/sources.json": "data/reference/sources.json",
    "schema/observed_vocabulary.json": "data/schema/observed_vocabulary.json",
    "alerts/index.json": "data/alerts/index.json",
}


def main() -> int:
    sys.path.insert(0, os.path.join(REPO_ROOT, "src"))
    from nhl_monitor import alerts as alerts_mod  # noqa: E402
    from nhl_monitor import sources as sources_mod  # noqa: E402

    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    shutil.copytree(SITE_SRC, OUT)

    written = []
    # the source registry is always regenerated so the site can never show a stale
    # verification status
    registry_path = os.path.join(REPO_ROOT, "data", "reference", "sources.json")
    os.makedirs(os.path.dirname(registry_path), exist_ok=True)
    with open(registry_path, "w") as fh:
        json.dump(sources_mod.registry_as_dict(), fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    written.append(registry_path)

    written.extend(alerts_mod.write_alert_index(root=os.path.join(REPO_ROOT, "data", "alerts")))

    missing = []
    for rel_out, rel_src in DATA_FILES.items():
        src = os.path.join(REPO_ROOT, rel_src)
        dst = os.path.join(OUT, "data", rel_out)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if not os.path.exists(src):
            missing.append(rel_src)
            continue
        shutil.copy2(src, dst)

    # make google/github pages happy without extra config
    open(os.path.join(OUT, ".nojekyll"), "w").close()

    print(json.dumps({
        "built": OUT,
        "copied": sorted(DATA_FILES),
        "missing_optional": missing,
        "regenerated": written,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
