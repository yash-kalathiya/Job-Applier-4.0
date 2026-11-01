#!/usr/bin/env python3
"""Read-only validation of the OpenCode coding-agent team and external skill presence."""
from pathlib import Path
import argparse
import sys

AGENTS = ("orchestrator", "coder", "security-reviewer", "quality-reviewer", "bug-reviewer", "review-lead", "publisher")
SKILLS = ("compact-coding", "enterprise-review")
EXTERNAL = ("karpathy-guidelines", "security-audit")


def locate(name: str, root: Path) -> Path | None:
    home = Path.home()
    for base in (root / ".opencode/skills", root / ".agents/skills", root / ".claude/skills", home / ".config/opencode/skills", home / ".agents/skills", home / ".claude/skills"):
        path = base / name / "SKILL.md"
        if path.is_file():
            return path
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external", action="store_true", help="Require the upstream GitHub skills too")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    errors = 0
    if not (root / ".git").exists():
        print(f"FAIL not a git repository: {root}")
        errors += 1
    print(f"Repository: {root}")
    for name in AGENTS:
        f = root / ".opencode" / "agents" / f"{name}.md"
        exists = f.is_file()
        print(f"{'PASS' if exists else 'FAIL'} agent {name}")
        errors += not exists
    for name in SKILLS:
        f = locate(name, root)
        print(f"{'PASS' if f else 'FAIL'} local skill {name}: {f or 'missing'}")
        errors += f is None
    for name in EXTERNAL:
        f = locate(name, root)
        state = 'PASS' if f else 'FAIL' if args.external else 'NOT_INSTALLED'
        print(f"{state} external skill {name}: {f or 'missing; run setup_external_skills.sh'}")
        errors += f is None and args.external
    return 1 if errors else 0

if __name__ == "__main__":
    sys.exit(main())
