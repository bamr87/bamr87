# What the maintainer needs after an apply. Each is empty while the node is off.

output "name" {
  description = "The machine's name: `gcloud compute ssh <name> --tunnel-through-iap` reaches it."
  value       = try(google_compute_instance.node[0].name, "")
}

output "address" {
  description = "The fixed address the DNS record of each hosted service points at."
  value       = try(google_compute_address.node[0].address, "")
}

output "backups" {
  description = "The bucket backups taken off the machine are written to."
  value       = try(google_storage_bucket.backups[0].name, "")
}

output "open_to_the_internet" {
  description = "Whether ports 80 and 443 are open (the machine's `public` in _data/hosting.yml)."
  value       = local.public
}

output "zone" {
  description = "The zone the machine is in: `gcloud compute ssh <name> --zone <zone> --tunnel-through-iap`."
  value       = local.hosting.zone
}
