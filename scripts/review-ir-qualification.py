"""Recompute a streamed qualification from original traces after releasing GPU."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from cc_contract.cli import canonical
from cc_contract.generators import qualification_corpus
from cc_contract.model import execute


def review(path):
    corpus=qualification_corpus(); counts=Counter(); raw=hashlib.sha256()
    identities=set(); scopes=set(); observations=0; summary=None
    with Path(path).open() as file:
        for line in file:
            if line.strip()=='{':
                summary=json.loads(line+file.read()); break
            record=json.loads(line)
            if record['record_type']!='qualification_case':
                raise ValueError('Unexpected qualification record')
            index=sum(counts.values())
            if record['case_index']!=index or record['scenario']!=corpus[index]:
                raise ValueError('Qualification corpus/order mismatch')
            raw.update(canonical(record)); identities.add(record['run_id'])
            scopes.add((record['scope'],record['gpu_executed']))
            verdict=record['verdict']; actual=record['observations']
            if verdict in ('PASS','FAIL'):
                expected=execute(record['scenario'])
                if len(actual)!=len(expected):raise ValueError('Observation count mismatch')
                failures=False
                for observed,reference in zip(actual,expected):
                    if observed['buffer']!=reference['buffer'] or observed['expected']!=reference['expected']:
                        raise ValueError('Reported reference contradicts independent model')
                    good=observed['observed']==reference['expected']
                    if observed['verdict']!=('PASS' if good else 'FAIL'):
                        raise ValueError('Observation verdict contradicts raw payload/generation')
                    failures |= not good
                if verdict!=('FAIL' if failures else 'PASS'):raise ValueError('Case verdict mismatch')
                observations+=len(actual)
            elif verdict not in ('UNSUPPORTED','INFRA_FAILURE') or actual or not record['reason']:
                raise ValueError('Invalid unsupported/infrastructure record')
            counts[verdict]+=1
    if summary is None or not summary['case_records_emitted']:
        raise ValueError('Missing detailed qualification summary')
    if identities!={summary['run_id']} or scopes!={(summary['scope'],summary['gpu_executed'])}:
        raise ValueError('Qualification identity/scope mismatch')
    if dict(counts)!=summary['counts'] or sum(counts.values())!=summary['cases'] or observations!=summary['observations']:
        raise ValueError('Qualification aggregate mismatch')
    if raw.hexdigest()!=summary['case_records_sha256']:
        raise ValueError('Qualification trace hash mismatch')
    expected_verdict='PASS' if counts['PASS']==96 else 'INCOMPLETE'
    if summary['verdict']!=expected_verdict:raise ValueError('Qualification summary verdict mismatch')
    return {'scope':summary['scope'],'gpu_executed':summary['gpu_executed'],'run_id':summary['run_id'],
            'verdict':expected_verdict,'cases':summary['cases'],'observations':observations,'counts':dict(counts),
            'independently_recomputed':True,'original_sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            'attestation_review':'SEPARATE_REQUIRED','confirmed_defects':[]}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('original',type=Path);args=parser.parse_args()
    result=review(args.original);print(json.dumps(result,indent=2))
    return 0 if result['verdict']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
