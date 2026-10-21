"""Production entry point. Render provides PORT and its external HTTPS URL."""
import os
import sys
from pathlib import Path

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'backend'))
os.chdir(root)

if __name__=='__main__':
    import uvicorn
    # Never trust arbitrary X-Forwarded-For. Hosting environments can supply a
    # restricted proxy allowlist explicitly; app origin checks use PUBLIC_URL.
    proxies=os.getenv('FORWARDED_ALLOW_IPS','').strip()
    uvicorn.run('app.main:app',host='0.0.0.0',port=int(os.getenv('PORT','10000')),workers=1,proxy_headers=bool(proxies),forwarded_allow_ips=proxies or '127.0.0.1',access_log=False)
