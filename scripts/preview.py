"""Expand reviewed, immutable application fixtures for non-enforcing CI."""

import json
import os
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def matrices():
    policy = json.loads((ROOT / "policy/repositories.json").read_text())
    fixtures = json.loads((ROOT / "policy/fixtures.json").read_text())
    if set(fixtures) != set(policy):
        raise ValueError("preview must cover every governed repository")
    baselines = []
    repositories = []
    for repository, sha in fixtures.items():
        if not re.fullmatch(r"[0-9a-f]{40}", sha) or sha == "0" * 40:
            raise ValueError("preview fixtures require immutable application commit SHAs")
        repositories.append({"repository": repository, "ref": sha})
        for project in policy[repository]:
            baselines.append({"repository": repository, "ref": sha, "id": project["id"]})
    return {"include": baselines}, {"include": repositories}


def main():
    baselines, repositories = matrices()
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write(f"baselines={json.dumps(baselines, separators=(',', ':'))}\n")
        output.write(f"repositories={json.dumps(repositories, separators=(',', ':'))}\n")


if __name__ == "__main__":
    main()
