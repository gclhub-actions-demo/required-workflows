import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import ValidationError


ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


policy = load("policy")
baseline = load("baseline")
render = load("render_rulesets")


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / ".github/ci").mkdir(parents=True)
        (self.root / "apps/python-service").mkdir(parents=True)
        self.manifest = {"version": 1, "projects": [{"id": "python", "path": "apps/python-service"}]}

    def validate(self):
        (self.root / ".github/app-ci.json").write_text(json.dumps(self.manifest))
        return policy.validate(self.root, "gclhub-actions-demo/python-app")

    def test_exact_project_policy(self):
        matrix, extensions = self.validate()
        self.assertEqual(matrix["include"][0]["coverage"], 80)
        self.assertEqual(extensions, [])

    def test_all_repository_profiles(self):
        for repository, projects in policy.load_json(ROOT / "policy/repositories.json").items():
            with self.subTest(repository=repository), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / ".github").mkdir()
                for project in projects:
                    (root / project["path"]).mkdir(parents=True, exist_ok=True)
                manifest = {"version": 1, "projects": [{k: p[k] for k in ("id", "path")} for p in projects]}
                (root / ".github/app-ci.json").write_text(json.dumps(manifest))
                self.assertEqual(policy.validate(root, repository)[0]["include"], projects)

    def test_omitted_duplicate_and_changed_projects(self):
        for projects in ([], self.manifest["projects"] * 2, [{"id": "node", "path": "."}],
                         [{"id": "python", "path": "."}]):
            with self.subTest(projects=projects):
                self.manifest["projects"] = projects
                with self.assertRaises((ValueError, ValidationError)):
                    self.validate()

    def test_no_overrides(self):
        for key in ("commands", "runner", "disable", "coverage", "python-version", "tests"):
            with self.subTest(key=key):
                self.manifest[key] = "override"
                with self.assertRaises(ValidationError):
                    self.validate()
                del self.manifest[key]

    def test_no_project_overrides(self):
        self.manifest["projects"][0]["coverage"] = 0
        with self.assertRaises(ValidationError):
            self.validate()

    def test_missing_manifest(self):
        with self.assertRaises(ValueError):
            policy.validate(self.root, "gclhub-actions-demo/python-app")

    def test_unknown_repository(self):
        with self.assertRaises(ValueError):
            policy.validate(self.root, "gclhub-actions-demo/not-authorized")

    def test_missing_project(self):
        (self.root / "apps/python-service").rmdir()
        with self.assertRaises(ValueError):
            self.validate()

    def test_extensions(self):
        (self.root / ".github/ci/preflight.sh").write_text("exit 0\n")
        self.manifest["extensions"] = {"preflight": ".github/ci/preflight.sh"}
        self.assertEqual(self.validate()[1][0]["phase"], "preflight")

    def test_missing_extension(self):
        self.manifest["extensions"] = {"postflight": ".github/ci/missing.sh"}
        with self.assertRaises(ValueError):
            self.validate()

    def test_unsafe_extensions(self):
        for path in ("../escape.sh", "/tmp/file.sh", ".github/../escape.sh",
                     ".github/ci/a.sh;echo", ".github/ci/a\n.sh", "echo hello"):
            with self.subTest(path=path):
                self.manifest["extensions"] = {"preflight": path}
                with self.assertRaises((ValueError, ValidationError)):
                    self.validate()

    def test_extension_cannot_contain_yaml(self):
        self.manifest["extensions"] = {"preflight": {"run": "echo hi"}}
        with self.assertRaises(ValidationError):
            self.validate()

    def test_symlink_manifest(self):
        source = self.root / "manifest.json"
        source.write_text(json.dumps(self.manifest))
        (self.root / ".github/app-ci.json").symlink_to(source)
        with self.assertRaises(ValueError):
            policy.validate(self.root, "gclhub-actions-demo/python-app")

    def test_symlink_project_parent(self):
        (self.root / "apps/python-service").rmdir()
        (self.root / "apps").rmdir()
        (self.root / "apps").symlink_to(self.root / ".github")
        with self.assertRaises(ValueError):
            self.validate()

    def test_symlink_script(self):
        (self.root / ".github/ci/preflight.sh").symlink_to("/etc/hosts")
        self.manifest["extensions"] = {"preflight": ".github/ci/preflight.sh"}
        with self.assertRaises(ValueError):
            self.validate()

    def test_duplicate_json_keys(self):
        path = self.root / "duplicate.json"
        path.write_text('{"version":1,"version":2}')
        with self.assertRaises(ValueError):
            policy.load_json(path)


