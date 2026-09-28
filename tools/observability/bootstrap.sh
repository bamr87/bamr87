#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# bootstrap.sh — install what the contract renders into a running stack.
#
# Idempotent by construction: ILM policies and index templates are PUTs (last
# write wins) and the Kibana import runs with overwrite=true, so running this
# on every `dash observe up` is free. Grafana needs nothing — it reads its
# provisioning directory at start.
#
# It waits rather than assuming: Elasticsearch takes tens of seconds to go
# yellow and Kibana minutes to go available, and a bootstrap that fires early
# reports success having installed nothing.
#
# Everything it installs is generated — re-render with
# `tools/dash observe verify --write` after editing _data/fleet.yml.
# ---------------------------------------------------------------------------
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ES="${ES_URL:-http://127.0.0.1:${ES_PORT:-9200}}"
KIBANA="${KIBANA_URL:-http://127.0.0.1:${KIBANA_PORT:-5601}}"
GRAFANA="${GRAFANA_URL:-http://127.0.0.1:${GRAFANA_PORT:-3001}}"

c_ok=$'\033[32m'; c_warn=$'\033[33m'; c_err=$'\033[31m'; c_off=$'\033[0m'
ok()   { echo "  ${c_ok}✓${c_off} $*"; }
warn() { echo "  ${c_warn}!${c_off} $*"; }
die()  { echo "  ${c_err}✗${c_off} $*" >&2; exit 1; }

wait_for() {
  local name="$1" url="$2" tries="${3:-60}" i=0
  while (( i < tries )); do
    if curl -fsS --max-time 5 "$url" >/dev/null 2>&1; then ok "${name} is up"; return 0; fi
    i=$((i + 1)); sleep 5
  done
  return 1
}

# --- Elasticsearch ---------------------------------------------------------
wait_for "elasticsearch" "${ES}/_cluster/health?wait_for_status=yellow&timeout=5s" 60 \
  || die "elasticsearch never came up at ${ES} — is the elk profile running? (docker compose --profile elk up -d)"

policies="${HERE}/elasticsearch/ilm-policies.json"
templates="${HERE}/elasticsearch/index-templates.json"
[[ -f "$policies"  ]] || die "missing ${policies} — run: tools/dash observe verify --write"
[[ -f "$templates" ]] || die "missing ${templates} — run: tools/dash observe verify --write"

# jq is not a hub dependency; python3 is (tools/setup.sh), and it is already
# the language the policies were rendered in.
names() { python3 -c 'import json,sys;print("\n".join(json.load(open(sys.argv[1]))))' "$1"; }
body()  { python3 -c 'import json,sys;print(json.dumps(json.load(open(sys.argv[1]))[sys.argv[2]]))' "$1" "$2"; }

while IFS= read -r name; do
  [[ -n "$name" ]] || continue
  if body "$policies" "$name" \
     | curl -fsS -X PUT "${ES}/_ilm/policy/${name}" -H 'Content-Type: application/json' -d @- >/dev/null
  then ok "ILM policy ${name}"; else warn "ILM policy ${name} failed"; fi
done < <(names "$policies")

while IFS= read -r name; do
  [[ -n "$name" ]] || continue
  if body "$templates" "$name" \
     | curl -fsS -X PUT "${ES}/_index_template/${name}" -H 'Content-Type: application/json' -d @- >/dev/null
  then ok "index template ${name}"; else warn "index template ${name} failed"; fi
done < <(names "$templates")

# --- Kibana ----------------------------------------------------------------
# Long patience on purpose: Kibana's first start migrates its own saved-object
# indices and can take several minutes on a cold volume.
if wait_for "kibana" "${KIBANA}/api/status" 60; then
  ndjson="${HERE}/kibana/dashboards.ndjson"
  if [[ -f "$ndjson" ]]; then
    if curl -fsS -X POST "${KIBANA}/api/saved_objects/_import?overwrite=true" \
         -H 'kbn-xsrf: true' -F "file=@${ndjson}" >/dev/null
    then
      ok "kibana saved objects imported"
    else
      warn "kibana import failed — try by hand:"
      warn "  curl -X POST '${KIBANA}/api/saved_objects/_import?overwrite=true' -H 'kbn-xsrf: true' -F file=@${ndjson}"
    fi
  else
    warn "no ${ndjson} — run: tools/dash observe verify --write"
  fi
else
  warn "kibana not reachable at ${KIBANA}; dashboards not imported (re-run this script later)"
fi

# --- Grafana ---------------------------------------------------------------
# Nothing to install: the datasource and the dashboard provider are mounted
# provisioning files. This only reports whether it took them.
if wait_for "grafana" "${GRAFANA}/api/health" 24; then
  ok "grafana provisioned (datasource + Fleet folder read from the mount)"
else
  warn "grafana not reachable at ${GRAFANA}"
fi

echo
echo "  Kibana   ${KIBANA}"
echo "  Grafana  ${GRAFANA}"
echo "  Portal   http://127.0.0.1:${CONSOLE_PORT:-4001}/#observe  (docker compose up -d console)"
echo
echo "  Next:    tools/dash lake sync --days 7 && tools/dash observe ship --days 7"
