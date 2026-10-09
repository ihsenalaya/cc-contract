mock_provider "azurerm" {}
variables {
  subscription_id = "00000000-0000-0000-0000-000000000000"
  window_id       = "test-only"
  ssh_public_key  = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGTKtvOwodXI9WIpcDD+Ea6LAaiAj+pnbAbVzNcAa33x cpu-test-fixture"
  ssh_source_cidr = "192.0.2.1/32"
  expires_at_utc  = "2026-10-09T12:00:00Z"
}
run "cloud_model_read_only" {
  command = plan
  variables {
    model_container_scope = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/cc-contract-artifacts/providers/Microsoft.Storage/storageAccounts/cccontract12345678/blobServices/default/containers/models"
  }
  assert {
    condition     = azurerm_linux_virtual_machine.gpu.identity[0].type == "SystemAssigned" && azurerm_role_assignment.model_read[0].role_definition_name == "Storage Blob Data Reader"
    error_message = "The GPU must use its own identity with read-only model rights."
  }
  assert {
    condition     = endswith(azurerm_role_assignment.model_read[0].scope, "/containers/models")
    error_message = "Model access must be scoped to the single private container."
  }
}
run "confidential_single_gpu_window" {
  command = plan
  assert {
    condition     = azurerm_linux_virtual_machine.gpu.size == "Standard_NCC40ads_H100_v5" && azurerm_linux_virtual_machine.gpu.secure_boot_enabled && azurerm_linux_virtual_machine.gpu.vtpm_enabled
    error_message = "H100 confidentiality properties must remain enabled."
  }
  assert {
    condition     = azurerm_linux_virtual_machine.gpu.os_disk[0].security_encryption_type == "DiskWithVMGuestState"
    error_message = "Confidential OS disk encryption is required."
  }
  assert {
    condition     = azurerm_logic_app_trigger_recurrence.expiry.interval == 1
    error_message = "Independent expiry must check every minute."
  }
  assert {
    condition     = strcontains(jsondecode(azurerm_logic_app_action_custom.expiry.body).actions.IfAllocated.actions.Deallocate.inputs.uri, "/deallocate?")
    error_message = "Expiry must release allocation, not merely shut down the guest."
  }
}
