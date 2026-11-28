# What is hosted, where and from which repo is read from _data/hosting.yml.
# Only what must stay out of the repo, or is the maintainer's to choose at
# apply time, is a variable: deploy.sh passes each from the environment.

variable "project_id" {
  description = "The Google Cloud project the platform runs in. Never committed: deploy.sh reads GCP_PROJECT_ID."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a Google Cloud project id: 6 to 30 lowercase letters, digits and hyphens."
  }
}

variable "env" {
  description = "The environment label every resource carries (ADR 0018, decision 6)."
  type        = string
  default     = "prod"
}

variable "billing_account" {
  description = "The billing account id for the budget alert. Empty: no budget is created here (deploy.sh reads GCP_BILLING_ACCOUNT)."
  type        = string
  default     = ""
}

variable "budget_usd" {
  description = "The monthly amount the budget alerts at 50, 90 and 100 percent of. An alert, never a cap: Google Cloud does not stop spending at a budget."
  type        = number
  default     = 50
}
