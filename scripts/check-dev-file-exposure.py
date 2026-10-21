"""HEAD-only regression check: never downloads database or secret contents."""
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

root=Path(__file__).resolve().parents[1].as_posix()
base='http://127.0.0.1:5173'


def status(path):
    request=urllib.request.Request(base+path,method='HEAD')
    try:
        with urllib.request.urlopen(request,timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


for relative in ['backend/data/community.db','.env','backend/app/auth.py']:
    for query in ['', '?raw', '?url', '?import']:
        path='/@fs/'+urllib.parse.quote(root+'/'+relative,safe='/:')+query
        code=status(path)
        if code not in (403,404):
            raise SystemExit(f'FAIL: protected file reachable: {relative}{query} (HTTP {code})')
        print(f'Blocked {relative}{query}: {code}')
if status('/src/main.ts')!=200:
    raise SystemExit('FAIL: frontend entry point is unavailable')
print('PASS: protected files blocked; frontend resources available')
