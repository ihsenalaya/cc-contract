"""Bind the existing qualified images and completed local sample gate before plan."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import subprocess
import tarfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))


def sha(path):
    result=hashlib.sha256()
    with path.open('rb') as source:
        while chunk:=source.read(8*1024*1024):result.update(chunk)
    return result.hexdigest()


def verify_volume_preflight(path, source_binding_path, spec, spec_sha):
    proof=json.loads(path.read_text())
    binding=json.loads(source_binding_path.read_text())
    if (proof.get('scope')!='CPU_DETERMINISTIC_GENERATION_AND_SIZE_PROJECTION_NOT_GPU_TIMINGS' or
            proof.get('schedule_seed')!=spec['schedule_seed'] or
            proof.get('harness_sha256')!=spec['harness_sha256'] or
            proof.get('gpu_spec_sha256')!=spec_sha or
            proof.get('image_digest')!=spec['image_digest'] or
            proof.get('image_source_commit')!=spec['source_commit'] or
            proof.get('source_binding_sha256')!=sha(source_binding_path)):
        raise ValueError('Complete matching deterministic volume preflight required')
    if binding.get('all_equal') is not True or binding.get('image_source_commit')!=spec['source_commit']:
        raise ValueError('Volume preflight source binding differs from pinned IR image')
    required={'src/cc_contract/search.py','src/cc_contract/generators.py',
              'src/cc_contract/contracts.py','src/cc_contract/cli.py','src/cc_contract/native.py',
              'src/cuda/ir_worker.cu'}
    rows=binding.get('files',[])
    if not required.issubset({row['file'] for row in rows}):
        raise ValueError('Volume preflight lacks source bindings')
    for row in rows:
        file=Path(row['file'])
        if file.is_absolute() or '..' in file.parts:raise ValueError('Unsafe volume source path')
        original=subprocess.run(['git','show',spec['source_commit']+':'+file.as_posix()],
                                cwd=ROOT,check=True,capture_output=True).stdout
        if (row.get('equal') is not True or row['local_sha256']!=sha(ROOT/file) or
                row['pinned_image_source_sha256']!=hashlib.sha256(original).hexdigest() or
                row['local_sha256']!=row['pinned_image_source_sha256']):
            raise ValueError('Deterministic preflight source changed: '+str(file))
    jobs=proof.get('rows',[])
    if len(jobs)!=14:raise ValueError('Deterministic volume preflight must finish all fourteen jobs')
    upper_bounds=[];estimated_total=0
    for observed,planned in zip(jobs,spec['schedule']):
        if any(observed[key]!=planned['sample_block' if key=='block' else key]
               for key in ('block','position','method','seed')):
            raise ValueError('Volume preflight order or seeds differ from GPU specification')
        checkpoints=[mark for mark in observed['checkpoints']
                     if mark['selected_cases']==spec['selected_case_target']]
        if len(checkpoints)!=1:raise ValueError('Every method requires one full selected-case prefix')
        mark=checkpoints[0]
        expected_draws=spec['selected_case_target']*(1 if planned['method'] in ('B1','B2') else 16)
        if (mark['candidate_draws']!=expected_draws or
                not 0<=mark['invalid']<=spec['selected_case_target'] or
                type(mark['byte_projection_successful_cuda_payload']) is not int or
                not 0<mark['largest_record_bytes']<=mark['byte_projection_successful_cuda_payload']):
            raise ValueError('Invalid deterministic volume accounting')
        projected=mark['byte_projection_successful_cuda_payload'];estimated_total+=projected
        upper_bounds.append(4*projected+65536*spec['selected_case_target'])
    if proof.get('estimated_bytes100')!=estimated_total:
        raise ValueError('Deterministic trace volume total changed')
    if any(bound>=spec['trace_byte_limit_per_job'] for bound in upper_bounds):
        raise ValueError('Conservative trace projection exceeds per-job cap')
    if sum(upper_bounds)>=spec['total_trace_byte_limit']:
        raise ValueError('Conservative trace projection exceeds global cap')
    return {'scope':proof['scope'],'projected_successful_payload_bytes':estimated_total,
            'margin_multiplier':4,'per_selected_case_allowance_bytes':65536,
            'per_job_upper_raw_bytes':upper_bounds,'total_upper_raw_bytes':sum(upper_bounds),
            'guarantees_GPU_success_or_deadline_completion':False}


def verify_independent_cpu_review(path, kind):
    review=json.loads(path.read_text())
    if (review.get('state')!='PASS_BOTH_CPU_WORKERS' or review.get('gpu_executed') is not False or
            review.get('scope')!='INDEPENDENT_ORIGINAL_NATIVE_CPU_KIND_FUNCTIONAL_AUDIT_ONLY' or
            review.get('selected_cases_per_job')!=4 or review.get('total_jobs')!=28 or
            review.get('total_selected_cases')!=112 or
            review.get('all_original_payload_bytes_unchanged') is not True or
            review.get('reviewer_sha256')!=sha(ROOT/'scripts/review-work-sample.py') or
            len(review.get('workers',[]))!=2):
        raise ValueError('Independent original CPU Kind review required')
    for index,(observed,worker) in enumerate(zip(review['workers'],kind['workers'])):
        if (observed['node']!=worker['node'] or
                observed['original_archive_sha256']!=worker['archive_sha256'] or
                observed['original_archive_bytes']!=worker['archive_bytes'] or
                observed['state']!='PASS_CPU_FINITE_WORK_DIAGNOSTIC_AUDIT' or
                observed['gpu_executed'] is not False or observed['jobs']!=14 or
                observed['selected_cases']!=56 or
                observed['original_payload_bytes_unchanged'] is not True):
            raise ValueError('Independent review does not match original CPU worker archive')
        default=path.parent/('independent-audit-worker-'+str(index))/'independent-review.json'
        individual_path=Path(observed.get('independent_review_path',default))
        if sha(individual_path)!=observed['independent_review_sha256']:
            raise ValueError('Independent individual CPU review changed')
        individual=json.loads(individual_path.read_text())
        if (individual['state']!='PASS_CPU_FINITE_WORK_DIAGNOSTIC_AUDIT' or
                individual['gpu_executed'] is not False or
                individual['spec_sha256']!=kind['spec_sha256'] or
                individual['harness_sha256']!=kind['harness_sha256'] or
                individual['image_digest']!=kind['image_digest'] or
                individual['source_commit']!=kind['science_source_commit'] or
                individual['audited_jobs']!=14 or individual['audited_selected_cases']!=56 or
                individual['selected_case_quota_attained_for_all_fourteen_jobs'] is not True or
                individual['nonoverlapping_job_intervals_verified'] is not True or
                individual['all_case_traces_independently_recomputed'] is not True):
            raise ValueError('Independent CPU semantic audit scope or provenance changed')
        adapter_proof_path=individual_path.parent/'adapter-proof.json'
        if sha(adapter_proof_path)!=observed['adapter_proof_sha256']:
            raise ValueError('Independent CPU archive adapter proof changed')
        adapter_proof=json.loads(adapter_proof_path.read_text())
        if (adapter_proof['original_archive_sha256']!=worker['archive_sha256'] or
                adapter_proof['original_archive_bytes']!=worker['archive_bytes'] or
                adapter_proof['gpu_executed'] is not False or
                adapter_proof['all_original_payload_bytes_unchanged'] is not True):
            raise ValueError('Independent CPU adapter does not preserve the actual original archive')
        adapted_archive=individual_path.parent/'cpu-adapter.tar.gz'
        if sha(adapted_archive)!=individual['archive_sha256']:
            raise ValueError('The independently reviewed CPU adapter archive changed')
        original_archive=path.parent/('worker-'+str(index)+'.tar.gz')
        with tarfile.open(original_archive) as original,tarfile.open(adapted_archive) as adapted:
            original_files={member.name for member in original.getmembers() if member.isfile()}
            payloads=adapter_proof['original_payload_files']
            if {row['original_member'] for row in payloads}!=original_files or len(payloads)!=len(original_files):
                raise ValueError('CPU adapter proof omits or duplicates original files')
            for row in payloads:
                if row['original_payload_bytes_unchanged'] is not True:
                    raise ValueError('CPU adapter altered an original payload')
                before=original.extractfile(row['original_member']).read()
                after=adapted.extractfile(row['adapter_member']).read()
                if (before!=after or len(before)!=row['bytes'] or
                        hashlib.sha256(before).hexdigest()!=row['sha256']):
                    raise ValueError('CPU adapter payload differs from the actual Kind original')
    return review


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--kind-receipt',required=True,type=Path)
    parser.add_argument('--spec',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--volume-preflight','--volume-preflight-proof',required=True,type=Path)
    parser.add_argument('--volume-preflight-source-binding',required=True,type=Path)
    parser.add_argument('--independent-cpu-review',required=True,type=Path)
    args=parser.parse_args()
    loader=importlib.util.spec_from_file_location('sample',ROOT/'scripts/run-work-sample.py')
    sample=importlib.util.module_from_spec(loader);loader.loader.exec_module(sample)
    spec=json.loads(args.spec.read_text())
    if spec!=sample.make_spec('cuda'):raise ValueError('GPU sample specification changed')
    kind=json.loads(args.kind_receipt.read_text())
    if not kind['verified'] or kind['gpu_executed'] is not False or kind['harness_sha256']!=sample.harness_sha256() or kind['image_digest']!=sample.IMAGE_DIGEST:
        raise ValueError('Matching CPU sample qualification required')
    if {row['node'] for row in kind['workers']}!={'cc-contract-worker','cc-contract-worker2'} or any(row['completed_jobs']!=14 or row['gpu_executed'] is not False for row in kind['workers']):
        raise ValueError('Both CPU workers must finish all fourteen sequential sample jobs')
    if (kind['science_source_commit']!=sample.SOURCE_COMMIT or kind.get('selected_cases_per_job')!=4 or
            kind.get('safety_timeout_seconds')!=120 or kind.get('secret_access')!='DENIED' or
            any(row.get('finite_work_completed_jobs')!=14 or row.get('selected_cases_per_job')!=4
                for row in kind['workers'])):
        raise ValueError('Kind must qualify finite selected work, separately from GPU target 100')
    cpu_spec=args.kind_receipt.parent/'spec.json'
    if sha(cpu_spec)!=kind['spec_sha256']:
        raise ValueError('CPU original specification changed')
    for index,row in enumerate(kind['workers']):
        archive=args.kind_receipt.parent/('worker-'+str(index)+'.tar.gz')
        if sha(archive)!=row['archive_sha256'] or archive.stat().st_size!=row['archive_bytes']:
            raise ValueError('CPU original worker archive changed')
    volume_bounds=verify_volume_preflight(args.volume_preflight,
        args.volume_preflight_source_binding,spec,sha(args.spec))
    verify_independent_cpu_review(args.independent_cpu_review,kind)
    images={};gates={}
    for name in ('cuda','ir'):
        directory=ROOT/'.local'/name
        gate=json.loads((directory/'kind-verified.json').read_text())
        inspection=json.loads((directory/'inspect.json').read_text())[0]
        image=(directory/'remote-digest').read_text().strip()
        registry=json.loads((directory/'registry.json').read_text())
        if not gate['verified'] or gate['image_id']!=inspection['Id'] or image.split('@')[1]!=registry['digest'] or gate['git_commit']!=inspection['Config']['Labels']['org.opencontainers.image.revision']:
            raise ValueError('Existing image qualification or immutable publication changed')
        expected_source=sample.SOURCE_COMMIT if name=='ir' else 'e8f34fddc62479a6995dcf260a4242e1494cc26b'
        if gate['git_commit']!=expected_source:raise ValueError('Pinned image source changed')
        images[name]=image;gates[name]={'image_id':inspection['Id'],'kind_gate_sha256':sha(directory/'kind-verified.json'),'source_commit':gate['git_commit']}
    if images['ir']!=sample.IMAGE_DIGEST:raise ValueError('Sample must use the qualified IR digest')
    bundle={'schema_version':2,'transport':'FINITE_WORK_IR_SAMPLE','images':images,'image_gates':gates,
            'sample_spec_path':str(args.spec.resolve()),'sample_spec_sha256':sha(args.spec),
            'sample_harness_sha256':sample.harness_sha256(),'cpu_kind_receipt_sha256':sha(args.kind_receipt),
            'cpu_kind_receipt_path':str(args.kind_receipt.resolve()),
            'volume_preflight_path':str(args.volume_preflight.resolve()),
            'volume_preflight_sha256':sha(args.volume_preflight),
            'volume_preflight_source_binding_path':str(args.volume_preflight_source_binding.resolve()),
            'volume_preflight_source_binding_sha256':sha(args.volume_preflight_source_binding),
            'independent_cpu_review_path':str(args.independent_cpu_review.resolve()),
            'independent_cpu_review_sha256':sha(args.independent_cpu_review),
            'volume_planning_bounds':volume_bounds,
            'local_functional_selected_case_target':4,'gpu_selected_case_target':100,
            'gpu_jobs_parallel':False,'model_download_required':False,'comparative_campaigns_included':False}
    with args.output.open('x') as output:json.dump(bundle,output,indent=2);output.write('\n')
    args.output.chmod(0o444)
    print(json.dumps({'bundle_file':str(args.output),'bundle_sha256':sha(args.output),'planned_jobs':14,'gpu_created':False}))


if __name__=='__main__':main()
