# The platform's machine: one virtual machine that is a fleet node (ADR 0003).
# bashOS installs onto it, the same compose stacks run on it, and it is reached
# over SSH like any node. What this module owns is what outlives a container:
#
#   a private network, and the only two ways in:
#     SSH, from the provider's identity-aware tunnel and nowhere else
#     ports 80 and 443 from the internet, only while node.public is true
#   the machine and its address
#   a data disk that survives the machine, snapshotted daily
#   a bucket for backups taken off the machine
#
# While the machine's `enabled` in _data/hosting.yml is false this module plans
# NOTHING. The same module describes the development instance (`dev:`), which
# is never public and has nothing durable, so one apply removes it.

locals {
  hosting = yamldecode(file("${path.module}/../../../_data/hosting.yml"))
  node    = local.hosting[var.instance]
  env     = var.instance == "dev" ? "dev" : "prod"

  create = local.node.enabled
  public = local.node.enabled && local.node.public
  # What must outlive the machine: a data disk, its snapshots, a backups bucket
  # and deletion protection. The development instance has none of it.
  durable = local.node.enabled && try(local.node.durable, true)
  name    = "${local.hosting.project}-${local.node.name}"
  tag     = local.name

  # Google Cloud labels hold lowercase letters, digits, hyphens and underscores
  # only, so `source` (ADR 0018: `<owner>/<repo> <path>`) is written with an
  # underscore for each slash and two hyphens for the space.
  labels = {
    project    = local.hosting.project
    env        = local.env
    managed-by = "opentofu"
    source     = "bamr87_bamr87--infra_gcp_node"
  }

  # The provider's identity-aware tunnel connects from this range.
  tunnel_range = "35.235.240.0/20"
}

# ---------------------------------------------------------------------------
# Network: its own, with nothing open that is not listed here.
# ---------------------------------------------------------------------------
resource "google_compute_network" "platform" {
  count = local.create ? 1 : 0

  name                    = local.name
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "platform" {
  count = local.create ? 1 : 0

  name          = local.name
  region        = local.hosting.region
  network       = google_compute_network.platform[0].id
  ip_cidr_range = "10.10.0.0/24"
}

resource "google_compute_firewall" "ssh_from_tunnel" {
  count = local.create ? 1 : 0

  name          = "${local.name}-ssh-from-tunnel"
  description   = "SSH is the only API to a node (ADR 0003), and only through the identity-aware tunnel: nobody reaches port 22 from the internet."
  network       = google_compute_network.platform[0].id
  direction     = "INGRESS"
  source_ranges = [local.tunnel_range]
  target_tags   = [local.tag]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

resource "google_compute_firewall" "web" {
  count = local.public ? 1 : 0

  name          = "${local.name}-web"
  description   = "The front door: HTTP and HTTPS from the internet. Exists only while the machine's `public` in _data/hosting.yml is true."
  network       = google_compute_network.platform[0].id
  direction     = "INGRESS"
  source_ranges = ["0.0.0.0/0"]
  target_tags   = [local.tag]

  allow {
    protocol = "tcp"
    ports    = ["80", "443"]
  }
}

# One fixed address: what the DNS records point at, and how the machine reaches
# the internet for packages and images. Nothing reaches it without a rule above.
resource "google_compute_address" "node" {
  count = local.create ? 1 : 0

  name   = local.name
  region = local.hosting.region
  labels = local.labels
}

# ---------------------------------------------------------------------------
# The machine's own identity: it may write logs and metrics, pull images from
# the project's registry and write backups. Nothing else.
# ---------------------------------------------------------------------------
resource "google_service_account" "node" {
  count = local.create ? 1 : 0

  account_id   = "node-${local.node.name}"
  display_name = "The platform node ${local.node.name}"
}

resource "google_project_iam_member" "node" {
  for_each = local.create ? toset([
    "roles/artifactregistry.reader",
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
  ]) : toset([])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.node[0].email}"
}

# ---------------------------------------------------------------------------
# Data: a disk that outlives the machine, a daily snapshot, and a bucket for
# backups that leave the machine. A plan that would delete either one fails.
# ---------------------------------------------------------------------------
resource "google_compute_disk" "data" {
  count = local.durable ? 1 : 0

  name   = "${local.name}-data"
  type   = "pd-balanced"
  zone   = local.hosting.zone
  size   = local.node.data_disk_gb
  labels = local.labels

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_compute_resource_policy" "snapshots" {
  count = local.durable ? 1 : 0

  name   = "${local.name}-daily"
  region = local.hosting.region

  snapshot_schedule_policy {
    schedule {
      daily_schedule {
        days_in_cycle = 1
        start_time    = local.node.snapshots.daily_at
      }
    }

    retention_policy {
      max_retention_days    = local.node.snapshots.keep_days
      on_source_disk_delete = "KEEP_AUTO_SNAPSHOTS"
    }

    snapshot_properties {
      labels = local.labels
    }
  }
}

resource "google_compute_disk_resource_policy_attachment" "data" {
  count = local.durable ? 1 : 0

  name = google_compute_resource_policy.snapshots[0].name
  disk = google_compute_disk.data[0].name
  zone = local.hosting.zone
}

resource "google_storage_bucket" "backups" {
  count = local.durable ? 1 : 0

  name                        = "${var.project_id}-platform-backups"
  location                    = local.hosting.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = local.labels

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = 90
    }

    action {
      type = "Delete"
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}

# The node may add a backup and read one back for a restore. It may not delete
# one: a machine that is taken over cannot erase what was saved off it.
resource "google_storage_bucket_iam_member" "node_backups" {
  for_each = local.durable ? toset(["roles/storage.objectCreator", "roles/storage.objectViewer"]) : toset([])

  bucket = google_storage_bucket.backups[0].name
  role   = each.value
  member = "serviceAccount:${google_service_account.node[0].email}"
}

# ---------------------------------------------------------------------------
# The machine.
# ---------------------------------------------------------------------------
resource "google_compute_instance" "node" {
  count = local.create ? 1 : 0

  name                      = local.name
  machine_type              = local.node.machine_type
  zone                      = local.hosting.zone
  tags                      = [local.tag]
  labels                    = local.labels
  deletion_protection       = local.durable
  allow_stopping_for_update = true

  boot_disk {
    initialize_params {
      image = "debian-cloud/${local.node.os}"
      size  = local.node.boot_disk_gb
      type  = "pd-balanced"
    }
  }

  dynamic "attached_disk" {
    for_each = local.durable ? [1] : []

    content {
      source      = google_compute_disk.data[0].id
      device_name = "data"
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.platform[0].id

    access_config {
      nat_ip = google_compute_address.node[0].address
    }
  }

  # Sign-in to the machine is by the operator's own cloud identity, through the
  # tunnel. No SSH key is stored in the project or on the machine by this module.
  metadata = {
    enable-oslogin         = "TRUE"
    block-project-ssh-keys = "TRUE"
  }

  service_account {
    email  = google_service_account.node[0].email
    scopes = ["cloud-platform"]
  }

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }
}
