"""One-time administrator provisioning from private deployment environment."""
import os
from fastapi import HTTPException
from app import storage


def bootstrap_admin():
    username=os.getenv('BOOTSTRAP_ADMIN_USERNAME','').strip().lower()
    password=os.getenv('BOOTSTRAP_ADMIN_PASSWORD','')
    if not username and not password: return
    if not username or not password: raise RuntimeError('Both bootstrap administrator variables are required')
    import re
    if not re.fullmatch(r'[a-z][a-z0-9_]{2,31}',username): raise RuntimeError('Invalid bootstrap administrator username')
    with storage.connection() as db:
        existing=db.execute('SELECT role FROM users WHERE username=?',(username,)).fetchone()
    if existing:
        if existing['role']!='admin': raise RuntimeError('Bootstrap account exists and is not an administrator')
        return
    from app.auth import create_user
    try: create_user(username,'社区管理员',password,role='admin')
    except HTTPException as exc:
        if exc.status_code!=409: raise
        with storage.connection() as db:
            existing=db.execute('SELECT role FROM users WHERE username=?',(username,)).fetchone()
        if not existing or existing['role']!='admin': raise RuntimeError('Administrator provisioning conflict') from None
    # Existing accounts are never promoted or reset on restart. Remove the
    # bootstrap secret in Render once the first deployment succeeds.
