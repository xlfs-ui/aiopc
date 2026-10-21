"""Serve only the built Vue directory; never expose source or database files."""
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

HEADERS={
    'Cache-Control':'no-store',
    'X-Content-Type-Options':'nosniff',
    'X-Frame-Options':'DENY',
    'Referrer-Policy':'same-origin',
    'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
}


def mount_frontend(app):
    root=(Path(__file__).resolve().parents[2]/'frontend'/'dist').resolve()
    if not (root/'index.html').is_file(): return
    if (root/'assets').is_dir(): app.mount('/assets',StaticFiles(directory=root/'assets'),name='frontend-assets')

    @app.get('/',include_in_schema=False)
    def index(): return FileResponse(root/'index.html',headers=HEADERS)

    @app.get('/{path:path}',include_in_schema=False)
    def public_file(path:str):
        # This app has no history-based frontend routes. Unknown /api, source,
        # dotfiles and traversal paths must return 404, never an SPA fallback.
        if path.startswith(('api/','assets/')) or any(part.startswith('.') for part in path.split('/')): raise HTTPException(404)
        file=(root/path).resolve()
        if not file.is_relative_to(root) or not file.is_file() or file.suffix.lower() not in {'.ico','.png','.svg','.webp','.txt'}: raise HTTPException(404)
        return FileResponse(file,headers=HEADERS)
