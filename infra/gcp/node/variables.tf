# The machine's shape is read from _data/hosting.yml `node:`. Only what must
# stay out of the repo is a variable: deploy.sh passes it from the environment.

variable "project_id" {
  description = "The Google Cloud project the platform runs in. Never committed: deploy.sh reads GCP_PROJECT_ID."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a Google Cloud project id: 6 to 30 lowercase letters, digits and hyphens."
  }
}

variable "instance" {
  description = "Which machine of _data/hosting.yml this state describes: `node` (the platform's machine) or `dev` (the development instance). deploy.sh sets it."
  type        = string
  default     = "node"

  validation {
    condition     = contains(["node", "dev"], var.instance)
    error_message = "instance must be node or dev: the two machines _data/hosting.yml describes."
  }
}
