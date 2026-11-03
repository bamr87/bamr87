# OpenTofu, not Terraform: the MPL-2.0 fork under the Linux Foundation
# (ADR 0003). The HCL is Terraform-compatible; nothing here needs an
# OpenTofu-only feature yet, so the choice stays reversible.
#
# Floors only, no ceilings (docs/DEPENDENCIES.md): `dash infra plan` runs
# `init -upgrade`, and the provider lock file is never committed.
terraform {
  required_version = ">= 1.8.0"

  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = ">= 3.0.0"
    }
  }

  # The path comes at init (`-backend-config=path=...`) from _data/fleet.yml
  # `nodes.infra.state_dir`: outside every checkout, so worktrees share one state.
  backend "local" {}
}
