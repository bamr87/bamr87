# A fleet node's durable infrastructure: the shared network and the volumes
# its placed services keep their data in. Compose owns the containers and
# takes these as `external` (the overlay `dash node gen` writes), so
# `docker compose down -v` can never delete what this state holds.

provider "docker" {
  host     = var.docker_host
  ssh_opts = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
}

locals {
  labels = {
    "com.bamr87.fleet.node"       = var.node
    "com.bamr87.fleet.managed-by" = "opentofu"
  }
}

resource "docker_network" "fleet" {
  name   = var.network
  driver = "bridge"

  dynamic "labels" {
    for_each = local.labels
    content {
      label = labels.key
      value = labels.value
    }
  }
}

# prevent_destroy turns any plan that would delete one of these into an error
# (a lifecycle argument must be a literal, hence two resources, not a flag).
resource "docker_volume" "durable" {
  for_each = toset(var.durable_volumes)
  name     = each.value

  dynamic "labels" {
    for_each = merge(local.labels, { "com.bamr87.fleet.data" = "durable" })
    content {
      label = labels.key
      value = labels.value
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "docker_volume" "rebuildable" {
  for_each = toset(var.rebuildable_volumes)
  name     = each.value

  dynamic "labels" {
    for_each = merge(local.labels, { "com.bamr87.fleet.data" = "rebuildable" })
    content {
      label = labels.key
      value = labels.value
    }
  }
}
