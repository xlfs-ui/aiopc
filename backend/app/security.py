"""Request size, origin, host-independent rate and response protections."""
import asyncio
import time
from urllib.parse import urlsplit
from fastapi import HTTPException
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from app import config
from app.auth import enforce_rate, digest


class SecurityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not scope['path'].startswith('/api'):
            return await self.app(scope,receive,send)
        headers = {k.decode('latin-1').lower():v.decode('latin-1') for k,v in scope['headers']}
        async def protected_send(message):
            if message['type'] == 'http.response.start':
                values = list(message.get('headers',[]))
                values.extend([(b'cache-control',b'no-store'),(b'x-content-type-options',b'nosniff'),(b'x-frame-options',b'DENY'),(b'referrer-policy',b'same-origin'),(b'permissions-policy',b'camera=(), microphone=(), geolocation=()'),(b'content-security-policy',b"frame-ancestors 'none'; base-uri 'none'")])
                if config.PRODUCTION:
                    values.append((b'strict-transport-security',b'max-age=31536000; includeSubDomains'))
                message['headers'] = values
            await send(message)
        async def reject(code,detail,extra=None):
            await JSONResponse({'detail':detail},status_code=code,headers=extra)(scope,receive,protected_send)
        try:
            host = (scope.get('client') or ('unknown',0))[0]
            await run_in_threadpool(enforce_rate,'http:'+digest(host),240,60)
        except HTTPException as exc:
            return await reject(exc.status_code,exc.detail,exc.headers)
        if scope['method'] in ('POST','PUT','PATCH','DELETE'):
            max_body = 2*1024*1024 if scope['method']=='POST' and scope['path']=='/api/knowledge/documents' else 32768
            origin = headers.get('origin')
            referer = headers.get('referer')
            if origin and origin.rstrip('/') not in config.ALLOWED_ORIGINS:
                return await reject(403,'请求来源不被允许')
            if not origin and referer:
                parsed = urlsplit(referer)
                if f'{parsed.scheme}://{parsed.netloc}' not in config.ALLOWED_ORIGINS:
                    return await reject(403,'请求来源不被允许')
            if scope['method'] != 'DELETE' and headers.get('content-type','').split(';')[0].strip().lower() != 'application/json':
                return await reject(415,'请求须使用 JSON 格式')
            try:
                if int(headers.get('content-length','0')) > max_body:
                    return await reject(413,'请求内容过大')
            except ValueError:
                return await reject(400,'请求格式错误')
            body = bytearray()
            deadline = time.monotonic()+15
            while True:
                try:
                    message = await asyncio.wait_for(receive(),timeout=max(.01,deadline-time.monotonic()))
                except asyncio.TimeoutError:
                    return await reject(408,'请求读取超时')
                if message['type'] == 'http.disconnect':
                    return
                body.extend(message.get('body',b''))
                if len(body) > max_body:
                    return await reject(413,'请求内容过大')
                if not message.get('more_body',False):
                    break
            delivered = False
            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {'type':'http.request','body':bytes(body),'more_body':False}
                return await receive()
            return await self.app(scope,replay,protected_send)
        return await self.app(scope,receive,protected_send)
