"""Real PyTorch components and paired inference; CPU scope stays explicit."""
import argparse
from decimal import Decimal, localcontext
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
from datetime import datetime,timezone
from uuid import uuid4
from .oracles import dot_verdict, paired_logits, FLOAT32_U
from .cli import canonical,provenance


def prepare(torch, device):
    torch.set_num_threads(1)
    torch.manual_seed(17001)
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32=False
    torch.backends.cudnn.allow_tf32=False
    if device=='cuda' and not torch.cuda.is_available():
        return {'scope':'NO_GPU','gpu_executed':False,'verdict':'UNSUPPORTED','reason':'torch_cuda_unavailable'}
    return {'scope':'REAL_TORCH_CUDA' if device=='cuda' else 'REAL_TORCH_CPU_ONLY',
            'gpu_executed':device=='cuda','torch_version':torch.__version__,
            'compiled_cuda':torch.version.cuda,'hardware_attestation':'NOT_RUN_IN_WORKLOAD',
            'tf32':False,'deterministic_algorithms':True}


def transfer(torch, value, tag, device, asynchronous):
    if device=='cpu':
        return value.clone(),tag.clone()
    if not asynchronous:
        return value.to(device),tag.to(device)
    # Host lifetimes are retained until the transfer finishes. Values AND the
    # generation tensor physically cross the same ordered stream.
    host=value.pin_memory(); host_tag=tag.pin_memory(); stream=torch.cuda.Stream()
    with torch.cuda.stream(stream):
        result=host.to(device,non_blocking=True); generation=host_tag.to(device,non_blocking=True)
        done=torch.cuda.Event(); done.record(stream)
    torch.cuda.current_stream().wait_event(done)
    stream.synchronize()
    return result,generation


def attention_reference(q,k,v):
    with localcontext() as context:
        context.prec=60
        d=lambda x:Decimal.from_float(float(x))
        scale=Decimal(len(q[0])).sqrt()
        result=[]
        for row in q:
            scores=[sum(d(a)*d(b) for a,b in zip(row,key))/scale for key in k]
            exponentials=[(score-max(scores)).exp() for score in scores]
            weights=[e/sum(exponentials) for e in exponentials]
            result.append([float(sum(w*d(value[column]) for w,value in zip(weights,v))) for column in range(len(v[0]))])
        return result


def components(torch, device):
    environment=prepare(torch,device)
    if environment.get('verdict')=='UNSUPPORTED':
        return {'environment':environment,'verdict':'UNSUPPORTED','records':[]}
    records=[]
    with torch.inference_mode():
        for repeat in range(3):
            for asynchronous in (False,True):
                tokens=torch.tensor([0,3,7,15,3,1,9,0],dtype=torch.int64)
                ids,tag=transfer(torch,tokens,torch.tensor([repeat],dtype=torch.int64),device,asynchronous)
                values=[[float(i*8+j)/16 for j in range(8)] for i in range(16)]
                table=torch.tensor(values,dtype=torch.float32,device=device)
                embedding=torch.nn.functional.embedding(ids,table).cpu().tolist()
                expected=[values[i] for i in tokens.tolist()]
                exact=embedding==expected and tag.cpu().item()==repeat and ids.cpu().tolist()==tokens.tolist()
                records.append({'component':'tokens_embedding_metadata','repeat':repeat,'asynchronous':asynchronous,
                                'verdict':'PASS' if exact else 'FAIL','expected':expected,'observed':embedding,
                                'expected_generation':repeat,'observed_generation':tag.cpu().item()})
                rows=[[((i*7+j*3)%17-8)/16 for j in range(32)] for i in range(4)]
                weights=[[((i*5+j*11)%19-9)/16 for j in range(32)] for i in range(8)]
                input_tensor,_=transfer(torch,torch.tensor(rows,dtype=torch.float32),torch.tensor([repeat]),device,asynchronous)
                output=torch.nn.functional.linear(input_tensor,torch.tensor(weights,dtype=torch.float32,device=device)).cpu().tolist()
                checks=[dot_verdict(output[i][j],row,weight) for i,row in enumerate(rows) for j,weight in enumerate(weights)]
                records.append({'component':'linear','repeat':repeat,'asynchronous':asynchronous,
                                'verdict':'PASS' if all(c['verdict']=='PASS' for c in checks) else 'FAIL',
                                'observed':output,'oracles':checks})
                q=[[((i*3+j*7)%11-5)/32 for j in range(8)] for i in range(4)]
                k=[[((i*5+j*3)%13-6)/32 for j in range(8)] for i in range(4)]
                v=[[((i*7+j*5)%17-8)/16 for j in range(8)] for i in range(4)]
                q_tensor,_=transfer(torch,torch.tensor(q,dtype=torch.float32),torch.tensor([repeat]),device,asynchronous)
                scores=q_tensor @ torch.tensor(k,dtype=torch.float32,device=device).T/math.sqrt(8)
                actual=(torch.softmax(scores,dim=-1) @ torch.tensor(v,dtype=torch.float32,device=device)).cpu().tolist()
                reference=attention_reference(q,k,v)
                # Conservative forward bound for bounded normal inputs: score
                # dot/scaling, softmax exp/normalization, then weighted sum.
                gamma16=16*FLOAT32_U/(1-16*FLOAT32_U); gamma8=8*FLOAT32_U/(1-8*FLOAT32_U)
                score_error=gamma16*8*(6/32)**2/math.sqrt(8)+2*FLOAT32_U
                bound=.5*(2*score_error+16*FLOAT32_U+2*gamma8)+gamma8*.5
                error=max(abs(a-b) for x,y in zip(actual,reference) for a,b in zip(x,y))
                records.append({'component':'reduced_attention','repeat':repeat,'asynchronous':asynchronous,
                                'verdict':'PASS' if error<=bound else 'FAIL','maximum_absolute_error':error,
                                'bound':bound,'reference':'Decimal60_independent_softmax_and_dot','observed':actual,
                                'expected':reference,'bound_precondition':'bounded normal float32; TF32 disabled; exp error <= 4 float32 ulp'})
    return {'environment':environment,'records':records,'verdict':'PASS' if all(r['verdict']=='PASS' for r in records) else 'FAIL',
            'repeats_are_independent_campaigns':False,'model_inference':'NOT_RUN_COMPONENTS_ONLY'}


