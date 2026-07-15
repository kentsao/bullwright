# Bullwright cloud stubs (docs/ARCHITECTURE.md §7) — INTENTIONALLY INERT.
# Everything is gated behind var.enabled (default false): `terraform plan`
# with defaults provisions NOTHING. Flip deliberately when you decide to
# deploy, after reading docs/SPEC.md §9 on the security posture.

terraform {
  required_version = ">= 1.6"
}

variable "enabled" {
  description = "Master switch. Bullwright is local-first; nothing provisions until you flip this."
  type        = bool
  default     = false
}

variable "fly_app_name" {
  type    = string
  default = "bullwright"
}

# --- Sketch (fill in when deploying; see fly.toml for the app config) ---
# provider "fly" { ... }
#
# resource "fly_app" "api" {
#   count = var.enabled ? 1 : 0
#   name  = var.fly_app_name
# }
#
# resource "fly_postgres" "db" {
#   count = var.enabled ? 1 : 0
#   ...
# }
#
# Blog: static host (Cloudflare Pages / Netlify) — deploy apps/web/dist
# from CI, gate premium paths at the edge per docs/SUBSCRIPTION.md §3.

output "status" {
  value = var.enabled ? "ENABLED — review every resource before apply" : "disabled (local-first)"
}
