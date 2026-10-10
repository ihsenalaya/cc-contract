"""Render public tables and a figure from a previously verified complete audit.

CPU only: no cloud or GPU operations. This formatter does not replace raw-case
recomputation, fresh Azure power readback or private remote-backup verification.
Matplotlib is needed for the exported figure; its version is recorded.
"""
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import argparse, csv, hashlib, json, statistics

REPO = Path(__file__).resolve().parents[1]
PRIVATE = None
METHODS = ['B1', 'B2', 'B3', 'B4', 'A_NO_STATE', 'A_NO_DIVERSITY', 'A_NO_VALIDITY_GUIDANCE']

def require(condition, message):
    if not condition:
        raise ValueError(message)


def load(name):
    return json.loads((PRIVATE / name).read_bytes())

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024**2), b''):
            h.update(chunk)
    return h.hexdigest()

def dump(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')

def table(path, rows):
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

def main(argv=None):
    global REPO, PRIVATE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign-directory', type=Path, required=True,
                        help='Private completed collection, raw audit, host review and verified Azure backup proofs')
    parser.add_argument('--repo-root', type=Path, default=REPO,
                        help='Repository containing the public results and docs directories')
    args = parser.parse_args(argv)
    PRIVATE = args.campaign_directory.resolve()
    REPO = args.repo_root.resolve()
    audit = load('independent-fixed-work-audit-parallel.json')
    parallel = load('independent-fixed-work-audit-parallel-parallel-receipt.json')
    host = load('independent-host-review/independent-fixed-work-host-review.json')
    backup = load('private-azure-originals-backup-summary.json')
    off = load('root-independent-post-run-deallocation.json')
    collection, release, run = load('collection.json'), load('release.json'), load('run-exit.json')
    require(audit['state'] == 'PASS_COMPLETE_FIXED_WORK_GPU_AUDIT', 'Public formatting requires complete consistent verified GPU audit and lifecycle/backup proofs')
    require(audit['audited_jobs'] == 140 and audit['audited_selected_cases'] == 14000, 'Public formatting requires complete consistent verified GPU audit and lifecycle/backup proofs')
    require(audit['audited_candidate_draws'] == 164000 and audit['full_gpu_quota_matrix'], 'Public formatting requires complete consistent verified GPU audit and lifecycle/backup proofs')
    require(audit['all_case_traces_independently_recomputed'] and audit['original_host_hash_manifest_verified'], 'Public formatting requires complete consistent verified GPU audit and lifecycle/backup proofs')
    require(audit['candidate_failures'] == audit['unresolved_candidate_failures'] == 0, 'Public formatting requires complete consistent verified GPU audit and lifecycle/backup proofs')
    require(parallel['state'] == 'VERIFIED_COMPOSED_OFFLINE_CPU_AUDIT', 'Public formatting requires complete consistent verified GPU audit and lifecycle/backup proofs')
    require(parallel['result_sha256'] == sha(PRIVATE/'independent-fixed-work-audit-parallel.json'), 'Public formatting requires complete consistent verified GPU audit and lifecycle/backup proofs')
    require(host['state'] == 'PASS_BOUNDED_HOST_AND_IR_QUALIFICATION_REVIEW', 'Public formatting requires complete consistent verified GPU audit and lifecycle/backup proofs')
    require(host['original_archive_bytes_unchanged'] and not host['GPU_quote_or_local_HMAC_independently_authenticated'], 'Public formatting requires complete consistent verified GPU audit and lifecycle/backup proofs')
    require(backup['state'] == 'PASS_PRIVATE_GPU_ORIGINALS_AZURE_FULL_GET_BACKUP', 'Public formatting requires complete consistent verified GPU audit and lifecycle/backup proofs')
    require(backup['remote_full_GET_SHA256_and_length_verified'], 'Public formatting requires complete consistent verified GPU audit and lifecycle/backup proofs')
    require(off['state'] == 'PASS_FRESH_AZURE_DEALLOCATED_RETAINED_IDENTITY', 'Public formatting requires complete consistent verified GPU audit and lifecycle/backup proofs')
    require(release['power_state'] == 'PowerState/deallocated' and run['deallocation_verified'], 'Public formatting requires complete consistent verified GPU audit and lifecycle/backup proofs')
    require(audit['original_archive_sha256'] == host['original_archive_sha256'] == backup['archive_sha256'] == collection['archive_sha256'], 'Public formatting requires complete consistent verified GPU audit and lifecycle/backup proofs')
    rows = audit['job_rows']
    require(len(rows) == 140 and {(r['block'], r['method']) for r in rows} == {(b,m) for b in range(20) for m in METHODS}, 'Public formatting requires complete consistent verified GPU audit and lifecycle/backup proofs')
    counts = Counter()
    for row in rows:
        counts.update(row['counts'])
    require(sum(counts.values()) == 14000 and not any(counts[v] for v in ['FAIL', 'UNSUPPORTED', 'INFRA_FAILURE']), 'Public formatting requires complete consistent verified GPU audit and lifecycle/backup proofs')
    require(sum(r['actual_job_seconds'] for r in rows) == audit['whole_job_seconds'], 'Public formatting requires complete consistent verified GPU audit and lifecycle/backup proofs')

    tables = REPO/'docs/environment/fixed-work-campaign-tables'
    tables.mkdir(exist_ok=True)
    method_rows = []
    for method in METHODS:
        group = [r for r in rows if r['method'] == method]
        c = Counter()
        for r in group: c.update(r['counts'])
        summary = audit['summaries']['by_method'][method]
        method_rows.append(dict(method=method, independent_blocks=20, selected_cases=2000,
            PASS=c['PASS'], INVALID_TEST=c['INVALID_TEST'], FAIL=c['FAIL'],
            candidate_draws=summary['candidate_draws'], observations=sum(r['observations'] for r in group),
            mean_job_seconds=summary['mean_actual_job_seconds'], total_job_seconds=sum(r['actual_job_seconds'] for r in group),
            min_job_seconds=min(r['actual_job_seconds'] for r in group), max_job_seconds=max(r['actual_job_seconds'] for r in group),
            mean_valid_selected_fraction=summary['mean_valid_selected_fraction'],
            mean_structural_software_coverage=summary['mean_structural_coverage'],
            mean_temporal_software_coverage=summary['mean_temporal_coverage'],
            confirmed_defects=0, detecting_jobs=0,
            detection_probability_wilson95_lower=summary['detection_probability_95_wilson'][0],
            detection_probability_wilson95_upper=summary['detection_probability_95_wilson'][1]))
    table(tables/'methods.csv', method_rows)
    job_rows = []
    for i, r in enumerate(rows):
        job_rows.append(dict(job_index=i, block=r['block'], method=r['method'], seed=r['seed'],
            selected_cases=r['selected_cases'], original_campaign_state=r['original_campaign_state'], gpu_executed=r['gpu_executed'], scope=r['scope'], fixed_work_complete=r['fixed_work_complete'], PASS=r['counts'].get('PASS',0), INVALID_TEST=r['counts'].get('INVALID_TEST',0),
            candidate_draws=r['candidate_draws'], observations=r['observations'], raw_bytes=r['raw_bytes'],
            job_seconds=r['actual_job_seconds'], campaign_seconds=r['actual_campaign_seconds'],
            structural_software_coverage=r['coverage']['structural'], temporal_software_coverage=r['coverage']['temporal'],
            confirmed_defects=r['confirmed_defects'], time_to_detection='', right_censored=r['censored'], raw_sha256=r['raw_sha256']))
    table(tables/'jobs.csv', job_rows)
    paired = []
    for baseline, comparison in audit['summaries']['paired_comparisons'].items():
        for metric, values in comparison['metrics'].items():
            low, high = values['paired_block_bootstrap_95_percentile_ci']
            paired.append(dict(baseline=baseline, family=comparison['family'], metric=metric, independent_paired_blocks=20,
                mean_difference_B4_minus_baseline=values['mean_paired_difference_B4_minus_baseline'],
                bootstrap95_lower=low, bootstrap95_upper=high,
                detection_mcnemar_p=comparison.get('mcnemar_two_sided_p','') if metric=='detection_probability' else '',
                detection_holm_p=comparison.get('holm_adjusted_primary_detection_p','') if metric=='detection_probability' else ''))
    table(tables/'paired-comparisons.csv', paired)

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    matplotlib.rcParams['svg.hashsalt'] = 'cc-contract-fixed-work-1010a'
    fig, ax = plt.subplots(figsize=(10,4.5), constrained_layout=True)
    ax.boxplot([[r['actual_job_seconds'] for r in rows if r['method']==m] for m in METHODS], showmeans=True)
    ax.set_xticks(range(1, len(METHODS) + 1))
    ax.set_xticklabels(['B1','B2','B3','B4','No state','No diversity','No validity\nguidance'])
    ax.set_ylabel('Whole-job time (seconds)')
    ax.set_title('H100: 20 jobs per method, 100 selected cases per job')
    ax.grid(axis='y', alpha=.25)
    fig.savefig(tables/'job-times.svg', metadata={'Date':None,'Creator':'CC-Contract offline result aggregation'})
    svg = tables/'job-times.svg'
    svg.write_text(''.join(line.rstrip() + '\n' for line in svg.read_text().splitlines()))
    plt.close(fig)

    manifest = {k:v for k,v in audit.items() if k not in ('job_rows',)}
    manifest.update(timestamp_utc=datetime.now(timezone.utc).isoformat(), campaign_id='fixed-work-1010a',
        state='COMPLETED_AND_INDEPENDENTLY_AUDITED_FIXED_WORK_GPU_CAMPAIGN', scope='BOUNDED_T01_T08_EXACT_INTEGER_FIXED_WORK_V0_3',
        selected_cases_per_job=100, independent_blocks=20, parallel_gpu_jobs=False, counts=dict(counts),
        actual_gpu_jobs_run=140, development_pilots_pooled=False, CPU_qualification_results_pooled=False,
        private_raw_archive=dict(sha256=collection['archive_sha256'], bytes=(PRIVATE/collection['archive_file']).stat().st_size,
            original_files_verified=collection['files_verified'], private_Azure_full_GET_SHA256_and_length_verified=True),
        evidence_sha256={n:sha(PRIVATE/n) for n in ('collection.json','release.json','run-exit.json',
            'root-independent-post-run-deallocation.json','independent-fixed-work-audit-parallel.json',
            'independent-fixed-work-audit-parallel-parallel-receipt.json',
            'independent-host-review/independent-fixed-work-host-review.json','private-azure-originals-backup-summary.json')},
        timings=dict(whole_gpu_job_seconds=audit['whole_job_seconds'], campaign_seconds=audit['actual_total_seconds'],
            current_start_request_to_confirmed_deallocation_seconds=off['current_start_request_to_confirmed_deallocation_seconds'],
            prior_failed_start_request_to_deallocation_seconds=off['prior_failed_start_request_to_deallocation_seconds'],
            cumulative_conservative_start_request_to_deallocation_seconds=off['cumulative_conservative_start_request_to_deallocation_seconds'],
            offline_CPU_audit_seconds=parallel['elapsed_seconds'], offline_CPU_host_review_seconds=host['actual_review_seconds_including_hashes_extraction_and_cert_fetch'],
            local_audit_time_included_in_H100_duration=False, actual_billing_start_and_cost_established=False),
        deallocation=dict(power_state='PowerState/deallocated', confirmed_utc=release['timestamp_utc'], independent_live_readback_verified=True,
            same_VM_and_disk_retained=True, managed_resources_retained=13, resources_destroyed=0),
        tables={str(f.relative_to(REPO)):sha(f) for f in sorted(tables.iterdir()) if f.is_file()},
        host_qualification_state=host['state'], independent_GPU_hardware_quote_verified=False,
        full_E0_E8_complete=False, full_E0_E8_H100_duration_established=False,
        plotting_library_version=matplotlib.__version__, public_formatter_sha256=sha(Path(__file__)))
    dump(REPO/'results/manifests/fixed-work-campaign-gpu-result.json', manifest)

    lines = ['# Fixed-work H100 campaign result — 10 October 2026', '',
        f'All **140 successive jobs × 100 selected cases** completed and passed independent raw-case recomputation: '
        f'**{counts["PASS"]:,} PASS**, **{counts["INVALID_TEST"]:,} INVALID_TEST**, and **zero FAIL, unsupported or infrastructure failures**. '
        'Invalid selected cases consumed quota and were rejected before CUDA.', '',
        'This completes the frozen v0.3 bounded E4/E5 matrix, with 20 paired independent blocks and seven methods. '
        'The statistical unit is a paired block; the 14,000 selected cases and 164,000 candidate draws are not independent statistical replicates. '
        'Development pilots and Kind CPU qualification are excluded. Fixed selected quotas do not equalize candidate-generation cost, valid CUDA executions, byte volume or wall time.', '',
        '| Method | Jobs | PASS | INVALID_TEST | Candidate draws | Mean job (s) | Total jobs (min) |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for row in method_rows:
        lines.append(f'| {row["method"]} | 20 | {row["PASS"]} | {row["INVALID_TEST"]} | {row["candidate_draws"]} | {row["mean_job_seconds"]:.3f} | {row["total_job_seconds"]/60:.3f} |')
    lines += ['', f'The sum of whole-job intervals is **{audit["whole_job_seconds"]/60:.3f} minutes**; '
        f'the campaign interval is {audit["actual_total_seconds"]/60:.3f} minutes. '
        f'Current start request to confirmed deallocation is **{off["current_start_request_to_confirmed_deallocation_seconds"]/60:.3f} minutes**. '
        f'Including the failed zero-work startup, cumulative conservative VM duration is **{off["cumulative_conservative_start_request_to_deallocation_seconds"]/60:.3f} minutes**, within the approved 90-minute allowance. '
        'These measured intervals do not establish actual billing start or invoice charges.', '',
        'The H100 is deallocated; the same VM, OS disk and thirteen managed resources remain. '
        f'Independent CPU review took {parallel["elapsed_seconds"]/60:.3f} minutes after deallocation. '
        'It required no additional H100 execution.', '',
        '![Observed whole-job durations](fixed-work-campaign-tables/job-times.svg)', '',
        'Zero candidate failures means zero confirmed defects in this bounded study. It does not prove defect absence, '
        'absolute hardware correctness, adequate statistical power or superiority of B4. '
        'The predeclared paired bootstrap uses 5,000 block resamples and seed 59001; '
        'primary detection comparisons use exact paired McNemar tests and Holm adjustment. '
        'With no detected defects in any method, each primary detection p-value and its adjustment are 1. '
        'All-zero primary outcomes yield degenerate bootstrap differences; this does not establish equivalence or adequate power. '
        'Nondetection times remain null and right-censored, never zero seconds. '
        'Software coverage and timing are secondary descriptive outcomes.', '',
        'The independent host review passed the pinned kernel/driver, CC production, Secure Boot, '
        'CPU MAA RS256 signature/VM claims, CUDA references and the 96-case IR qualification. '
        'GPU hardware quote/remote-token authentication remains independently unverified; full E0–E8 is not complete.', '',
        f'The private original archive contains {collection["files_verified"]} hash-verified files and '
        f'{(PRIVATE/collection["archive_file"]).stat().st_size:,} compressed bytes. Its Azure copy was fully read back '
        'and matched SHA-256 and length; local originals remain preserved. Raw attestation tokens, credentials '
        'and case payloads are excluded from public Git.', '',
        '[Result manifest](../../results/manifests/fixed-work-campaign-gpu-result.json) · '
        '[Method table](fixed-work-campaign-tables/methods.csv) · '
        '[140 job rows](fixed-work-campaign-tables/jobs.csv) · '
        '[Paired comparisons](fixed-work-campaign-tables/paired-comparisons.csv) · '
        '[Offline reproduction](../reproducibility/fixed-work-offline-audit.md) · '
        '[Remaining H100 work](remaining-h100-experiments.md)', '']
    (REPO/'docs/environment/fixed-work-campaign-result.md').write_text('\n'.join(lines))
    print(json.dumps({'state':manifest['state'],'counts':dict(counts),'whole_job_seconds':audit['whole_job_seconds'],
        'actual_campaign_seconds':audit['actual_total_seconds'],'CPU_audit_seconds':parallel['elapsed_seconds']}))


if __name__ == "__main__":
    main()
