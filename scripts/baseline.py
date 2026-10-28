"""Fixed central build profiles and report verification.

Application build code remains untrusted and may forge reports. Isolation and a
trusted workflow identity do not make arbitrary application build code attestable.
"""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET


CENTRAL = Path(__file__).resolve().parents[1]


def run(*args, cwd):
    subprocess.run(args, cwd=cwd, check=True)


def clear_outputs(project, names):
    for name in names:
        path = project / name
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.exists():
            shutil.rmtree(path)


def test_reports(paths):
    paths = list(paths)
    if not paths:
        raise ValueError("missing test reports")
    executed = 0
    for path in paths:
        cases = list(ET.parse(path).getroot().iter("testcase"))
        executed += sum(1 for case in cases if case.find("skipped") is None)
        if any(case.find("failure") is not None or case.find("error") is not None for case in cases):
            raise ValueError(f"failed test report: {path}")
    if executed < 1:
        raise ValueError("no executed tests")


def coverage_xml(path, kind, minimum):
    root = ET.parse(path).getroot()
    if kind == "jacoco":
        counters = root.findall("./counter[@type='LINE']")
        if not counters:
            raise ValueError("missing JaCoCo LINE coverage")
        covered = int(counters[0].attrib["covered"])
        total = covered + int(counters[0].attrib["missed"])
        if minimum is not None:
            packages = root.findall("./package")
            if not packages:
                raise ValueError("missing JaCoCo package coverage")
            for package in packages:
                counter = package.find("./counter[@type='LINE']")
                if counter is None:
                    raise ValueError("missing package LINE counter")
                count = int(counter.attrib["covered"]) + int(counter.attrib["missed"])
                if count and 100 * int(counter.attrib["covered"]) / count < minimum:
                    raise ValueError("package coverage below central minimum")
    else:
        total = int(root.attrib["lines-valid"])
        covered = int(root.attrib["lines-covered"])
    if total <= 0 or covered <= 0 or covered > total:
        raise ValueError("missing or invalid measured coverage")
    if minimum is not None and 100 * covered / total < minimum:
        raise ValueError("coverage below central minimum")


def node_coverage(project):
    files = json.loads((project / "coverage/coverage-final.json").read_text())
    if not files:
        raise ValueError("missing measured Node coverage")
    totals = {metric: [] for metric in ("branches", "functions", "lines", "statements")}
    for data in files.values():
        statements = data["s"]
        totals["statements"].extend(statements.values())
        totals["functions"].extend(data["f"].values())
        totals["branches"].extend(hit for branch in data["b"].values() for hit in branch)
        lines = {}
        for key, hits in statements.items():
            line = data["statementMap"][key]["start"]["line"]
            lines[line] = max(lines.get(line, 0), hits)
        totals["lines"].extend(lines.values())
    summary = json.loads((project / "coverage/coverage-summary.json").read_text())["total"]
    for metric, hits in totals.items():
        if not hits or any(not isinstance(hit, (int, float)) or hit < 0 for hit in hits):
            raise ValueError(f"missing or invalid measured Node coverage: {metric}")
        covered = sum(hit > 0 for hit in hits)
        if 100 * covered / len(hits) < 70:
            raise ValueError(f"Node coverage below central minimum: {metric}")
        if summary[metric]["covered"] != covered or summary[metric]["total"] != len(hits):
            raise ValueError(f"Node summary differs from measured coverage: {metric}")


