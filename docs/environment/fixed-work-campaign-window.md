# Fixed-work E4/E5 campaign on the retained confidential H100

The user explicitly requested **140 successive jobs of 100 selected cases**,
then immediate deallocation with the VM and its disk retained. Protocol
[v0.3](../methodology/fixed-work-campaign-v0.3.md) keeps all twenty paired
blocks, the seven methods and the reserved order/seeds. It declares a new
fixed-work completion rule; the original 600-second draft schedule remains
unchanged. Invalid proposals count toward selected work and are rejected
before CUDA. This design does not establish statistical power or superiority.

The measured development pilot projects **50 min 38 s of job execution**,
with a descriptive two-block range of 46 min 30 s–54 min 45 s. Startup,
host requalification and verified export add allocated time. Actual start,
power observations, every job and confirmed deallocation are recorded
separately. These are estimates, not guaranteed completion times.

Campaign identity: `fixed-work-1010a`. Retained VM/window:
`work-sample-1009b`. The authorized ceiling remains **USD 15 forecast and
90 minutes from planning**, with an independent minute Azure expiry guard.
The update-only Terraform plan may renew expiry/workload tags and the
single approved SSH source IP; it must create, destroy and replace zero
resources and retain the same actual VM UUID and thirteen managed resources.
No additional GPU is reserved. A startup exceeding fifteen minutes aborts;
the workload has a 60-minute external command guard and 120 seconds per job.

Before starting compute, source tests, native CPU integration on both Kind
workers (140 × 4 each), permissions, immutable image qualifications,
independent original-case reviews and lifecycle error paths must pass.
The existing locally built CUDA/IR images are reused by digest. The wrapper
and shared helper are hash-bound read-only mounts; no Torch image or model
download is required for this workload. CPU results remain qualification
evidence and are never pooled with GPU measurements.

Preserve driver 595.91.07, kernel 6.8.0-1066-azure-fde, CC ON/PRODUCTION and
SecureBoot. Do not enable MIG, use concurrent GPU jobs, reset the GPU,
reinstall the driver or rebuild the qualified VM. Host/attestation/CUDA/IR
failure blocks the campaign. Any candidate failure, unsupported execution,
quota, timeout, interruption or infrastructure failure stops later jobs.
Original partial evidence is preserved; diagnose locally after deallocation.

Guest originals use a fresh campaign directory, keeping prior pilot originals
separate. Trace limits are 1 GiB per job and 32 GiB total, with 2 GiB free
reserve. The compressed local download is capped at 8 GiB; planning verifies
physical Windows space as well as WSL space. Export failures still deallocate
compute after an eight-minute export deadline, including a stalled SSH stream,
and keep the persistent disk. Complete or partial originals and their
hashes are backed up to private Azure storage and verified remotely before
any deletion. Resources remain until a later explicit user instruction.

After confirmed deallocation, audit raw cases, selections, ordering, coverage,
payloads and quotas locally. Analyze paired blocks using the predeclared
metrics; report unresolved anomalies and zero detections truthfully.
E0/E1/E3/E6/E7/E8 are not completed by this E4/E5 campaign.
Publish sanitized manifests and verified summaries to GitHub, keeping
original traces, credentials, Azure state and model weights outside Git.
