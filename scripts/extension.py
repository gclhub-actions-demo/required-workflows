"""Revalidate the selected additive hook before executing in its own job."""

import argparse
import importlib.util
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--phase", choices=["preflight", "postflight"], required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("central_policy", Path(__file__).with_name("policy.py"))
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)
    root = args.root.resolve()
    _, extensions = policy.validate(root, args.repository)
    script = next(e["script"] for e in extensions if e["phase"] == args.phase)
    subprocess.run(["bash", "--noprofile", "--norc", "-euo", "pipefail", script],
                   cwd=root, check=True, timeout=600)


if __name__ == "__main__":
    main()
