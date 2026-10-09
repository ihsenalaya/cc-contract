# Working rules

Read docs/methodology/protocol.md and experiments/status.json before changes.
Read docs/incidents/historical-gpu.md before GPU changes: preserve the
qualified host driver/kernel and CC, do not retry AKS, enable MIG or reset the
GPU. GPU Operator must use the host driver (driver.enabled=false). Historical
vLLM H08/H09 causes remain unconfirmed; never downgrade the driver to reproduce.
Never claim CPU fixtures validate CUDA, confidential computing or attestation.
Preserve original evidence outside Git. Use verified hashes to link public summaries.
No GPU provisioning before local qualification and approval of a concrete costed window.
When the user requests stopping until their decision, deallocate and retain the
VM, disk and restart resources. Never automatically destroy them after a sample;
destruction requires a later explicit user instruction.
Do not modify unrelated Azure resources. Never automatically force-push.
Verify each deliverable before proceeding. Every failed check is an incident.
Keep protocols versioned; do not change metrics to improve observed results.
Images must be built locally and qualified on Kind before GHCR publication.
Do not enable remote/cloud image builds in CI.
