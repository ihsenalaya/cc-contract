# Offline review of fixed-work campaign originals

The 140 GPU jobs execute successively. CPU review may use four independent
processes after confirmed H100 deallocation. The portable helper composes the
unchanged `scripts/analyze-fixed-work-campaign.py` semantic auditor and statistical
coordinator; it preserves original compressed archives and does not extract raw
case files. Each worker is limited to 1 GiB of address space. Kind CPU archive
qualification is distinct from real GPU evidence.

Confirm the retained VM is deallocated through a fresh Azure readback first.
Use the exact archive basename recorded by `collection.json`, never a wildcard.
For GPU evidence, the original `release.json` must reside beside that collection.
The helper checks its state, timestamps and hashes, but does not itself consult
Azure. Pin the original analyzer SHA before invocation:

```bash
PYTHONPATH=src python3 scripts/analyze-fixed-work-campaign-parallel.py \
  --repo-root "$PWD" \
  --expected-analyzer-sha256 560872b8f008e40f5d7440e1cfa4a396c77d6bbd145705a0f9312d6a10eddb5f \
  --archive /private/campaign/ARCHIVE_FROM_COLLECTION.tar.gz \
  --collection-json /private/campaign/collection.json \
  --deallocation-receipt /private/campaign/release.json \
  --output /private/campaign/fresh-independent-audit.json --workers 4
```

Use a fresh output path. The helper checks immutable source bindings, a complete
original hash inventory, ordered worker proofs and unchanged inputs after review.
Its JSON result, parallel receipt and worker proofs remain outside Git; publish
reviewed summaries and hashes separately. Candidate FAILs require the registered
fresh-process reproductions and external characterization before confirmation.
No automatic superiority, power, whole-project or GPU-attestation claim is emitted.
