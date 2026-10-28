from pathlib import Path
import re
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class WorkflowContractTests(unittest.TestCase):
    def test_external_actions_are_pinned_and_no_pr_owned_actions(self):
        for path in (ROOT / ".github").rglob("*.yml"):
            workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
            jobs = workflow.get("jobs", {})
            steps = workflow.get("runs", {}).get("steps", [])
            steps += [step for job in jobs.values() for step in job.get("steps", [])]
            for step in steps:
                action = step.get("uses")
                if action and action.startswith("./"):
                    self.assertEqual(action, "./central/.github/actions/toolchains")
                elif action:
                    self.assertRegex(action, r"^[^@]+@[0-9a-f]{40}$")

    def test_required_workflow_trust_and_isolation(self):
        source = (ROOT / ".github/workflows/required-pr.yml").read_text()
        workflow = yaml.load(source, Loader=yaml.BaseLoader)
        self.assertEqual(set(workflow["on"]), {"pull_request"})
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        self.assertNotIn("concurrency", workflow)
        self.assertNotIn("secrets", workflow)
        self.assertNotIn("continue-on-error", source)
        self.assertNotRegex(source, r"actions/(?:cache|upload-artifact|download-artifact)@")
        jobs = workflow["jobs"]
        self.assertEqual(set(jobs), {"policy", "baseline", "preflight", "postflight", "final-gate"})
        for job in jobs.values():
            self.assertEqual(job["runs-on"], "ubuntu-24.04")
            for step in job["steps"]:
                if step.get("uses", "").startswith("actions/checkout@"):
                    options = step["with"]
                    self.assertEqual(options["persist-credentials"], "false")
                    if options["path"] == "central":
                        self.assertEqual(options["repository"], "gclhub-actions-demo/required-workflows")
                        self.assertEqual(options["ref"], "${{ github.workflow_sha }}")
                    else:
                        self.assertEqual(options["path"], "app")
                        self.assertEqual(options["ref"], "${{ github.sha }}")
        self.assertIn("always()", jobs["final-gate"]["if"])
        self.assertEqual(set(jobs["final-gate"]["needs"]),
                         {"policy", "preflight", "baseline", "postflight"})
        self.assertEqual(jobs["baseline"]["strategy"]["fail-fast"], "false")

    def test_no_reusable_workflow_or_codeql_shortcut(self):
        text = (ROOT / ".github/workflows/required-pr.yml").read_text()
        self.assertNotIn("workflow_call", text)
        self.assertNotIn("pull_request_target", text)
        self.assertNotIn("codeql-action", text)


if __name__ == "__main__":
    unittest.main()
