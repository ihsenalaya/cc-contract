# Remaining HDSC AI evaluation — corrected graph preparation

The owner has freshly authorized the next H100 start after local qualification.
Announced limits: **30 minutes planned maximum / USD 4 forecast**, sequential
execution only. This authorization is distinct from the completed recovery-only
window. Freeze an executable plan and record this instruction in its private
receipt after all local gates pass.

## Confirmed incident and correction

INC-0132 identifies the first AI failure: Transformers 4.57.1 GPT-Neo eager
attention constructed its scalar mask tensor during CUDA Graph capture, which
CUDA rejected. No reserved AI request completed. The failed original and its
traceback are preserved, with hashes and verified private Azure copies. The
recovery-only window took 169.558006 seconds and ended DEALLOCATED.

The adapter allocates the same FP32 minimum-value constant before capture for
each of eight attention layers (32 bytes total). Arithmetic, global/local masks,
weights, model assets, TF32 setting, seeds, fault targets and output criteria
remain unchanged. The adapter checks the exact upstream method source hash and
model configuration; unexpected versions fail. It applies equally to ON and OFF.
This is a disclosed adaptation of the model implementation, not a claim that
unmodified Transformers graph capture works. Retain its Apache license and
[upstream attribution](https://github.com/huggingface/transformers/blob/v4.57.1/src/transformers/models/gpt_neo/modeling_gpt_neo.py).

No fallback to CPU/eager-only execution is allowed in GPU evaluation. There is no
relaxation of numeric comparisons, removal of graph replay, detector tuning or
replacement of seeds after seeing an outcome. Negative or inconclusive scientific
results remain reportable. CPU equivalence cannot establish CUDA capture support.

## Exact next execution

| Work | Jobs / requests |
|---|---:|
| Development GPU equivalence and healthy control, OFF then ON | 2 / 2 |
| Reserved healthy/injected Transformer pairs | 40 / 80 |
| Separate reserved Transformer healthy controls | 10 / 10 |
| Reserved performance modes (ten paired blocks) | 20 / 260 |
| **Total** | **72 / 352** |

Each of the 72 model constructions has nine eager warmup forwards and three graph
captures: 864 setup forwards. The two development instances additionally perform
nine equivalence forwards each, comparing upstream eager, adapted eager and graph
replay on three live buffers with development seed 82000. Thus 882 forwards occur
outside the listed requests. The 260 performance requests comprise 60 warmups and
200 measured requests. Development results are never additional reserved blocks.

Both development controls must show byte-identical logits across the three paths,
finite output, correct healthy verdicts and matching ON/OFF tokens. Any failure
stops before reserved AI jobs. Reserved maximum job durations and order remain
those of the original frozen schedule (120/180 seconds). The development controls
have 180 seconds each. No repeated native, RQ1, Qwen, sanitizer or search jobs.

## Provenance and local gates

The 363 native jobs of `hdsc-eval-1010b` remain intact and are not repeated. Recover
and hash-check their complete 1,083-record stream before admission, including the
720 unsupported records. The first interrupted `1010a` attempt remains excluded
in its entirety. The final analysis composes disjoint core/AI sections with their
separate plan/source/image identities, never pooling repeated attempts as new
independent blocks. Previously exposed inputs are disclosed.

Required local gates: full source checks and exact-source CI; synthetic attention
tests covering optional masks, unchanged weights and method restoration; exact
trained-model development logits; original fault/healthy CPU qualification;
locally built AI image qualified on Kind and published by immutable digest;
model and evidence hashes, secret scan, retained inventory and frozen plan.
Native source/image provenance is recorded separately; only the AI image changes.

## Cost and release

Reuse the qualified VM/disk, driver 595.91.07, kernel 6.8.0-1066-azure-fde,
CC ON/PRODUCTION and Secure Boot. Zero created/deleted resources, no MIG/reset,
host change or cloud build. Existing controller and independent expiry guards
bound the single start: guest expiry minute 23, admission reserve two minutes,
Azure expiry minute 27, deallocation confirmed and disk retained. Any technical
error immediately stops; bounded final diagnostic tails return over SSH before
deallocation. No automatic second restart.

Planning assumption 10–25 minutes, not measured GPU AI duration. The verified
Linux East US 2 retail rate is USD 6.98/hour: 30 minutes compute USD 3.49, forecast
USD 4 with margin. This is not a hard invoice cap; retained disk/IP/tax and Azure
control-plane delays are separate. Count the entire start-to-deallocation cycle.
After collection, deallocate before independent local audit and evidence backup.
If no valid complete paired performance result exists, report RQ4 incomplete.
