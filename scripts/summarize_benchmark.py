"""Summarize actual k6 reports, retaining failures rather than filtering them out."""
import hashlib
import json
from pathlib import Path

root=Path(__file__).resolve().parents[1]
rows=[]
for pattern in ['before20-*.json','after20-*.json','afterstats20-*.json','capacity*-*.json']:
    for path in sorted((root/'reports').glob(pattern)):
        report=json.loads(path.read_text(encoding='utf-8'))
        metrics=report['metrics']
        get=lambda name,key:metrics.get(name,{}).get('values',{}).get(key)
        rows.append({'file':path.name,'label':report['label'],'endpoint':report['target'],
            'vus':report['vus'],'duration':report['duration'],'think_seconds':report['think_seconds'],
            'requests':get('http_reqs','count'),'requests_per_second':get('http_reqs','rate'),
            'p95_ms':get('http_req_duration','p(95)'),'p99_ms':get('http_req_duration','p(99)'),
            'error_rate':get('http_req_failed','rate'),'checks_failed':get('checks','fails'),
            'new_submissions':get('submissions_created','count'),'replayed_submissions':get('submissions_replayed','count'),
            'thresholds_passed':all(t['ok'] for m in metrics.values() for t in m.get('thresholds',{}).values())})
result={'script_sha256':hashlib.sha256((root/'scripts/benchmark.js').read_bytes()).hexdigest(),'runs':rows}
(root/'reports/bench-summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('| 运行 | 目标 | VU | 请求数 | req/s | P95 ms | 错误率 | 断言失败 |')
print('| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |')
for row in rows:
    print(f"| {row['label']} | {row['endpoint']} | {row['vus']} | {row['requests']} | {row['requests_per_second']:.2f} | {row['p95_ms']:.2f} | {row['error_rate']:.2%} | {row['checks_failed']} |")
