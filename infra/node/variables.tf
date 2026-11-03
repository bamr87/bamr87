# Inputs are generated, never hand-written: `tools/dash node gen` (or
# `dash infra plan`) writes .fleet/nodes/<node>.tfvars.json from
# _data/fleet.yml `nodes:` resolved against docker-compose.yml.

variable "node" {
  description = "The fleet node this state describes (a nodes.hosts key in _data/fleet.yml)."
  type        = string
}

variable "docker_host" {
  description = "The node's Docker endpoint. SSH is the only API to a workload node (docs/FORGE-HOST.md)."
  type        = string

  validation {
    condition     = startswith(var.docker_host, "ssh://") || startswith(var.docker_host, "unix://")
    error_message = "docker_host must be ssh:// (a workload node) or unix:// (this machine), never a TCP socket."
  }
}

variable "network" {
  description = "The shared network every fleet compose project joins (containers.network)."
  type        = string
  default     = "fleet"
}

variable "durable_volumes" {
  description = "Full volume names whose loss a rebuild cannot repair (nodes.durable_volumes); created with prevent_destroy."
  type        = list(string)
  default     = []
}

variable "rebuildable_volumes" {
  description = "Full volume names a fresh start, reindex or re-export can refill."
  type        = list(string)
  default     = []
}
