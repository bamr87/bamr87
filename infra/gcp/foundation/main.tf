# The landing zone: what the platform's node stands on, created once.
#
#   the APIs the platform uses
#   one keyless sign-in for GitHub Actions (Workload Identity Federation) and a
#     deploy identity per hosted service that names one, trusted only from that
#     service's repo and GitHub environment
#   a pull-through of ghcr.io, so the node pulls the fleet's own images from
#     inside the project
#   an optional budget alert
#
# It creates nothing that serves traffic and nothing billed while idle.
# The machine itself is infra/gcp/node.

locals {
  hosting = yamldecode(file("${path.module}/../../../_data/hosting.yml"))
  region  = local.hosting.region

  # A deploy identity for every service that names where it is deployed from,
  # whether or not the service is switched on yet: the identity is free, and a
  # repo can prove its sign-in before its service exists.
  deployers = {
    for name, svc in local.hosting.services : name => svc.deploy
    if try(svc.deploy.repository, "") != "" && try(svc.deploy.environment, "") != ""
  }

  # Google Cloud labels hold lowercase letters, digits, hyphens and underscores
  # only, so `source` (ADR 0018: `<owner>/<repo> <path>`) is written with an
  # underscore for each slash and two hyphens for the space.
  labels = {
    project    = local.hosting.project
    env        = var.env
    managed-by = "opentofu"
    source     = "bamr87_bamr87--infra_gcp_foundation"
  }

  # Only what the landing zone and the node use. A managed service a later phase
  # adopts (ADR 0020, G7) enables its own API in the change that adds it.
  apis = [
    "artifactregistry.googleapis.com",
    "billingbudgets.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "iap.googleapis.com",
    "oslogin.googleapis.com",
    "storage.googleapis.com",
    "sts.googleapis.com",
  ]

  # Only these repo and environment pairs may exchange a GitHub token at all.
  # With no deployer declared the condition names a repo that cannot exist.
  trusted = [
    for d in local.deployers :
    "(assertion.repository == '${d.repository}' && assertion.environment == '${d.environment}')"
  ]
  trust_condition = length(local.trusted) > 0 ? join(" || ", local.trusted) : "assertion.repository == 'none/none'"
}

data "google_project" "this" {}

resource "google_project_service" "enabled" {
  for_each = toset(local.apis)

  service            = each.value
  disable_on_destroy = false
}

# ---------------------------------------------------------------------------
# Sign-in: GitHub's own token, exchanged for a short-lived one. No key exists.
# ---------------------------------------------------------------------------
resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github"
  display_name              = "GitHub Actions"
  description               = "Short-lived sign-in for the fleet's deploy jobs; no key is stored (ADR 0018, ADR 0020)."

  depends_on = [google_project_service.enabled]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-oidc"
  display_name                       = "GitHub OIDC"

  # `repository` and `environment` are claims GitHub always writes the same
  # way; the subject's format can differ per repo, so nothing binds to it.
  attribute_mapping = {
    "google.subject"             = "assertion.sub"
    "attribute.repository"       = "assertion.repository"
    "attribute.repository_owner" = "assertion.repository_owner"
    "attribute.environment"      = "assertion.environment"
  }
  attribute_condition = local.trust_condition

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "deployer" {
  for_each = local.deployers

  account_id   = "deploy-${each.key}"
  display_name = "Deploys ${each.key} from ${each.value.repository}"
  description  = "Signed in to only by ${each.value.repository}'s jobs in the ${each.value.environment} environment. It holds no role until the change that needs one grants it."

  depends_on = [google_project_service.enabled]
}

resource "google_service_account_iam_member" "federated" {
  for_each = local.deployers

  service_account_id = google_service_account.deployer[each.key].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${each.value.repository}"
}

# ---------------------------------------------------------------------------
# Images: GHCR stays the registry of record (ADR 0003). This repository pulls
# through and caches, so a pull on the node does not depend on GHCR answering
# and a managed service can run the same image later.
# ---------------------------------------------------------------------------
resource "google_artifact_registry_repository" "ghcr" {
  location      = local.region
  repository_id = "ghcr"
  description   = "Pull-through of ghcr.io, the fleet's registry of record."
  format        = "DOCKER"
  mode          = "REMOTE_REPOSITORY"
  labels        = local.labels

  remote_repository_config {
    description = "ghcr.io"

    docker_repository {
      custom_repository {
        uri = "https://ghcr.io"
      }
    }
  }

  depends_on = [google_project_service.enabled]
}

# ---------------------------------------------------------------------------
# A budget ALERT, when a billing account is given. It warns; it does not cap.
# ---------------------------------------------------------------------------
resource "google_billing_budget" "platform" {
  count = var.billing_account == "" ? 0 : 1

  billing_account = var.billing_account
  display_name    = "${local.hosting.project} platform"

  budget_filter {
    projects = ["projects/${data.google_project.this.number}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(var.budget_usd)
    }
  }

  threshold_rules {
    threshold_percent = 0.5
  }

  threshold_rules {
    threshold_percent = 0.9
  }

  threshold_rules {
    threshold_percent = 1.0
  }

  depends_on = [google_project_service.enabled]
}
