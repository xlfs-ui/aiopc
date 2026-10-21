"""Read-only OSV advisory lookup for the active Python environment."""
import importlib.metadata
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

packages=sorted({(d.metadata['Name'],d.version) for d in importlib.metadata.distributions()})
queries=[{'package':{'name':name,'ecosystem':'PyPI'},'version':version} for name,version in packages]
request=urllib.request.Request('https://api.osv.dev/v1/querybatch',data=json.dumps({'queries':queries}).encode(),headers={'Content-Type':'application/json'})
with urllib.request.urlopen(request,timeout=30) as response:
    results=json.load(response)['results']
findings=[]
for (name,version),result in zip(packages,results):
    ids=[v['id'] for v in result.get('vulns',[])]
    if ids: findings.append({'package':name,'version':version,'advisories':ids})
report={'checked_at':datetime.now(timezone.utc).isoformat(),'source':'https://osv.dev/','packages_checked':len(packages),'findings':findings}
target=Path(__file__).resolve().parents[1]/'docs'/'python-advisory-audit.json'
target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
