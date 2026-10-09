terraform {
  required_version = "= 1.12.2"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "= 5.9.0"
    }
  }
  backend "local" {}
}

provider "azurerm" {
  features {}
  subscription_id                 = var.subscription_id
  resource_provider_registrations = "none"
  storage_use_azuread             = true
}

variable "subscription_id" { type = string }
variable "principal_id" { type = string }
variable "account_name" {
  type = string
  validation {
    condition     = can(regex("^cccontract[a-z0-9]{8,14}$", var.account_name))
    error_message = "Use a dedicated project storage account."
  }
}

resource "azurerm_resource_group" "artifacts" {
  name     = "cc-contract-artifacts"
  location = "eastus2"
  tags     = { project = "cc-contract", purpose = "durable-artifacts" }
  lifecycle { prevent_destroy = true }
}

resource "azurerm_storage_account" "artifacts" {
  name                              = var.account_name
  resource_group_name               = azurerm_resource_group.artifacts.name
  location                          = azurerm_resource_group.artifacts.location
  account_tier                      = "Standard"
  account_replication_type          = "LRS"
  account_kind                      = "StorageV2"
  access_tier                       = "Hot"
  min_tls_version                   = "TLS1_2"
  https_traffic_only_enabled        = true
  allow_nested_items_to_be_public   = false
  shared_access_key_enabled         = false
  default_to_oauth_authentication   = true
  infrastructure_encryption_enabled = true
  tags                              = azurerm_resource_group.artifacts.tags
  blob_properties {
    versioning_enabled = true
    delete_retention_policy { days = 30 }
    container_delete_retention_policy { days = 30 }
  }
  lifecycle { prevent_destroy = true }
}

resource "azurerm_role_assignment" "uploader" {
  scope                = azurerm_storage_account.artifacts.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = var.principal_id
}

resource "azurerm_storage_container" "data" {
  for_each              = toset(["models", "evidence"])
  name                  = each.key
  storage_account_id    = azurerm_storage_account.artifacts.id
  container_access_type = "private"
  depends_on            = [azurerm_role_assignment.uploader]
  lifecycle { prevent_destroy = true }
}

output "account_name" { value = azurerm_storage_account.artifacts.name }
output "account_id" { value = azurerm_storage_account.artifacts.id }
output "resource_group" { value = azurerm_resource_group.artifacts.name }