class GateTests(unittest.TestCase):
    def needs(self):
        return {key: {"result": "success" if key in ("policy", "baseline") else "skipped"}
                for key in ("policy", "preflight", "baseline", "postflight")}

    def test_absent_extensions_are_explicitly_skipped(self):
        policy.gate(self.needs(), [])

    def test_configured_extensions_must_succeed(self):
        needs = self.needs()
        extensions = [{"phase": "preflight"}, {"phase": "postflight"}]
        with self.assertRaises(ValueError):
            policy.gate(needs, extensions)
        needs["preflight"]["result"] = needs["postflight"]["result"] = "success"
        policy.gate(needs, extensions)

    def test_failed_cancelled_skipped_baselines_never_pass(self):
        for result in ("failure", "cancelled", "skipped", "timed_out", "neutral"):
            needs = self.needs()
            needs["baseline"]["result"] = result
            with self.subTest(result=result), self.assertRaises(ValueError):
                policy.gate(needs, [])

    def test_policy_must_succeed(self):
        needs = self.needs()
        needs["policy"]["result"] = "failure"
        with self.assertRaises(ValueError):
            policy.gate(needs, [])

    def test_dependency_omission(self):
        needs = self.needs()
        del needs["baseline"]
        with self.assertRaises(ValueError):
            policy.gate(needs, [])

    def test_unexpected_extension_execution_rejected(self):
        needs = self.needs()
        needs["preflight"]["result"] = "success"
        with self.assertRaises(ValueError):
            policy.gate(needs, [])


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "report.xml"

    def test_missing_empty_skipped_failed_reports(self):
        with self.assertRaises(ValueError):
            baseline.test_reports([])
        for content in ('<testsuite/>', '<testsuite><testcase><skipped/></testcase></testsuite>',
                        '<testsuite><testcase><failure/></testcase></testsuite>'):
            self.path.write_text(content)
            with self.subTest(content=content), self.assertRaises(ValueError):
                baseline.test_reports([self.path])

    def test_nonzero_executed_report(self):
        self.path.write_text('<testsuite><testcase name="real"/></testsuite>')
        baseline.test_reports([self.path])

    def test_measured_coverage_and_threshold(self):
        self.path.write_text('<coverage lines-valid="10" lines-covered="8"/>')
        baseline.coverage_xml(self.path, "cobertura", 80)
        with self.assertRaises(ValueError):
            baseline.coverage_xml(self.path, "cobertura", 81)

    def test_empty_coverage_never_passes(self):
        for total, covered in ((0, 0), (10, 0), (5, 6)):
            self.path.write_text(f'<coverage lines-valid="{total}" lines-covered="{covered}"/>')
            with self.assertRaises(ValueError):
                baseline.coverage_xml(self.path, "cobertura", None)

    def test_jacoco_package_minimum(self):
        self.path.write_text(
            '<report><package name="p"><counter type="LINE" covered="6" missed="4"/>'
            '</package><counter type="LINE" covered="9" missed="1"/></report>')
        with self.assertRaises(ValueError):
            baseline.coverage_xml(self.path, "jacoco", 70)


class DeploymentTests(unittest.TestCase):
    def test_rendered_rulesets_remain_disabled(self):
        application, central, owners = render.render("a" * 40)
        self.assertEqual(application["enforcement"], "disabled")
        self.assertEqual(central["enforcement"], "disabled")
        self.assertEqual(application["bypass_actors"], [])
        self.assertEqual(application["conditions"]["repository_name"]["include"],
                         ["github-actions-demo", "java-app-demo", "python-app"])
        workflow = application["rules"][-1]["parameters"]["workflows"][0]
        self.assertEqual(workflow["sha"], "a" * 40)
        self.assertNotIn("ref", workflow)
        self.assertEqual(owners, "* @gclhub\n")

    def test_mutable_revision_rejected(self):
        for sha in ("main", "latest", "a" * 39):
            with self.assertRaises(ValueError):
                render.render(sha)


if __name__ == "__main__":
    unittest.main()
