"""Explicit Render deployment helper. Reads secrets only from ignored local files."""
import argparse
import json
import secrets
import sys
import urllib.error
import urllib.request
from pathlib import Path
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]
PRIVATE=ROOT/'deploy-private'
settings=dotenv_values(ROOT/'.env.deploy')
local=dotenv_values(ROOT/'.env')


def redact(value):
    text=json.dumps(value,ensure_ascii=True)
    admin=dotenv_values(PRIVATE/'administrator.env') if (PRIVATE/'administrator.env').exists() else {}
    for key,value in {**local,**settings,**admin}.items():
        if value and ('KEY' in key or 'PASSWORD' in key or key=='DATABASE_URL'):
            text=text.replace(value,'[REDACTED]')
    return text


def request(path,method='GET',body=None):
    req=urllib.request.Request('https://api.render.com/v1/'+path,
        headers={'Authorization':'Bearer '+settings['RENDER_API_KEY'],'Accept':'application/json','Content-Type':'application/json'},
        data=json.dumps(body).encode() if body is not None else None,method=method)
    try:
        with urllib.request.urlopen(req,timeout=30) as response:
            raw=response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        print('Render API HTTP',exc.code,redact(exc.read().decode(errors='replace')))
        raise SystemExit(1) from None


def create():
    existing=request('services?name=neighborhood-agent&limit=100')
    matching=[item['service'] for item in existing if item['service']['name']=='neighborhood-agent']
    if matching:
        if len(matching)!=1 or matching[0].get('repo','').rstrip('/').removesuffix('.git')!=settings['GITHUB_REPOSITORY'].rstrip('/').removesuffix('.git'):
            raise SystemExit('Existing service name belongs to another repository; inspect before creating')
        return {'service':matching[0],'reused':True}
    owners=request('owners?limit=100')
    if len(owners)!=1: raise SystemExit('Expected one Render workspace; choose a workspace explicitly')
    env={key:local[key] for key in ('DEEPSEEK_API_KEY','DEEPSEEK_BASE_URL','DEEPSEEK_MODEL','EMBEDDING_API_KEY','EMBEDDING_BASE_URL','EMBEDDING_MODEL','EMBEDDING_DIMENSIONS') if local.get(key)}
    for key in ('DEEPSEEK_API_KEY','EMBEDDING_API_KEY'):
        if not env.get(key): raise SystemExit('Missing local setting: '+key)
    env.update(APP_ENV='production',COOKIE_SECURE='true',DATABASE_URL=settings['DATABASE_URL'])
    PRIVATE.mkdir(exist_ok=True)
    account=PRIVATE/'administrator.env'
    if not account.exists():
        account.write_text('BOOTSTRAP_ADMIN_USERNAME=community_admin\nBOOTSTRAP_ADMIN_PASSWORD='+secrets.token_urlsafe(30)+'\n',encoding='utf-8')
    env.update({k:v for k,v in dotenv_values(account).items() if v})
    body={'type':'web_service','name':'neighborhood-agent','ownerId':owners[0]['owner']['id'],
          'repo':settings['GITHUB_REPOSITORY'],'branch':'main','autoDeployTrigger':'commit',
          'envVars':[{'key':key,'value':value} for key,value in env.items()],
          'serviceDetails':{'runtime':'docker','plan':'free','region':'ohio','numInstances':1,
                            'healthCheckPath':'/api/health','envSpecificDetails':{'dockerfilePath':'./Dockerfile','dockerContext':'.','dockerCommand':''}}}
    return request('services','POST',body)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['create','status','logs','deploy','remove-bootstrap'])
    args=parser.parse_args()
    PRIVATE.mkdir(exist_ok=True)
    state_path=PRIVATE/'render-state.json'
    if args.action=='create':
        result=create()
        state_path.write_text(json.dumps(result,indent=2),encoding='utf-8')
        service=result['service']
        print(redact({'id':service['id'],'url':service.get('serviceDetails',{}).get('url'),'deployId':result.get('deployId'),'reused':result.get('reused',False)}))
        return
    state=json.loads(state_path.read_text(encoding='utf-8'))
    service_id=state['service']['id']
    if args.action=='deploy':
        print(redact(request('services/'+service_id+'/deploys','POST',{})))
    elif args.action=='status':
        service=request('services/'+service_id)
        deploys=request('services/'+service_id+'/deploys?limit=3')
        print(redact({'id':service_id,'url':service.get('serviceDetails',{}).get('url'),'plan':service.get('serviceDetails',{}).get('plan'),'deploys':deploys}))
    elif args.action=='logs':
        from urllib.parse import urlencode
        owner=state['service']['ownerId']
        result=request('logs?'+urlencode({'ownerId':owner,'resource':service_id,'limit':80,'direction':'backward'}))
        print(redact({'hasMore':result.get('hasMore'),'logs':[{'at':row['timestamp'],'message':row['message']} for row in result.get('logs',[])]}))
    else:
        for key in ('BOOTSTRAP_ADMIN_USERNAME','BOOTSTRAP_ADMIN_PASSWORD'):
            request('services/'+service_id+'/env-vars/'+key,'DELETE')
        print('Bootstrap environment variables removed; database account retained.')


if __name__=='__main__':
    try: main()
    except urllib.error.URLError as exc:
        print('Network error:',type(exc.reason).__name__)
        sys.exit(2)
