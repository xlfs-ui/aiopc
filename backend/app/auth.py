"""Password authentication with opaque, revocable cookie sessions."""
import hashlib
import hmac
import secrets
import sqlite3
import time
from datetime import datetime
from threading import BoundedSemaphore
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app import captcha, config, storage

router = APIRouter(prefix='/api/auth', tags=['authentication'])
_hash_slots = BoundedSemaphore(2)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def enforce_rate(bucket: str, limit: int, seconds: int):
    now = int(time.time())
    with storage.connection(write=True) as db:
        db.execute('DELETE FROM rate_limits WHERE until_at<?', (now,))
        row = db.execute('SELECT count,until_at FROM rate_limits WHERE bucket=?', (bucket,)).fetchone()
        if row and row['count'] >= limit:
            raise HTTPException(429, '操作过于频繁，请稍后再试', headers={'Retry-After': str(max(1, row['until_at']-now))})
        if row:
            db.execute('UPDATE rate_limits SET count=count+1 WHERE bucket=?', (bucket,))
        else:
            db.execute('INSERT INTO rate_limits VALUES (?,?,?)', (bucket,1,now+seconds))


def client_key(request: Request) -> str:
    # Forwarded headers are not trusted here; configure the trusted proxy in Uvicorn.
    return digest(request.client.host if request.client else 'unknown')


def validate_password(password: str, username: str = ''):
    if len(password) < 12 or len(password) > 128 or password.isspace():
        raise ValueError('密码需为12–128个字符，建议使用多个词组成的长密码')
    if password.casefold() in {'password1234','123456789012','qwertyuiop12','abcdefghijkl'} or (len(username) >= 3 and username.casefold() in password.casefold()):
        raise ValueError('密码过于简单或包含账号，请换用更难猜的长密码')


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    with _hash_slots:
        value = hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=3, maxmem=64*1024*1024, dklen=32)
    return 'scrypt$32768$8$3$'+salt.hex()+'$'+value.hex()


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm,n,r,p,salt,expected = stored.split('$')
        if (algorithm,n,r,p) != ('scrypt','32768','8','3'):
            return False
        with _hash_slots:
            actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=32768, r=8, p=3, maxmem=64*1024*1024, dklen=32)
        return hmac.compare_digest(actual.hex(),expected)
    except (ValueError, TypeError):
        return False


_DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


class AuthModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class LoginPayload(AuthModel):
    username: str = Field(min_length=3, max_length=32, pattern=r'^[a-zA-Z][a-zA-Z0-9_]{2,31}$')
    password: str = Field(min_length=1, max_length=128)
    captcha_id: str = Field(min_length=32, max_length=64, pattern=r'^[a-zA-Z0-9_-]+$')
    captcha_code: str = Field(min_length=1, max_length=8)

    @field_validator('username')
    @classmethod
    def normalize_username(cls, value):
        return value.lower()


class RegisterPayload(LoginPayload):
    display_name: str = Field(min_length=1, max_length=30, pattern=r'^[\w\u3400-\u9fff ·.-]+$')
    password_confirm: str = Field(min_length=12, max_length=128)

    @model_validator(mode='after')
    def validate_registration(self):
        validate_password(self.password, self.username)
        if self.password != self.password_confirm:
            raise ValueError('两次输入的密码不一致')
        self.display_name = self.display_name.strip()
        if not self.display_name:
            raise ValueError('请填写称呼')
        return self


class PasswordPayload(AuthModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)
    password_confirm: str = Field(min_length=12, max_length=128)

    @model_validator(mode='after')
    def validate_change(self):
        validate_password(self.new_password)
        if self.new_password != self.password_confirm:
            raise ValueError('两次输入的密码不一致')
        return self


def public_user(row):
    return {key: row[key] for key in ('id','username','display_name','role','created_at')}


def get_user(user_id):
    with storage.connection() as db:
        row = db.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
    if not row:
        raise HTTPException(401, '登录已失效，请重新登录')
    return public_user(row)


def current_user(request: Request):
    token = request.cookies.get(config.COOKIE_NAME,'')
    if not token or len(token) > 128:
        raise HTTPException(401, '请先登录')
    with storage.connection() as db:
        row = db.execute('SELECT u.*,s.csrf_token,s.token_hash FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?',(digest(token),int(time.time()))).fetchone()
    if not row:
        raise HTTPException(401, '登录已过期，请重新登录')
    if request.method not in ('GET','HEAD','OPTIONS'):
        csrf = request.headers.get('x-csrf-token','')
        if not csrf or not hmac.compare_digest(csrf.encode(),row['csrf_token'].encode()):
            raise HTTPException(403, '请求校验失败，请刷新页面后重试')
    return {**public_user(row),'_csrf':row['csrf_token'],'_session_hash':row['token_hash']}


def require_admin(user=Depends(current_user)):
    if user['role'] != 'admin':
        raise HTTPException(403, '没有管理员权限')
    return user


def consume_captcha(request, captcha_id, code, purpose):
    now = int(time.time())
    with storage.connection(write=True) as db:
        row = db.execute('SELECT * FROM captcha WHERE id=?',(captcha_id,)).fetchone()
        db.execute('DELETE FROM captcha WHERE id=?',(captcha_id,))
    valid = row and row['expires_at'] > now and row['client_key'] == client_key(request) and row['purpose'] == purpose and hmac.compare_digest(row['answer_hash'],digest(captcha_id+code.strip().upper()))
    if not valid:
        raise HTTPException(400, '验证码错误或已过期，请刷新后重试')


