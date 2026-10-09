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
}

variable "subscription_id" { type = string }
variable "window_id" {
  type = string
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{2,20}$", var.window_id))
    error_message = "Use a unique lowercase window identifier."
  }
}
variable "ssh_public_key" { type = string }
variable "ssh_source_cidr" {
  type = string
  validation {
    condition     = can(cidrhost(var.ssh_source_cidr, 0)) && endswith(var.ssh_source_cidr, "/32")
    error_message = "SSH is restricted to a single approved IPv4 address."
  }
}
variable "expires_at_utc" {
  type = string
  validation {
    condition     = can(formatdate("YYYY-MM-DD", var.expires_at_utc)) && endswith(var.expires_at_utc, "Z")
    error_message = "Specify the approved absolute UTC expiry, with Z suffix."
  }
}
variable "workload_sha256" {
  type    = string
  default = ""
}
variable "host_script_sha256" {
  type    = string
  default = ""
}
variable "model_container_scope" {
  type    = string
  default = ""
  validation {
    condition     = var.model_container_scope == "" || can(regex("^/subscriptions/[a-f0-9-]+/resourceGroups/cc-contract-artifacts/providers/Microsoft.Storage/storageAccounts/cccontract[a-z0-9]{8,14}/blobServices/default/containers/models$", var.model_container_scope))
    error_message = "The GPU may read only the dedicated project model container."
  }
}
variable "confidential_image_id" {
  type    = string
  default = "/communityGalleries/cgpuimage-db870bae-5bcf-4120-9415-b841adef61d3/images/cgpu-NCC-2204-base-image/versions/2204.20260928.0"
  validation {
    condition     = can(regex("^/communityGalleries/.+/images/cgpu-NCC-.+/versions/[0-9.]+$", var.confidential_image_id))
    error_message = "Use a pinned confidential GPU community image version, never latest."
  }
}
locals {
  location = "eastus2"
  name     = "cc-contract-${var.window_id}"
  tags     = merge({ project = "cc-contract", window = var.window_id, expires_at = var.expires_at_utc }, var.workload_sha256 == "" ? {} : { workload_sha256 = var.workload_sha256, host_script_sha256 = var.host_script_sha256 })
  vm_id    = "/subscriptions/${var.subscription_id}/resourceGroups/${local.name}/providers/Microsoft.Compute/virtualMachines/${local.name}"
}
resource "azurerm_resource_group" "window" {
  name     = local.name
  location = local.location
  tags     = local.tags
}
resource "azurerm_virtual_network" "window" {
  name                = local.name
  resource_group_name = azurerm_resource_group.window.name
  location            = local.location
  address_space       = ["10.239.0.0/16"]
  tags                = local.tags
}
resource "azurerm_subnet" "window" {
  name                 = "gpu"
  resource_group_name  = azurerm_resource_group.window.name
  virtual_network_name = azurerm_virtual_network.window.name
  address_prefixes     = ["10.239.0.0/24"]
}
resource "azurerm_network_security_group" "window" {
  name                = local.name
  resource_group_name = azurerm_resource_group.window.name
  location            = local.location
  tags                = local.tags
  security_rule {
    name                       = "approved-ssh"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = var.ssh_source_cidr
    destination_address_prefix = "*"
  }
}
resource "azurerm_subnet_network_security_group_association" "window" {
  subnet_id                 = azurerm_subnet.window.id
  network_security_group_id = azurerm_network_security_group.window.id
}
resource "azurerm_public_ip" "window" {
  name                = local.name
  resource_group_name = azurerm_resource_group.window.name
  location            = local.location
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.tags
}
resource "azurerm_network_interface" "window" {
  name                = local.name
  resource_group_name = azurerm_resource_group.window.name
  location            = local.location
  tags                = local.tags
  ip_configuration {
    name                          = "gpu"
    subnet_id                     = azurerm_subnet.window.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.window.id
  }
}
# This expiry guard is created BEFORE the GPU, independent of any local process.
# It deallocates only; the OS disk remains until evidence is verified and destroy approved.
resource "azurerm_logic_app_workflow" "expiry" {
  name                = "${local.name}-expiry"
  resource_group_name = azurerm_resource_group.window.name
  location            = local.location
  tags                = local.tags
  identity { type = "SystemAssigned" }
}
resource "azurerm_role_definition" "expiry" {
  name        = "${local.name}-deallocate"
  scope       = azurerm_resource_group.window.id
  description = "Read instance state and deallocate CC-Contract window VMs only."
  permissions {
    actions = ["Microsoft.Compute/virtualMachines/read", "Microsoft.Compute/virtualMachines/instanceView/read", "Microsoft.Compute/virtualMachines/deallocate/action"]
  }
  assignable_scopes = [azurerm_resource_group.window.id]
}
resource "azurerm_role_assignment" "expiry" {
  scope              = azurerm_resource_group.window.id
  role_definition_id = azurerm_role_definition.expiry.role_definition_resource_id
  principal_id       = azurerm_logic_app_workflow.expiry.identity[0].principal_id
}
resource "azurerm_logic_app_trigger_recurrence" "expiry" {
  name         = "ExpiryTick"
  logic_app_id = azurerm_logic_app_workflow.expiry.id
  frequency    = "Minute"
  interval     = 1
}
resource "azurerm_logic_app_action_custom" "expiry" {
  name         = "ExpiryGuard"
  logic_app_id = azurerm_logic_app_workflow.expiry.id
  body = jsonencode({
    type       = "If"
    expression = { greaterOrEquals = ["@ticks(utcNow())", "@ticks('${var.expires_at_utc}')"] }
    actions = {
      GetState = {
        type = "Http"
        inputs = {
          method         = "GET"
          uri            = "https://management.azure.com${local.vm_id}/instanceView?api-version=2024-03-01"
          authentication = { type = "ManagedServiceIdentity", audience = "https://management.azure.com/" }
        }
        runAfter = {}
      }
      IfAllocated = {
        type       = "If"
        expression = { not = { contains = ["@string(body('GetState'))", "PowerState/deallocated"] } }
        actions = {
          Deallocate = {
            type = "Http"
            inputs = {
              method         = "POST"
              uri            = "https://management.azure.com${local.vm_id}/deallocate?api-version=2024-03-01"
              authentication = { type = "ManagedServiceIdentity", audience = "https://management.azure.com/" }
            }
            runAfter = {}
          }
        }
        else     = { actions = {} }
        runAfter = { GetState = ["Succeeded"] }
      }
    }
    else     = { actions = {} }
    runAfter = {}
  })
  depends_on = [azurerm_role_assignment.expiry]
}
resource "azurerm_linux_virtual_machine" "gpu" {
  name                            = local.name
  resource_group_name             = azurerm_resource_group.window.name
  location                        = local.location
  size                            = "Standard_NCC40ads_H100_v5"
  admin_username                  = "cccontract"
  disable_password_authentication = true
  network_interface_ids           = [azurerm_network_interface.window.id]
  source_image_id                 = var.confidential_image_id
  secure_boot_enabled             = true
  vtpm_enabled                    = true
  tags                            = local.tags
  dynamic "identity" {
    for_each = var.model_container_scope == "" ? [] : [1]
    content { type = "SystemAssigned" }
  }
  admin_ssh_key {
    username   = "cccontract"
    public_key = var.ssh_public_key
  }
  os_disk {
    name                     = "${local.name}-os"
    caching                  = "ReadWrite"
    storage_account_type     = "StandardSSD_LRS"
    disk_size_gb             = 128
    security_encryption_type = "DiskWithVMGuestState"
  }
  boot_diagnostics {}
  depends_on = [azurerm_logic_app_action_custom.expiry, azurerm_logic_app_trigger_recurrence.expiry, azurerm_subnet_network_security_group_association.window]
}
resource "azurerm_role_assignment" "model_read" {
  count                = var.model_container_scope == "" ? 0 : 1
  scope                = var.model_container_scope
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_linux_virtual_machine.gpu.identity[0].principal_id
}
output "vm_id" { value = azurerm_linux_virtual_machine.gpu.id }
output "ssh_address" { value = azurerm_public_ip.window.ip_address }
output "resource_group" { value = azurerm_resource_group.window.name }
output "expiry" { value = var.expires_at_utc }
