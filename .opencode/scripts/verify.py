#!/usr/bin/env python3
"""Non-destructive OpenCode team quality checks; never installs dependencies.

Run from the repository root: python3 .opencode/scripts/verify.py --static
This checks git whitespace and Ruff (when present). It does not run project code.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def check(name: str, args: list[str], root: Path, timeout: int = 90) -> dict[str, str]:
    try:
        process = subprocess.run(
            args, cwd=root, capture_output=True, text=True, timeout=timeout,
            check=False, stdin=subprocess.DEVNULL,
        )
        output = (process.stdout + "\n" + process.stderr).strip()
        return {
            "check": name,
            "result": "PASS" if process.returncode == 0 else "FAIL",
            "exit_code": str(process.returncode),
            "command": " ".join(args),
            "evidence": output[:1100],
        }
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {
            "check": name,
            "result": "FAIL",
            "exit_code": "ERROR",
            "command": " ".join(args),
            "evidence": str(exc)[:400],
        }


def skip(name: str, reason: str, state: str = "NOT_AVAILABLE") -> dict[str, str]:
    return {"check": name, "result": state, "evidence": reason}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static", action="store_true", help="Static checks only (default)")
    parser.add_argument("--tests", action="store_true", help="Run pytest; needs explicit opt-in")
    parser.add_argument(
        "--i-approve-running-project-code", action="store_true",
        help="Required with --tests; execute ONLY in an approved, isolated environment",
    )
    args = parser.parse_args()
    if args.tests and not args.i_approve_running_project_code:
        parser.error("--tests requires --i-approve-running-project-code and a safe isolated test environment")

    root = Path(__file__).resolve().parents[2]
    results: list[dict[str, str]] = []
    if shutil.which("git"):
        results.append(check("git diff --check", ["git", "diff", "--check"], root))
        results.append(check("git diff --cached --check", ["git", "diff", "--cached", "--check"], root))
    else:
        results.append(skip("Git whitespace", "git is not installed"))

    # Avoid scanning private environments or huge dependency trees merely to detect a Python project.
    python_project = (root / "pyproject.toml").exists() or any(root.glob("*.py")) or (root / "api.py").exists()
    if python_project:
        ruff = shutil.which("ruff")
        if ruff:
            results.append(check("Ruff lint", [ruff, "check", "."], root))
            results.append(check("Ruff format", [ruff, "format", "--check", "."], root))
        else:
            results.append(skip("Ruff lint/format", "Ruff absent. Install/configure separately with user approval, or use existing project-approved lint commands."))
        mypy_config = (root / "mypy.ini").exists() or (root / ".mypy.ini").exists()
        try:
            if (root / "pyproject.toml").exists():
                mypy_config = mypy_config or "[tool.mypy]" in (root / "pyproject.toml").read_text(encoding="utf-8")
        except OSError:
            pass
        if mypy_config:
            if shutil.which("mypy"):
                results.append(check("mypy", ["mypy", "."], root, 120))
            else:
                results.append(skip("mypy", "Project requests mypy but it is not installed"))
        else:
            results.append(skip("Type checking", "No known mypy configuration; inspect project type-check tooling", "NOT_RUN"))
    else:
        results.append(skip("Python checks", "No top-level Python project detected", "NOT_RUN"))

    frontend = root / "ui" / "package.json"
    if not frontend.exists():
        frontend = root / "package.json"
    if frontend.exists():
        try:
            package = json.loads(frontend.read_text(encoding="utf-8"))
            scripts = package.get("scripts", {})
            for key in ("lint", "typecheck", "test"):
                if key in scripts:
                    results.append(skip("npm " + key, "Configured in " + str(frontend.relative_to(root)) + "; run in approved isolated environment: npm run " + key, "NOT_RUN"))
        except (OSError, json.JSONDecodeError):
            results.append(skip("frontend checks", "package.json could not be parsed", "NOT_RUN"))

    if args.tests:
        if shutil.which("pytest"):
            results.append(check("pytest", ["pytest", "-q"], root, 180))
        else:
            results.append(skip("pytest", "pytest missing"))
    else:
        results.append(skip("tests", "Not executed: project tests can have side effects; use an explicitly approved isolated environment", "NOT_RUN"))

    if any(x["result"] == "FAIL" for x in results):
        overall = "FAIL"
    elif python_project and not shutil.which("ruff"):
        overall = "INCOMPLETE"
    else:
        overall = "STATIC_CHECKS_PASSED_ONLY"
    print(json.dumps({"overall": overall, "repository": str(root), "checks": results}, indent=2))
    return 1 if overall == "FAIL" else (2 if overall == "INCOMPLETE" else 0)


if __name__ == "__main__":
    sys.exit(main())
