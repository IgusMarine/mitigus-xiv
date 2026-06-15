#!/bin/sh
# ---------------------------------------------------------------------------
# Vendors the FFXIV opcode definitions to a local file.
#
# The mitigator reads this file with -j, so once it exists the mitigator NEVER
# calls GitHub while you play. Re-run this after each game patch to refresh.
#
#   sudo sh scripts/update-opcodes.sh
#
# Knobs (environment variables):
#   REGION   which definition to pull        (default: Global)
#   SOURCE   GitHub API "contents" URL of the OpcodeDefinition folder
#            Point this at a CURRENT fork if the default repo goes stale.
#   PYTHON_BIN  python interpreter            (default: python3)
# ---------------------------------------------------------------------------
set -e

HERE="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$HERE/vendor/opcodes.json}"
REGION="${REGION:-Global}"
SOURCE="${SOURCE:-https://api.github.com/repos/Soreepeong/XivAlexander/contents/StaticData/OpcodeDefinition}"
PY="${PYTHON_BIN:-python3}"

echo "Source : $SOURCE"
echo "Region : $REGION"
echo "Output : $OUT"
mkdir -p "$(dirname "$OUT")"

"$PY" - "$SOURCE" "$REGION" "$OUT" <<'PYEOF'
import json, os, sys, tempfile, urllib.request

src, region, out = sys.argv[1], sys.argv[2], sys.argv[3]

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "weave-box"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()

try:
    listing = json.loads(fetch(src))
except Exception as exc:
    sys.exit(f"Could not read the opcode folder: {exc}")

if isinstance(listing, dict) and listing.get("message"):
    sys.exit(f"GitHub said: {listing['message']}")

files = [f for f in listing if str(f.get("name", "")).lower().endswith(".json")]
names = [f["name"] for f in files]
pick = next((f for f in files if region.lower() in f["name"].lower()), None)
if pick is None:
    print(f"No definition matched region={region!r}.")
    print("Available:", ", ".join(names) or "(none)")
    sys.exit(2)

data = fetch(pick["download_url"])
json.loads(data)  # validate before writing

fd, tmp = tempfile.mkstemp(dir=os.path.dirname(out) or ".")
with os.fdopen(fd, "wb") as fp:
    fp.write(data)
os.replace(tmp, out)
print(f"Saved {out}  (from {pick['name']})")
PYEOF

echo "Opcodes updated. Restart the mitigator from the panel to load them."
