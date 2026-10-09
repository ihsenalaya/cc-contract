# Historical GPU reports and operational constraints

Source: the user's mission prompt, sections 2.3, Kubernetes on Azure, and E3.
These are historical reports, not observations reproduced in this repository.
Original prior-campaign logs, full configurations and traces are not available
here. Record causes as unconfirmed until evidence establishes them.

| Report | Historical observation | Current state |
|---|---|---|
| AKS integration | Previously attempted without success | Do not retry; use automated kubeadm when Azure Kubernetes is required |
| H08 | vLLM logits diverged from the first token | NOT_REPRODUCED; cause unconfirmed |
| H09 | CUDA sampler assertion around `top_k=0` | NOT_REPRODUCED; cause unconfirmed |
| MIG / guest GPU reset | Unsupported in the tested confidential configuration | Do not enable MIG or attempt unsupported reset |

Historical reference: East US 2, Standard_NCC40ads_H100_v5, H100 NVL 94 GiB,
CC ON, host NVIDIA driver 595.91.07, working attestation after onboarding,
Transformers inference previously validated, vLLM 0.25/0.26 anomalies reported.
Versions, availability and compatibility must be checked for each new deployment;
this reference does not establish current subscription resources or qualification.

Preserve the qualified host driver, kernel, NVIDIA modules and CC mode. With
GPU Operator, retain `driver.enabled: false` and `toolkit.enabled: true`. Do not
reinstall the operator without justification and agreement. Do not reset kubeadm
or rebuild a qualified machine during a campaign. Approved temporary recreation
between windows requires renewed qualification. Never downgrade the driver to
reproduce H08/H09. A working nvidia-smi is not inference correctness evidence;
vLLM, Compute Sanitizer and CUPTI support in CC must not be assumed.
