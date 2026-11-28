# OpenTofu, as for the fleet's nodes (ADR 0003); Google Cloud is declared in
# OpenTofu and not in a second tool (ADR 0018, decision 5).
#
# Floors only, no ceilings (docs/DEPENDENCIES.md): `infra/gcp/deploy.sh` runs
# `init -upgrade`, and the provider lock file is never committed.
terraform {
  required_version = ">= 1.8.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0.0"
    }
  }

  # The path comes at init (`-backend-config=path=...`) from infra/gcp/deploy.sh:
  # outside every checkout, so worktrees share one state.
  backend "local" {}
}

# The project is never written in the repo: `_data/` is public site data
# (ADR 0018, decision 8). deploy.sh passes it from GCP_PROJECT_ID.
provider "google" {
  project = var.project_id
  region  = local.region
}
