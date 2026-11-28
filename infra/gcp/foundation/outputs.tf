# What a deploy workflow and infra/gcp/node need from the landing zone.
# None of these is a secret; the two a workflow uses are set as repo variables.

output "workload_identity_provider" {
  description = "The provider a deploy job signs in through: the `workload_identity_provider` input of google-github-actions/auth."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "deployers" {
  description = "Each hosted service's deploy identity: the `service_account` input of google-github-actions/auth."
  value       = { for name, sa in google_service_account.deployer : name => sa.email }
}

output "registry" {
  description = "Where a fleet image is pulled from inside the project: <registry>/<owner>/<image>@<digest> for ghcr.io/<owner>/<image>."
  value       = "${local.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.ghcr.repository_id}"
}

output "region" {
  description = "The region the platform runs in (_data/hosting.yml)."
  value       = local.region
}
