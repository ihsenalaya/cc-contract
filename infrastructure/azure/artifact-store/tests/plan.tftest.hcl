mock_provider "azurerm" {}
variables {
  subscription_id = "00000000-0000-0000-0000-000000000000"
  principal_id    = "00000000-0000-0000-0000-000000000001"
  account_name    = "cccontractfixture01"
}
run "private_project_storage" {
  command = plan
  assert {
    condition = !azurerm_storage_account.artifacts.allow_nested_items_to_be_public && !azurerm_storage_account.artifacts.shared_access_key_enabled
    error_message = "Project storage must reject public and shared-key access."
  }
  assert {
    condition = azurerm_storage_account.artifacts.account_replication_type == "LRS" && azurerm_storage_account.artifacts.location == "eastus2"
    error_message = "Use the reviewed regional storage tier."
  }
  assert {
    condition = alltrue([for container in azurerm_storage_container.data : container.container_access_type == "private"])
    error_message = "Both containers must stay private."
  }
}
