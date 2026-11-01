#!/usr/bin/env bash
# Job Applier 4.0 installer
set -euo pipefail

REPO="yash-kalathiya/Job-Applier-4.0"
DIR="${JOB_APPLIER_DIR:-$HOME/.job-applier-app}"
b() { printf '\033[1m%s\033[0m\n' "$*"; }
ok() { printf '\033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!\033[0m %s\n' "$*"; }
die() { printf '\033[31m✗\033[0m %s\n' "$*"; exit 1; }

b "Installing Job Applier 4.0"
command -v python3 >/dev/null || die "Job Applier 4.0 needs Python 3.9+. Get it at https://www.python.org/downloads/ and run this again."
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || die "Job Applier 4.0 needs Python 3.9 or newer (you have $(python3 -V))."
ok "$(python3 -V)"
command -v npx >/dev/null && ok "Node.js $(node -v 2>/dev/null)" || warn "Node.js not found. Your agent needs it to drive a browser: https://nodejs.org"

mkdir -p "$DIR"
cp -r . "$DIR" 2>/dev/null || true
chmod +x "$DIR/bin/job-applier"

mkdir -p "$HOME/.local/bin" && ln -sf "$DIR/bin/job-applier" "$HOME/.local/bin/job-applier"
echo; b "Checking your setup"
python3 "$DIR/bin/job-applier" doctor || true
echo
printf '\033[33m★\033[0m Free for every student. If it helps you, star it: https://github.com/yash-kalathiya/Job-Applier-4.0\n\n'
