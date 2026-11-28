#!/usr/bin/env bash
# ============================================================================
# infra/gcp/dev/up.sh — bring zer0-CMS's development stack up on the
# development instance (_data/hosting.yml `dev:`), and say how to open it.
# Run by the maintainer after `infra/gcp/deploy.sh dev --apply` created the
# machine. It reaches the machine only through the identity-aware tunnel, as
# you; nothing is opened to the internet.
#
#   gcloud auth login                    # once, as yourself
#   export GCP_PROJECT_ID=<the project>
#   infra/gcp/dev/up.sh                  # install, build, start, wait for /readyz
#   infra/gcp/dev/up.sh --tunnel         # forward the app to http://127.0.0.1:8000
#   infra/gcp/dev/up.sh --account        # make the first account (asks on the machine)
#   infra/gcp/dev/up.sh --codes          # show the sign-in codes the app logged
#
# The first `gcloud compute ssh` makes an SSH key on this Mac
# (~/.ssh/google_compute_engine) and registers its public half with your
# Google account's OS Login. That is how the tunnel signs you in.
# ============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"

command -v gcloud >/dev/null 2>&1 || { echo "up: the gcloud CLI is required" >&2; exit 1; }
[[ -n "${GCP_PROJECT_ID:-}" ]] || { echo "up: set GCP_PROJECT_ID to the Google Cloud project (it is never written in the repo)" >&2; exit 1; }

# The machine's name and zone are not secrets and are derived from the one file.
read -r NAME ZONE < <(python3 - "$ROOT/_data/hosting.yml" <<'PY'
import sys, yaml
doc = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
print(f"{doc['project']}-{doc['dev']['name']}", doc["zone"])
PY
)

ssh_to() { gcloud compute ssh "$NAME" --project "$GCP_PROJECT_ID" --zone "$ZONE" --tunnel-through-iap "$@"; }

case "${1:-}" in
  "")
    ssh_to --command 'bash -s' < "$HERE/zer0-cms.sh"
    echo
    echo "up: to open it, run:  $0 --tunnel   then visit http://127.0.0.1:8000/studio/"
    echo "up: to make the first account:  $0 --account"
    ;;
  --tunnel)
    echo "up: forwarding http://127.0.0.1:8000 to the development instance; Ctrl-C closes it"
    ssh_to -- -N -L 8000:127.0.0.1:8000
    ;;
  --account)
    ssh_to -- -t 'cd ~/dev/zer0-cms && sudo docker compose exec content python manage.py createsuperuser'
    ;;
  --codes)
    ssh_to --command 'cd ~/dev/zer0-cms && sudo docker compose logs --since 30m content 2>&1 | tail -n 80'
    ;;
  *)
    echo "usage: $0 [--tunnel|--account|--codes]" >&2
    exit 2
    ;;
esac
