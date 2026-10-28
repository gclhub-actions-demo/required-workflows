"""Trusted policy validation; never import application-owned Python modules."""

import argparse
import json
import os
from pathlib import Path
import stat


CENTRAL = Path(__file__).resolve().parents[1]


def load_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(), object_pairs_hook=unique)


def safe_path(root, relative, directory=False):
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("invalid relative path")
    parts = relative.split("/")
    if relative != "." and any(p in ("", ".", "..") for p in parts):
        raise ValueError(f"noncanonical path: {relative}")
    if Path(relative).is_absolute():
        raise ValueError("absolute paths forbidden")
    candidate = root
    for part in parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError(f"symlink forbidden: {relative}")
    candidate.resolve().relative_to(root.resolve())
    if directory:
        if not candidate.is_dir():
            raise ValueError(f"missing project directory: {relative}")
    elif not candidate.is_file() or not stat.S_ISREG(candidate.stat().st_mode):
        raise ValueError(f"missing regular file: {relative}")
    return candidate


def validate(root, repository):
    from jsonschema import Draft202012Validator
    policy = load_json(CENTRAL / "policy/repositories.json")
    if repository not in policy:
        raise ValueError(f"repository not authorized: {repository}")
    manifest = load_json(safe_path(root, ".github/app-ci.json"))
    Draft202012Validator(load_json(CENTRAL / "schema/app-ci.schema.json")).validate(manifest)
    expected = policy[repository]
    projects = manifest["projects"]
    if sorted((p["id"], p["path"]) for p in projects) != sorted(
        (p["id"], p["path"]) for p in expected
    ):
        raise ValueError("projects must exactly match central policy (no omissions or duplicates)")
    for project in expected:
        safe_path(root, project["path"], directory=True)
    extensions = []
    for phase, script in manifest.get("extensions", {}).items():
        safe_path(root, script)
        extensions.append({"phase": phase, "script": script})
    return {"include": expected}, extensions


def gate(needs, extensions):
    expected = {"policy", "preflight", "baseline", "postflight"}
    if set(needs) != expected or needs["policy"]["result"] != "success":
        raise ValueError("policy failed or dependency set changed")
    if needs["baseline"]["result"] != "success":
        raise ValueError("every baseline matrix job must succeed")
    for phase in ("preflight", "postflight"):
        wanted = "success" if any(e["phase"] == phase for e in extensions) else "skipped"
        if needs[phase]["result"] != wanted:
            raise ValueError(f"{phase}: expected {wanted}, got {needs[phase]['result']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["validate", "gate"])
    parser.add_argument("--root", type=Path)
    parser.add_argument("--repository")
    args = parser.parse_args()
    if args.command == "gate":
        gate(json.loads(os.environ["NEEDS"]), json.loads(os.environ["EXTENSIONS"]))
        return
    matrix, extensions = validate(args.root.resolve(), args.repository)
    outputs = {
        "matrix": matrix, "extensions": extensions,
        "preflight": {"include": [e for e in extensions if e["phase"] == "preflight"]},
        "postflight": {"include": [e for e in extensions if e["phase"] == "postflight"]},
        "has_preflight": any(e["phase"] == "preflight" for e in extensions),
        "has_postflight": any(e["phase"] == "postflight" for e in extensions),
    }
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        for key, value in outputs.items():
            output.write(f"{key}={json.dumps(value, separators=(',', ':'))}\n")


if __name__ == "__main__":
    main()
