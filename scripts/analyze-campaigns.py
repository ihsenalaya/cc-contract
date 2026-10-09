"""Read immutable campaign evidence; independent blocks are statistical units."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
from collections import Counter


def wilson(successes, trials, z=1.959963984540054):
    if trials<=0 or not 0<=successes<=trials:
        raise ValueError('Invalid binomial counts')
    p=successes/trials; denominator=1+z*z/trials
    center=(p+z*z/(2*trials))/denominator
    radius=z*math.sqrt(p*(1-p)/trials+z*z/(4*trials*trials))/denominator
    return [max(0.,center-radius),min(1.,center+radius)]


def percentile(values, fraction):
    ordered=sorted(values); position=(len(ordered)-1)*fraction
    low=math.floor(position); high=math.ceil(position)
    return ordered[low]+(position-low)*(ordered[high]-ordered[low])


def paired_bootstrap(differences, seed=59001, draws=5000):
    if len(differences)<2:
        return None
    rng=random.Random(seed)
    samples=[statistics.fmean(rng.choices(differences,k=len(differences))) for _ in range(draws)]
    return [percentile(samples,.025),percentile(samples,.975)]


def mcnemar_exact(left, right):
    if len(left)!=len(right) or not left:
        raise ValueError('Paired binary outcomes required')
    a=sum(bool(x) and not y for x,y in zip(left,right))
    b=sum(bool(y) and not x for x,y in zip(left,right))
    n=a+b
    return min(1.,2*sum(math.comb(n,i) for i in range(min(a,b)+1))/2**n) if n else 1.


def holm(pvalues):
    order=sorted(pvalues,key=pvalues.get); adjusted={}; previous=0.
    for index,key in enumerate(order):
        previous=max(previous,min(1.,(len(order)-index)*pvalues[key]))
        adjusted[key]=previous
    return adjusted


def load_campaign(path):
    path=Path(path); manifest=json.loads(path.read_text())
    raw=path.parent/manifest['raw_file']
    if raw.parent.resolve()!=path.parent.resolve():
        raise ValueError('Raw evidence path escapes campaign')
    data=raw.read_bytes()
    if hashlib.sha256(data).hexdigest()!=manifest['raw_sha256']:
        raise ValueError('Raw integrity check failed')
    rows=[json.loads(line) for line in data.splitlines()]
    if len(rows)!=manifest['completed_cases'] or any(r['run_id']!=manifest['run_id'] for r in rows):
        raise ValueError('Campaign count/identity inconsistent')
    if any(r['scope']!=manifest['environment']['scope'] or r['gpu_executed']!=manifest['environment']['gpu_executed'] for r in rows):
        raise ValueError('Execution scope inconsistent')
    if dict(Counter(r['verdict'] for r in rows))!=manifest['counts']:
        raise ValueError('Verdict counts inconsistent')
    return manifest,rows


def reviewed_defects(path, campaigns):
    """Require two separate original failing replays; grouping remains reviewed."""
    if path is None:
        return {}
    index={m['run_id']:(m,rows) for m,rows in campaigns}; result={}
    documents=json.loads(Path(path).read_text())
    for review in documents:
        if review['review_state']!='CONFIRMED' or not review['rationale'] or not review['defect_id']:
            raise ValueError('Defect grouping requires explicit characterization rationale')
        manifest,rows=index[review['run_id']]; original=rows[review['case_index']]
        if original['verdict']!='FAIL' or not original['gpu_executed']:
            raise ValueError('Only a real failing GPU case can anchor defect review')
        if review['original_raw_sha256']!=manifest['raw_sha256']:
            raise ValueError('Review original evidence hash mismatch')
        seen={manifest['run_id']}
        replays=review['reproductions']
        if len(replays)<2:
            raise ValueError('Two fresh failing process runs required')
        for replay in replays:
            file=Path(path).parent/replay['manifest']
            if hashlib.sha256(file.read_bytes()).hexdigest()!=replay['manifest_sha256']:
                raise ValueError('Replay manifest hash mismatch')
            repeated,observations=load_campaign(file)
            case=observations[replay['case_index']]
            if repeated['run_id'] in seen or case['verdict']!='FAIL' or not case['gpu_executed']:
                raise ValueError('Replay is not a separate failing GPU run')
            seen.add(repeated['run_id'])
            if case['scenario']['operations']!=original['scenario']['operations']:
                raise ValueError('Replay did not execute the original operation sequence')
            if repeated['image_digest']!=manifest['image_digest'] or repeated['git_commit']!=manifest['git_commit']:
                raise ValueError('Replay changed the qualified execution implementation')
        result.setdefault(manifest['run_id'],{})[review['defect_id']]=min(
            original['elapsed_seconds'],result.get(manifest['run_id'],{}).get(review['defect_id'],math.inf))
    return result


def analyze(paths, reviews=None):
    campaigns=[load_campaign(p) for p in paths]
    scopes={m['environment']['scope'] for m,_ in campaigns}
    if len(scopes)!=1:
        raise ValueError('Never pool CPU and GPU execution scopes')
    reviewed=reviewed_defects(reviews,campaigns)
    keyed={}; excluded=[]
    rows=[]
    for manifest,raw in campaigns:
        config=manifest['configuration']; method=config['method']; block=config.get('block')
        # Unreviewed numerical FAILs are candidates, not confirmed defect counts.
        # External scientific review must version a separate analyzed manifest;
        # never rewrite this runner's original immutable manifests in place.
        if manifest.get('confirmed_defects',[]):
            raise ValueError('Review annotations must remain separate from immutable runner evidence')
        defects=reviewed.get(manifest['run_id'],{})
        row={'run_id':manifest['run_id'],'method':method,'block':block,
             'state':manifest['state'],'scope':manifest['environment']['scope'],
             'actual_seconds':manifest['actual_seconds'],'budget_seconds':config['budget_seconds'],
             'cases':len(raw),'candidate_failures':sum(r['verdict']=='FAIL' for r in raw),
             'invalid_proposals':sum(r['verdict']=='INVALID_TEST' for r in raw),
             'confirmed_defects':len(defects),'detected':bool(defects),'time_to_detection':min(defects.values()) if defects else None,
             'censored':not bool(defects),'structural_coverage':manifest['coverage']['structural'],
             'temporal_coverage':manifest['coverage']['temporal']}
        rows.append(row)
        if manifest['state']!='COMPLETE_BUDGET' or block is None:
            excluded.append({'run_id':manifest['run_id'],'reason':'incomplete_budget_or_pilot_without_block'})
            continue
        key=(block,method)
        if key in keyed:
            raise ValueError('Duplicate campaign for a paired block/method')
        keyed[key]=row
    if len({(m['image_digest'],m['git_commit'],json.dumps(m['family_support'],sort_keys=True),m['oracle_version']) for m,_ in campaigns})!=1:
        raise ValueError('Comparisons require common implementation, hardware support and oracle version')
    comparisons={}; pvalues={}
    for baseline in ('B1','B2','B3'):
        blocks=sorted({b for b,m in keyed if m=='B4'} & {b for b,m in keyed if m==baseline})
        if not blocks:
            continue
        pairs=[(keyed[(b,'B4')],keyed[(b,baseline)]) for b in blocks]
        if any(a['budget_seconds']!=b['budget_seconds'] for a,b in pairs):
            raise ValueError('Unequal within-block budgets')
        differences=[a['confirmed_defects']-b['confirmed_defects'] for a,b in pairs]
        p=mcnemar_exact([a['detected'] for a,b in pairs],[b['detected'] for a,b in pairs])
        pvalues[baseline]=p
        comparisons[baseline]={'independent_paired_blocks':len(pairs),
                              'mean_confirmed_defect_difference':statistics.fmean(differences),
                              'paired_bootstrap_95_ci':paired_bootstrap(differences),
                              'detection_probability_B4_95_ci':wilson(sum(a['detected'] for a,b in pairs),len(pairs)),
                              'detection_probability_baseline_95_ci':wilson(sum(b['detected'] for a,b in pairs),len(pairs)),
                              'mcnemar_two_sided_p':p,'superiority_established':False}
    for method,p in holm(pvalues).items():
        comparisons[method]['holm_adjusted_p']=p
    return {'scope':next(iter(scopes)) if scopes else 'NO_DATA','campaign_rows':rows,
            'excluded_from_confirmatory_comparison':excluded,'comparisons':comparisons,
            'confirmed_defect_review':'EXTERNAL_REVIEW_WITH_TWO_HASHED_REPLAYS' if reviews else 'NOT_PERFORMED',
            'claim':'NO_AUTOMATIC_SUPERIORITY_CLAIM',
            'statistical_unit':'independent_campaign_block','confidence':.95,
            'bootstrap':{'seed':59001,'draws':5000},'multiple_comparisons':'Holm across B4 versus B1/B2/B3',
            'nondetections':'right_censored_at_actual_campaign_end; never zero detection time',
            'raw_files_modified':False}


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('manifests',nargs='+',type=Path)
    parser.add_argument('--output',required=True,type=Path); parser.add_argument('--figures',action='store_true')
    parser.add_argument('--reviews',type=Path)
    args=parser.parse_args(); result=analyze(args.manifests,args.reviews); args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    with (args.output/'campaigns.csv').open('w',newline='') as file:
        rows=result['campaign_rows']; writer=csv.DictWriter(file,fieldnames=list(rows[0]) if rows else [])
        writer.writeheader(); writer.writerows(rows)
    (args.output/'inputs.json').write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in args.manifests},indent=2)+'\n')
    if args.figures:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        rows=result['campaign_rows']; methods=sorted({r['method'] for r in rows})
        fig,ax=plt.subplots(figsize=(7,4))
        for x,method in enumerate(methods):
            values=[r['temporal_coverage'] for r in rows if r['method']==method]
            ax.scatter([x]*len(values),values,label=method)
        ax.set_xticks(range(len(methods)),methods); ax.set_ylabel('Temporal software features covered')
        ax.set_title(result['scope']+' — coverage, not defect detection'); fig.tight_layout()
        fig.savefig(args.output/'temporal-coverage.svg'); fig.savefig(args.output/'temporal-coverage.png',dpi=180); plt.close(fig)
    print(json.dumps({'campaigns':len(result['campaign_rows']),'scope':result['scope'],'claim':result['claim']}))


if __name__=='__main__':
    main()
