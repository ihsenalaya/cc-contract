"""Pinned GPT-Neo eager attention with its scalar mask allocated before capture.

The attention arithmetic below is adapted from Transformers 4.57.1
models/gpt_neo/modeling_gpt_neo.py, Copyright 2021 The Eleuther AI and HuggingFace
Inc. team, licensed under Apache-2.0 (https://www.apache.org/licenses/LICENSE-2.0).
Modification: replace the per-call host-created mask tensor with an identical
FP32 registered constant. No model weights, attention algorithm or masks change.
"""
import hashlib
import inspect
from contextlib import contextmanager, nullcontext
from types import MethodType

UPSTREAM_SHA256='5ba65e08c12632b0275b35728dc09161e4fbb2b49bd9dd1b92bac563aadc6a8c'


def _attn(self, query, key, value, attention_mask=None, head_mask=None):
    import torch
    query=query.to(torch.float32)
    key=key.to(torch.float32)
    attn_weights=torch.matmul(query,key.transpose(-1,-2))
    query_length,key_length=query.size(-2),key.size(-2)
    causal_mask=self.bias[:,:,key_length-query_length:key_length,:key_length]
    attn_weights=torch.where(causal_mask,attn_weights,self._hdsc_mask_value)
    if attention_mask is not None:
        causal_mask=attention_mask[:,:,:,:key.shape[-2]]
        attn_weights=attn_weights+causal_mask
    attn_weights=torch.nn.functional.softmax(attn_weights,dim=-1)
    attn_weights=attn_weights.to(value.dtype)
    attn_weights=self.attn_dropout(attn_weights)
    if head_mask is not None:attn_weights=attn_weights*head_mask
    attn_output=torch.matmul(attn_weights,value)
    return attn_output,attn_weights


def install(model):
    import torch
    import transformers
    from transformers.models.gpt_neo.modeling_gpt_neo import GPTNeoSelfAttention
    if transformers.__version__!='4.57.1' or hashlib.sha256(inspect.getsource(GPTNeoSelfAttention._attn).encode()).hexdigest()!=UPSTREAM_SHA256:
        raise ValueError('Unqualified GPT-Neo attention implementation')
    if model.training or model.config.model_type!='gpt_neo' or model.config._attn_implementation!='eager':
        raise ValueError('Adapter requires the qualified evaluation-mode eager GPT-Neo')
    layers=[m for m in model.modules() if isinstance(m,GPTNeoSelfAttention)]
    if len(layers)!=model.config.num_layers or not layers:
        raise ValueError('Incomplete attention layer inventory')
    for layer in layers:
        if type(layer) is not GPTNeoSelfAttention or hasattr(layer,'_hdsc_mask_value'):
            raise ValueError('Unexpected or already adapted attention layer')
        if layer.q_proj.weight.dtype!=torch.float32:
            raise ValueError('Only the frozen FP32 workload is qualified')
    for layer in layers:
        layer.register_buffer('_hdsc_mask_value',torch.tensor(torch.finfo(torch.float32).min,
            dtype=torch.float32,device=layer.q_proj.weight.device),persistent=False)
        layer._attn=MethodType(_attn,layer)
    return dict(version='gptneo-preallocated-mask-v1',upstream_attention_sha256=UPSTREAM_SHA256,
                layers=len(layers),constant_bytes=4*len(layers),applies_equally_to_ON_and_OFF=True)


@contextmanager
def upstream_eager(model):
    """Development equivalence check only; restore bound methods even on error."""
    from transformers.models.gpt_neo.modeling_gpt_neo import GPTNeoSelfAttention
    layers=[m for m in model.modules() if isinstance(m,GPTNeoSelfAttention)]
    if not layers or any(not hasattr(m,'_hdsc_mask_value') for m in layers):
        raise ValueError('Equivalence check requires the installed adapter')
    saved=[m._attn for m in layers]
    try:
        for layer in layers:layer._attn=MethodType(GPTNeoSelfAttention._attn,layer)
        yield
    finally:
        for layer,method in zip(layers,saved):layer._attn=method


def equivalence(transformer,seed=82000):
    """Compare three live buffers with upstream eager, adapted eager and GPU replay.

    Restricted to development inputs. Nine forwards on GPU (six on CPU), separate
    from performance timing and never counted as reserved experimental requests.
    """
    from .hdsc_ai import prompt_for_seed
    if seed not in range(82000,82008):raise ValueError('Development seeds only')
    torch=transformer.torch
    tokens=transformer.tokenizer.encode(prompt_for_seed(seed))[-16:]
    tokens=[transformer.tokenizer.eos_token_id]*(16-len(tokens))+tokens
    rows=[]
    context=torch.cuda.stream(transformer.consumer) if transformer.device=='cuda' else nullcontext()
    with torch.inference_mode(),context:
        for slot,buffer in enumerate(transformer.buffers):
            values=[slot+1,2,16,*tokens] if transformer.enabled else tokens
            buffer.copy_(torch.tensor(values,dtype=torch.long,device='cpu'),non_blocking=False)
            with upstream_eager(transformer.model):
                original=transformer.compute(buffer)[0].detach().cpu().clone()
            eager=transformer.compute(buffer)[0].detach().cpu().clone()
            graph=None
            if transformer.device=='cuda':
                transformer.graphs[slot].replay()
                graph=transformer.outputs[slot].detach().cpu().clone()
            if not torch.equal(original,eager) or graph is not None and not torch.equal(original,graph):
                raise ValueError('Graph adapter changes original eager logits; stop before evaluation')
            rows.append(dict(slot=slot,original_logits=original.tolist(),adapted_eager_logits=eager.tolist(),
                             graph_logits=graph.tolist() if graph is not None else None))
    return dict(scope='GPU_DEVELOPMENT_GRAPH_EQUIVALENCE' if transformer.device=='cuda' else 'CPU_DEVELOPMENT_EQUIVALENCE_ONLY',
                seed=seed,enabled=transformer.enabled,exact_logits_equal=True,buffers=rows)
