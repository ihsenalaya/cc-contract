# Threat model and trusted boundary

Trust the application intent constructor, verifier, API adapter, instrumented
consumer and qualified software stack inside the confidential VM. The fault model
is accidental application state misuse or controlled fault injection at the
transfer, dependency or graph-binding boundary. Metadata is not an attacker-proof
capability. A compromised adapter or consumer can forge a self-consistent witness.

NVIDIA CC protects data and execution within its documented threat model; HDSC
checks an additional application condition. CC ON / PRODUCTION and Secure Boot
are environment evidence, not a new attestation verification result. The pilot
performed no independent GPU quote verification.
[NVIDIA trusted-computing documentation](https://docs.nvidia.com/nvtrust/index.html).

Excluded: malicious trusted code, arbitrary uninstrumented kernels, memory-safety
proofs, side channels, physical attacks, CUDA implementation bugs, and replacement
of remote attestation. The monitor cannot determine that an application declared
the wrong intent. Equal-payload generations matter only if the application contract
requires the version/identity to differ. A violation is not automatically output
corruption, security exploitation or user-visible model degradation.

The security analysis of NVIDIA GPU-CC examines architectural engines, boot and
CPU/GPU transfer protection; it must not be treated as a semantic detector baseline.
[Blueprint, Bootstrap, and Bridge, MLSys 2026](https://proceedings.mlsys.org/paper_files/paper/2026/file/906419cd502575b617cc489a1a696a67-Paper-Conference.pdf).