def create_user(username, display_name, password, role='resident'):
    validate_password(password,username)
    encoded = hash_password(password)
    user = {'id':secrets.token_hex(16),'username':username.lower(),'display_name':display_name,'role':role,'created_at':datetime.now().isoformat(timespec='seconds')}
    try:
        with storage.connection(write=True) as db:
            db.execute('INSERT INTO users VALUES (?,?,?,?,?,?)',(user['id'],user['username'],display_name,encoded,role,user['created_at']))
            storage.audit(db,'创建账号',user['id'],user['id'])
    except sqlite3.IntegrityError:
        raise HTTPException(409, '该账号不可用，请换一个账号或前往登录') from None
    return {**user,'password_hash':encoded}


def issue_session(request, response, user, verified_hash=None):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    now = int(time.time())
    with storage.connection(write=True) as db:
        fresh=db.execute('SELECT * FROM users WHERE id=?',(user['id'],)).fetchone()
        if not fresh or (verified_hash and not hmac.compare_digest(fresh['password_hash'],verified_hash)):
            raise HTTPException(401,'登录信息已改变，请重新登录')
        user=public_user(fresh)
        db.execute('DELETE FROM sessions WHERE expires_at<=?',(now,))
        db.execute('DELETE FROM sessions WHERE token_hash=?',(digest(request.cookies.get(config.COOKIE_NAME,'')),))
        db.execute('DELETE FROM sessions WHERE token_hash IN (SELECT token_hash FROM sessions WHERE user_id=? ORDER BY expires_at DESC LIMIT -1 OFFSET 4)',(user['id'],))
        db.execute('INSERT INTO sessions VALUES (?,?,?,?)',(digest(token),user['id'],csrf,now+config.SESSION_SECONDS))
        storage.audit(db,'登录',user['id'],user['id'])
    response.set_cookie(config.COOKIE_NAME,token,max_age=config.SESSION_SECONDS,httponly=True,secure=config.SECURE_COOKIE,samesite='lax',path='/api')
    return {'user':public_user(user),'csrf_token':csrf}


@router.get('/captcha')
def get_captcha(request: Request, purpose: Literal['login','register'] = Query(default='login')):
    enforce_rate('captcha:'+client_key(request),40,600)
    enforce_rate('captcha-global',600,60)
    code,image = captcha.generate()
    identifier = secrets.token_urlsafe(24)
    now = int(time.time())
    with storage.connection(write=True) as db:
        db.execute('DELETE FROM captcha WHERE expires_at<=?',(now,))
        db.execute('INSERT INTO captcha VALUES (?,?,?,?,?)',(identifier,digest(identifier+code),client_key(request),purpose,now+180))
    return {'id':identifier,'image':image,'expires_in':180}


@router.post('/register', status_code=201)
def register(payload: RegisterPayload, request: Request, response: Response):
    enforce_rate('register:'+client_key(request),10,3600)
    consume_captcha(request,payload.captcha_id,payload.captcha_code,'register')
    enforce_rate('hash-global',120,60)
    user = create_user(payload.username,payload.display_name,payload.password)
    return issue_session(request,response,user,verified_hash=user['password_hash'])


@router.post('/login')
def login(payload: LoginPayload, request: Request, response: Response):
    enforce_rate('login-ip:'+client_key(request),30,900)
    consume_captcha(request,payload.captcha_id,payload.captcha_code,'login')
    enforce_rate('login-user:'+payload.username,10,900)
    enforce_rate('hash-global',120,60)
    with storage.connection() as db:
        row = db.execute('SELECT * FROM users WHERE username=?',(payload.username,)).fetchone()
    valid = verify_password(payload.password,row['password_hash'] if row else _DUMMY_HASH)
    if not row or not valid:
        raise HTTPException(401, '账号或密码错误')
    with storage.connection(write=True) as db:
        db.execute('DELETE FROM rate_limits WHERE bucket=?',('login-user:'+payload.username,))
    return issue_session(request,response,row,verified_hash=row['password_hash'])


@router.get('/me')
def me(user=Depends(current_user)):
    return {'user':public_user(user),'csrf_token':user['_csrf']}


@router.post('/logout')
def logout(response: Response, user=Depends(current_user)):
    with storage.connection(write=True) as db:
        db.execute('DELETE FROM sessions WHERE token_hash=?',(user['_session_hash'],))
        storage.audit(db,'退出登录',user['id'],user['id'])
    response.delete_cookie(config.COOKIE_NAME,path='/api',httponly=True,secure=config.SECURE_COOKIE,samesite='lax')
    return {'message':'已退出登录'}


@router.post('/password')
def change_password(payload: PasswordPayload, response: Response, user=Depends(current_user)):
    enforce_rate('password:'+user['id'],5,900)
    try:
        validate_password(payload.new_password,user['username'])
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from None
    with storage.connection() as db:
        stored = db.execute('SELECT password_hash FROM users WHERE id=?',(user['id'],)).fetchone()['password_hash']
    if not verify_password(payload.current_password,stored):
        raise HTTPException(400,'当前密码错误')
    if hmac.compare_digest(payload.current_password.encode(),payload.new_password.encode()):
        raise HTTPException(400,'新密码不能与当前密码相同')
    encoded = hash_password(payload.new_password)
    with storage.connection(write=True) as db:
        changed = db.execute('UPDATE users SET password_hash=? WHERE id=? AND password_hash=?',(encoded,user['id'],stored)).rowcount
        if not changed:
            raise HTTPException(409,'密码已发生变化，请重新登录')
        db.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],))
        storage.audit(db,'修改密码并注销会话',user['id'],user['id'])
    response.delete_cookie(config.COOKIE_NAME,path='/api',httponly=True,secure=config.SECURE_COOKIE,samesite='lax')
    return {'message':'密码已修改，请重新登录'}