def validate_java(project, integration):
    pom = ET.parse(project / "pom.xml").getroot()
    ns = {"m": "http://maven.apache.org/POM/4.0.0"}
    for node in pom.iter():
        name = node.tag.split("}")[-1].lower()
        value = (node.text or "").strip().lower()
        if ("skip" in name and value not in ("", "false")) or (
            name in ("testfailureignore", "maven.test.failure.ignore") and value != "false"
        ):
            raise ValueError(f"test/check disabling setting: {name}")
    required = {"maven-surefire-plugin", "jacoco-maven-plugin", "maven-checkstyle-plugin"}
    if integration:
        required.add("maven-failsafe-plugin")
    present = {p.findtext("m:artifactId", namespaces=ns) for p in pom.findall(".//m:build/m:plugins/m:plugin", ns)}
    if not required <= present:
        raise ValueError("required Maven plugins missing")
    for plugin in pom.findall(".//m:build/m:plugins/m:plugin", ns):
        artifact = plugin.findtext("m:artifactId", namespaces=ns)
        if artifact in ("maven-surefire-plugin", "maven-failsafe-plugin", "jacoco-maven-plugin"):
            if plugin.findall(".//m:excludes", ns):
                raise ValueError("test/coverage exclusions are not permitted in Maven plugins")
        versions = {"maven-surefire-plugin": (3, 2, 2), "maven-failsafe-plugin": (3, 2, 2),
                    "jacoco-maven-plugin": (0, 8, 11), "maven-checkstyle-plugin": (3, 3, 1)}
        if artifact in versions:
            version = plugin.findtext("m:version", default="", namespaces=ns)
            if not re.fullmatch(r"\d+\.\d+\.\d+", version) or tuple(map(int, version.split("."))) < versions[artifact]:
                raise ValueError(f"unapproved or downgraded plugin version: {artifact}")
        if artifact in ("maven-surefire-plugin", "maven-failsafe-plugin"):
            for name in ("includes", "test", "groups", "excludedGroups"):
                if plugin.findall(f".//m:{name}", ns):
                    raise ValueError("Maven test selectors may not narrow the baseline")
    properties = pom.find("m:properties", ns)
    if properties is None or any(
        properties.findtext(f"m:{key}", namespaces=ns) != "17"
        for key in ("java.version", "maven.compiler.source", "maven.compiler.target")
    ):
        raise ValueError("Maven Java 17 compiler baseline required")


def java(project, integration):
    validate_java(project, integration)
    run("mvn", "--batch-mode", "--no-transfer-progress",
        "-DskipTests=false", "-Dmaven.test.skip=false", "-DskipITs=false",
        "-Dcheckstyle.skip=false", "-Dcheckstyle.failOnViolation=true",
        "-Dcheckstyle.failsOnError=true", "-Dcheckstyle.violationSeverity=warning",
        "-Dmaven.test.failure.ignore=false", "clean", "verify", "checkstyle:check", cwd=project)
    if ET.parse(project / "target/checkstyle-result.xml").getroot().findall(".//error"):
        raise ValueError("Checkstyle violations")
    test_reports(project.glob("target/surefire-reports/TEST-*.xml"))
    if integration:
        test_reports(project.glob("target/failsafe-reports/TEST-*.xml"))


def node(project):
    package = json.loads((project / "package.json").read_text())
    scripts = package.get("scripts", {})
    if scripts.get("lint") != "eslint src --ext .ts" or scripts.get("build") != "tsc":
        raise ValueError("Node lint/build scripts differ from approved fixed profile")
    tsconfig = json.loads((project / "tsconfig.json").read_text())
    compiler = tsconfig.get("compilerOptions", {})
    if (compiler.get("strict") is not True or compiler.get("noCheck") is True
            or compiler.get("noEmit") is True or compiler.get("outDir") != "./dist"
            or tsconfig.get("include") != ["src/**/*"]):
        raise ValueError("TypeScript compilation may not be disabled or narrowed")
    clear_outputs(project, ["reports", "coverage", "dist"])
    run("npm", "ci", "--ignore-scripts", cwd=project)
    run("node", "node_modules/eslint/bin/eslint.js", "--no-eslintrc",
        "--config", str(CENTRAL / "policy/eslint.config.cjs"),
        "--resolve-plugins-relative-to", str(project), "--no-ignore",
        "src", "--ext", ".ts", cwd=project)
    run("npm", "run", "build", cwd=project)
    if not list((project / "dist").rglob("*.js")):
        raise ValueError("missing TypeScript build output")
    run("node", "node_modules/jest/bin/jest.js", "--config",
        str(CENTRAL / "policy/jest.config.cjs"), "--ci", "--runInBand", "--coverage",
        cwd=project)
    test_reports([project / "reports/junit.xml"])
    node_coverage(project)