def tiny_transformer(torch):
    """Random small architecture fixture; never the Qwen 7B workload."""
    from transformers import Qwen2Config,Qwen2ForCausalLM
    prepare(torch,'cpu')
    config=Qwen2Config(vocab_size=64,hidden_size=32,intermediate_size=64,num_hidden_layers=1,
                       num_attention_heads=4,num_key_value_heads=2,max_position_embeddings=64)
    config._attn_implementation='eager'
    model=Qwen2ForCausalLM(config).eval(); inputs=torch.tensor([[1,3,5,7]])
    with torch.inference_mode():
        first=model(inputs).logits; second=model(inputs.clone()).logits
    return {'scope':'CPU_RANDOM_TINY_TRANSFORMER_FIXTURE','gpu_executed':False,
            'real_Qwen2_5_7B_executed':False,'verdict':'PASS' if torch.equal(first,second) else 'FAIL',
            'shape':list(first.shape),'parameters':sum(p.numel() for p in model.parameters())}


def _inference(torch, directory, corpus, output, device, start):
    from transformers import AutoModelForCausalLM,AutoTokenizer
    environment=prepare(torch,device)
    if environment.get('verdict')=='UNSUPPORTED':
        return {'verdict':'UNSUPPORTED','environment':environment}
    model_manifest=json.loads((directory/'cc-model-manifest.json').read_text())
    # Verify every downloaded file, including tokenizer/config and weight shards.
    for name,digest in model_manifest['file_sha256'].items():
        file=directory/name
        if file.resolve().parent!=directory.resolve() or hashlib.file_digest(file.open('rb'),'sha256').hexdigest()!=digest:
            raise ValueError('Model artifact integrity failure')
    tokenizer=AutoTokenizer.from_pretrained(directory,local_files_only=True,trust_remote_code=False)
    model=AutoModelForCausalLM.from_pretrained(directory,local_files_only=True,trust_remote_code=False,
              torch_dtype=torch.bfloat16,attn_implementation='eager').to(device).eval()
    cases=json.loads(corpus.read_text())
    if len(cases)!=24 or sorted(c['length'] for c in cases)!=[32]*8+[128]*8+[512]*8:
        raise ValueError('Expected 24 frozen prompts at 32/128/512 tokens')
    results=[]
    with torch.inference_mode():
        for index,case in enumerate(cases):
            encoded=tokenizer(case['text'],add_special_tokens=False)['input_ids']
            if encoded!=case['token_ids'] or len(encoded)!=case['length']:
                raise ValueError('Tokenized input differs from frozen corpus')
            cpu_tokens=torch.tensor([encoded],dtype=torch.int64)
            pairs=[]
            for asynchronous in (False,True):
                token_ids,tag=transfer(torch,cpu_tokens,torch.tensor([index]),device,asynchronous)
                begin=time.perf_counter(); steps=[]
                for token in [None]+case['forced_continuation']:
                    if token is not None:
                        token_ids=torch.cat([token_ids,torch.tensor([[token]],device=device)],dim=1)
                    # Forced continuation keeps both paths on identical inputs.
                    calculated=model(token_ids,output_hidden_states=True,use_cache=False)
                    logits=calculated.logits[0,-1].float().cpu()
                    hidden=calculated.hidden_states[-1][0,-1].float().cpu()
                    steps.append({'logits':logits,'hidden':hidden})
                if device=='cuda': torch.cuda.synchronize()
                artifact=output/f'case-{index:02d}-{"async" if asynchronous else "sync"}.pt'
                temporary=artifact.with_suffix('.tmp')
                torch.save({'steps':steps,'token_ids':token_ids.cpu(),'generation':tag.cpu()},temporary)
                temporary.replace(artifact)
                pairs.append({'steps':steps,'duration_seconds':time.perf_counter()-begin,'observed_generation':tag.cpu().item(),
                              'artifact':artifact.name,'sha256':hashlib.sha256(artifact.read_bytes()).hexdigest()})
            diagnostics=[]
            for a,b in zip(pairs[0]['steps'],pairs[1]['steps']):
                diagnostics.append({'logits':paired_logits(a['logits'].tolist(),b['logits'].tolist()),
                                    'hidden':paired_logits(a['hidden'].tolist(),b['hidden'].tolist())})
            result={'run_id':start['run_id'],'seed':17001,'case':index,'length':case['length'],'input_sha256':hashlib.sha256(canonical(encoded)).hexdigest(),
                    'pairs':[{k:v for k,v in p.items() if k!='steps'} for p in pairs],
                    'diagnostics':diagnostics,'metadata_exact':all(p['observed_generation']==index for p in pairs),
                    'scope':environment['scope'],'gpu_executed':environment['gpu_executed'],
                    'independent_model_correctness':'NOT_ESTABLISHED_BY_PAIRED_LOGITS'}
            results.append(result)
            with (output/'records.jsonl').open('ab') as file:
                file.write(canonical(result)); file.flush(); os.fsync(file.fileno())
    manifest={**start,'environment':environment,'model':model_manifest,'cases':len(results),
              'paired_path_divergences':sum(any(s['logits']['verdict']!='PASS' or s['hidden']['verdict']!='PASS' for s in r['diagnostics']) for r in results),
              'state':'COMPLETE_PAIRED_DIAGNOSTIC','independent_campaigns':1,
              'raw_sha256':hashlib.sha256((output/'records.jsonl').read_bytes()).hexdigest()}
    (output/'manifest.json').write_bytes(canonical(manifest))
    for file in output.iterdir(): file.chmod(0o444)
    return manifest


