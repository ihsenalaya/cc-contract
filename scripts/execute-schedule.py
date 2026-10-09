"""Execute a versioned schedule; resume skips only hash-verified completed runs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from cc_contract.runner import backend,campaign


def select_complete(directory,config):
    for file in sorted(directory.glob('campaign-*/manifest.json')):
        manifest=json.loads(file.read_text())
        if manifest['configuration']==config and manifest['state']=='COMPLETE_BUDGET':
            raw=file.parent/manifest['raw_file']
            if hashlib.sha256(raw.read_bytes()).hexdigest()!=manifest['raw_sha256']:
                raise ValueError('Completed campaign evidence changed')
            return file
    return None


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--schedule',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--backend',choices=['model','native-reference','cuda'],default='model')
    parser.add_argument('--protocol-freeze',type=Path);parser.add_argument('--start-index',type=int,default=0)
    parser.add_argument('--jobs',required=True,type=int);parser.add_argument('--resume',action='store_true')
    args=parser.parse_args();schedule_bytes=args.schedule.read_bytes();jobs=json.loads(schedule_bytes)
    if args.jobs<1 or args.start_index<0 or args.start_index+args.jobs>len(jobs):
        parser.error('Requested jobs outside schedule')
    if args.backend=='cuda':
        if not args.protocol_freeze:parser.error('GPU comparison requires a frozen, reviewed protocol')
        freeze=json.loads(args.protocol_freeze.read_text())
        if not freeze['frozen'] or freeze['schedule_sha256']!=hashlib.sha256(schedule_bytes).hexdigest():
            parser.error('Schedule does not match frozen protocol')
        if freeze['image_digest']!=os.environ.get('CC_IMAGE_DIGEST') or freeze['oracle_version']!='integer_physical_tag_v2':
            parser.error('Execution image/oracle differs from freeze')
    args.output.mkdir(parents=True,exist_ok=True,mode=0o700)
    executor=backend(args.backend)
    try:
        for index in range(args.start_index,args.start_index+args.jobs):
            config=jobs[index]
            existing=select_complete(args.output,config) if args.resume else None
            if existing:
                manifest=json.loads(existing.read_text())
                if manifest['environment']['scope']!=executor.environment['scope']:
                    raise ValueError('Resume cannot substitute a CPU run for a GPU run')
                print(json.dumps({'index':index,'state':'SKIPPED_VERIFIED_COMPLETE','manifest':str(existing)}),flush=True)
                continue
            result=campaign(executor,config,args.output)
            print(json.dumps({'index':index,'state':result['state'],'run_id':result['run_id']}),flush=True)
            if result['state']!='COMPLETE_BUDGET':return 1
    finally:executor.close()
    return 0


if __name__=='__main__':sys.exit(main())