def python(project, minimum):
    clear_outputs(project, ["reports", "coverage.xml", ".coverage", "dist", "build"])
    run(sys.executable, "-m", "pip", "install", "-r", "requirements.txt", cwd=project)
    if (project / "requirements-dev.txt").exists():
        run(sys.executable, "-m", "pip", "install", "-r", "requirements-dev.txt", cwd=project)
    run(sys.executable, "-m", "pip", "install", "build==1.2.2.post1", "wheel==0.45.1", cwd=project)
    run(sys.executable, "-m", "flake8", "app", "tests", "--isolated", "--max-line-length=100",
        "--extend-ignore=E203,W503", cwd=project)
    args = [sys.executable, "-m", "pytest", "-c", str(CENTRAL / "policy/pytest.ini"),
            "--rootdir=.", "tests", "--junitxml=reports/junit.xml",
            "--cov=app", f"--cov-config={CENTRAL / 'policy/coverage.ini'}",
            "--cov-report=xml:coverage.xml", "--cov-report=term"]
    if minimum is not None:
        args.append(f"--cov-fail-under={minimum}")
        args.append("--cov-branch")
    run(*args, cwd=project)
    test_reports([project / "reports/junit.xml"])
    coverage_xml(project / "coverage.xml", "cobertura", minimum)
    run(sys.executable, "-m", "build", cwd=project)
    if not list((project / "dist").glob("*.whl")) or not list((project / "dist").glob("*.tar.gz")):
        raise ValueError("missing Python wheel or sdist")


def dotnet(project):
    test_project = ET.parse(project / "Tests/DotnetApi.Tests.csproj").getroot()
    if test_project.findtext(".//IsTestProject") != "true":
        raise ValueError(".NET test project must remain enabled")
    packages = {p.attrib["Include"] for p in test_project.findall(".//PackageReference")}
    if not {"Microsoft.NET.Test.Sdk", "coverlet.collector", "xunit"} <= packages:
        raise ValueError(".NET test SDK/coverage collector missing")
    for config in project.rglob("*.csproj"):
        root = ET.parse(config).getroot()
        if root.findtext(".//TargetFramework") != "net8.0":
            raise ValueError(".NET 8 target framework required")
        for exclusion in root.findall(".//Compile[@Remove]"):
            if config != project / "DotnetApi.csproj" or exclusion.attrib["Remove"] != "Tests/**":
                raise ValueError("source/test removal is not permitted")
    clear_outputs(project, ["TestResults"])
    sdk = os.environ["CENTRAL_DOTNET_SDK"]
    if not re.fullmatch(r"8\.0\.\d+", sdk):
        raise ValueError("central .NET 8 SDK setup output required")
    global_json = project / "global.json"
    if global_json.is_symlink():
        raise ValueError("global.json cannot be symlinked")
    if global_json.exists():
        configured = json.loads(global_json.read_text()).get("sdk", {}).get("version", "")
        if not re.fullmatch(r"8\.0\.\d+", configured):
            raise ValueError("application cannot downgrade or replace .NET SDK baseline")
    global_json.write_text(json.dumps({"sdk": {"version": sdk, "rollForward": "disable"}}) + "\n")
    solution = project / "DotnetApi.sln"
    run("dotnet", "restore", str(solution), cwd=project)
    run("dotnet", "format", str(solution), "--verify-no-changes", "--no-restore", cwd=project)
    run("dotnet", "build", str(solution), "--no-restore", "--configuration", "Release", cwd=project)
    run("dotnet", "test", str(project / "Tests/DotnetApi.Tests.csproj"),
        "--no-build", "--configuration", "Release", "--logger", "trx",
        "--results-directory", str(project / "TestResults"),
        "--collect:XPlat Code Coverage", cwd=project)
    reports = list(project.glob("TestResults/*.trx"))
    if not reports:
        raise ValueError("missing TRX")
    for path in reports:
        counters = ET.parse(path).getroot().find(".//{*}Counters")
        if counters is None or int(counters.attrib["executed"]) <= 0:
            raise ValueError("no executed .NET tests")
        if int(counters.attrib.get("failed", 0)) or int(counters.attrib["passed"]) != int(counters.attrib["executed"]):
            raise ValueError("unsuccessful .NET tests")
    coverage = list(project.glob("TestResults/*/coverage.cobertura.xml"))
    if not coverage:
        raise ValueError("missing .NET coverage")
    for path in coverage:
        coverage_xml(path, "cobertura", None)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--id", required=True)
    args = parser.parse_args()
    policy = json.loads((Path(__file__).resolve().parents[1] / "policy/repositories.json").read_text())
    profile = next(p for p in policy[args.repository] if p["id"] == args.id)
    project = (args.root / profile["path"]).resolve()
    if args.id == "java":
        java(project, profile["integration"])
        report = "jacoco-aggregate" if profile["integration"] else "jacoco"
        coverage_xml(project / f"target/site/{report}/jacoco.xml", "jacoco", profile["coverage"])
    elif args.id == "node":
        node(project)
    elif args.id == "python":
        python(project, profile["coverage"])
    elif args.id == "dotnet":
        dotnet(project)
    else:
        raise ValueError("unknown profile")


if __name__ == "__main__":
    main()
