"""Render inactive deployment artifacts locally; never call the GitHub API."""

import argparse
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def render(sha):
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("central revision must be an immutable 40-character commit SHA")
    application = json.loads((ROOT / "rulesets/application-main.json").read_text())
    application["rules"][-1]["parameters"]["workflows"][0]["sha"] = sha
    central = json.loads((ROOT / "rulesets/central-main.json").read_text())
    owners = (ROOT / ".github/CODEOWNERS").read_text()
    return application, central, owners


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--central-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    application, central, owners = render(args.central_sha)
    args.output.mkdir(parents=True, exist_ok=True)
    for name, value in (("application-main.json", application), ("central-main.json", central)):
        (args.output / name).write_text(json.dumps(value, indent=2) + "\n")
    (args.output / "CODEOWNERS").write_text(owners)


if __name__ == "__main__":
    main()
