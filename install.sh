#!/usr/bin/env bash
# One-step setup: checks Python and Chrome, registers Job Applier 4.0 with Claude Code and Codex, opens the app.
set -e
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Job Applier 4.0 needs Python 3.9+ (https://www.python.org/downloads/)"; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || { echo "Job Applier 4.0 needs Python 3.9 or newer"; exit 1; }
chmod +x bin/job-applier
python3 -m pip install --quiet --user pypdf 2>/dev/null || true   # optional: lets the ATS check read PDFs
python3 bin/job-applier install-agents
echo
echo "Opening Job Applier 4.0 at http://localhost:4747 (Ctrl+C to stop)"
exec python3 bin/job-applier app