def inference(torch, directory, corpus, output, device):
    commit,dirty=provenance(); image=os.environ.get('CC_IMAGE_DIGEST','NOT_APPLICABLE_LOCAL_PROCESS')
    if device=='cuda' and ('@sha256:' not in image or dirty is True):
        raise ValueError('GPU inference requires committed sources and an immutable image digest')
    output.mkdir(parents=True,exist_ok=False,mode=0o700)
    start={'run_id':'inference-'+uuid4().hex,'timestamp_utc':datetime.now(timezone.utc).isoformat(),
           'git_commit':commit,'working_tree_dirty':dirty,'image_digest':image,'seed':17001,
           'corpus_sha256':hashlib.sha256(corpus.read_bytes()).hexdigest(),'device':device,
           'budget':{'prompts':24,'paths_per_prompt':2,'steps':'one plus frozen forced continuation'}}
    (output/'start.json').write_bytes(canonical(start))
    try:
        return _inference(torch,directory,corpus,output,device,start)
    except BaseException as error:
        raw=output/'records.jsonl'
        partial={**start,'state':'INFRA_FAILURE','error':type(error).__name__+': '+str(error),
                 'raw_sha256':hashlib.sha256(raw.read_bytes()).hexdigest() if raw.exists() else None}
        (output/'manifest.json').write_bytes(canonical(partial))
        for file in output.iterdir():
            if file.is_file():file.chmod(0o444)
        raise


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('command',choices=['components','local-selftest','inference'])
    parser.add_argument('--device',choices=['cpu','cuda'],default='cpu'); parser.add_argument('--model',type=Path)
    parser.add_argument('--corpus',type=Path); parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    import torch
    if args.command=='inference':
        if not args.model or not args.corpus or not args.output: parser.error('inference requires model/corpus/output')
        result=inference(torch,args.model,args.corpus,args.output,args.device)
    else:
        result=components(torch,args.device)
        if args.command=='local-selftest' and result['verdict']=='PASS':
            result['tiny_transformer_fixture']=tiny_transformer(torch)
            if result['tiny_transformer_fixture']['verdict']!='PASS': result['verdict']='FAIL'
    print(json.dumps(result,indent=2))
    return 77 if result.get('verdict')=='UNSUPPORTED' else 0 if result.get('verdict')=='PASS' or result.get('state')=='COMPLETE_PAIRED_DIAGNOSTIC' else 1


if __name__=='__main__': sys.exit(main())
