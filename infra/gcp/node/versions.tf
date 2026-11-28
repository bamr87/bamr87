# OpenTofu, as for the fleet's other nodes (ADR 0003, ADR 0018).
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

# The project is never written in the repo (ADR 0018, decision 8).
provider "google" {
  project = var.project_id
  region  = local.hosting.region
  zone    = local.hosting.zone
}
