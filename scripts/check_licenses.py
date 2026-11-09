"""License inventory for runtime Python deps (pip-licenses) and web deps (package-lock), failing on
strong copyleft (GPL/AGPL/SSPL) in shipped runtime dependencies. LGPL/MPL are reported, not failed."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DENY = ("AGPL", "SSPL", "GNU General Public License", "GPL-2", "GPL-3", "GPLv2", "GPLv3")
DEV_ONLY = {"pytest", "ruff", "pip-audit", "pip-licenses", "pluggy", "iniconfig", "pygments", "cyclonedx-python-lib",
            "pip-requirements-parser", "pip-api", "license-expression", "boolean.py", "packageurl-python",
            "py-serializable", "sortedcontainers", "defusedxml", "cachecontrol", "msgpack", "toml", "tomli",
            "tomli_w", "rich", "markdown-it-py", "mdurl", "prettytable", "wcwidth", "platformdirs", "filelock"}


def py() -> list[dict]:
    out = subprocess.run([sys.executable, "-m", "piplicenses", "--format=json", "--with-system"],
                         capture_output=True, text=True, check=True).stdout
    return [{"name": r["Name"], "version": r["Version"], "license": r["License"], "ecosystem": "pypi"}
            for r in json.loads(out)]


def npm() -> list[dict]:
    lock = ROOT / "web" / "package-lock.json"
    if not lock.exists():
        return []
    pkgs = json.loads(lock.read_text()).get("packages", {})
    rows = []
    for path, meta in pkgs.items():
        if not path or meta.get("dev"):
            continue
        rows.append({"name": path.split("node_modules/")[-1], "version": meta.get("version"),
                     "license": meta.get("license", "UNKNOWN"), "ecosystem": "npm"})
    return rows


def main() -> int:
    rows = py() + npm()
    bad = [r for r in rows if r["name"].lower() not in DEV_ONLY and any(d in str(r["license"]) for d in DENY)
           and "LGPL" not in str(r["license"]) and "Lesser" not in str(r["license"])]
    (ROOT / "eval" / "reports").mkdir(parents=True, exist_ok=True)
    (ROOT / "eval" / "reports" / "licenses.json").write_text(json.dumps(sorted(rows, key=lambda r: (r["ecosystem"], r["name"])), indent=1) + "\n")
    weak = sorted({r["license"] for r in rows if any(x in str(r["license"]) for x in ("LGPL", "MPL", "Lesser"))})
    print(f"{len(rows)} runtime packages inventoried -> eval/reports/licenses.json")
    if weak:
        print("weak copyleft present (allowed, review before redistribution):", weak)
    for r in bad:
        print("DENIED LICENSE:", r)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
