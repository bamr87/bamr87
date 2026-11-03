output "network" {
  description = "The network compose projects on this node join as external."
  value       = docker_network.fleet.name
}

output "volumes" {
  description = "The volumes this state owns, by kind."
  value = {
    durable     = sort([for v in docker_volume.durable : v.name])
    rebuildable = sort([for v in docker_volume.rebuildable : v.name])
  }
}
