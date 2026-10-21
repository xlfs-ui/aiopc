import os
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / '.env')
PRODUCTION = os.getenv('APP_ENV', 'development') == 'production'
SECURE_COOKIE = os.getenv('COOKIE_SECURE', 'true' if PRODUCTION else 'false').lower() == 'true'
PUBLIC_URL=(os.getenv('PUBLIC_URL','').strip() or os.getenv('RENDER_EXTERNAL_URL','').strip()).rstrip('/')
default_origins=PUBLIC_URL if PRODUCTION and PUBLIC_URL else 'http://localhost:5173,http://127.0.0.1:5173'
ALLOWED_ORIGINS = [s.strip().rstrip('/') for s in os.getenv('ALLOWED_ORIGINS', default_origins).split(',') if s.strip()]
for origin in ALLOWED_ORIGINS:
    parsed = urlsplit(origin)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username or '*' in origin:
        raise RuntimeError('ALLOWED_ORIGINS must contain explicit HTTP(S) origins')
if PRODUCTION and (not SECURE_COOKIE or any(not o.startswith('https://') for o in ALLOWED_ORIGINS)):
    raise RuntimeError('Production requires COOKIE_SECURE=true and HTTPS origins')
default_hosts='localhost,127.0.0.1'+(','+urlsplit(PUBLIC_URL).hostname if PUBLIC_URL and urlsplit(PUBLIC_URL).hostname else '')+('' if PRODUCTION else ',testserver')
TRUSTED_HOSTS = [s.strip() for s in os.getenv('TRUSTED_HOSTS', default_hosts).split(',') if s.strip()]
if PRODUCTION and os.getenv('RENDER') and not os.getenv('DATABASE_URL','').strip():
    raise RuntimeError('Render production requires DATABASE_URL: ephemeral SQLite is disabled')
SESSION_SECONDS = 8 * 60 * 60
COOKIE_NAME = 'community_session'
