#!/usr/bin/env bash
# Builds the public site into ./site
set -euo pipefail
cd "$(dirname "$0")/.."
keep="$(mktemp -d)"; [ -d site/.vercel ] && cp -R site/.vercel "$keep/"
(cd ui && npm run build >/dev/null && npx vite build -c vite.site.config.js >/dev/null)
[ -d "$keep/.vercel" ] && cp -R "$keep/.vercel" site/; rm -rf "$keep"
mv site/site.html site/index.html
cp scripts/install-remote.sh site/install.sh
cp scripts/install-remote.ps1 site/install.ps1
tar -czf site/job-applier.tar.gz --exclude './ui/node_modules' --exclude './site' --exclude '*/__pycache__' \
  --exclude '*.pyc' --exclude '.DS_Store' --exclude './.vercel' --exclude './.claude' --exclude './.git' .
cat > site/vercel.json <<'JSON'
{
  "cleanUrls": true,
  "rewrites": [{ "source": "/install", "destination": "/install.sh" }],
  "headers": [
    { "source": "/install(.sh|.ps1)?", "headers": [{ "key": "Content-Type", "value": "text/plain; charset=utf-8" }, { "key": "Cache-Control", "value": "no-cache" }] },
    { "source": "/job-applier.tar.gz", "headers": [{ "key": "Cache-Control", "value": "no-cache" }] }
  ]
}
JSON
echo "site/ ready: $(du -sh site 2>/dev/null | cut -f1)"
