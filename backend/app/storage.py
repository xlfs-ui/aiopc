"""SQLite transactions for business data, identities and sessions."""
import json
import sqlite3
import time
import hashlib
import copy
import os
from fastapi import HTTPException
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import RLock
from app import config

DB_PATH = Path(os.getenv('SQLITE_PATH',str(Path(__file__).resolve().parents[1] / 'data' / 'community.db'))).resolve()
_lock = RLock()
_initialized = set()
# SQL identifiers below are fixed application constants, never request input.
BUSINESS = {
    'policies': {'id':'TEXT PRIMARY KEY','title':'TEXT NOT NULL','category':'TEXT NOT NULL','summary':'TEXT NOT NULL','steps':'TEXT NOT NULL','source':'TEXT NOT NULL','source_url':"TEXT NOT NULL DEFAULT ''",'phone':'TEXT NOT NULL DEFAULT \'\'','keywords':'TEXT NOT NULL','updated_at':'TEXT NOT NULL'},
    'activities': {'id':'TEXT PRIMARY KEY','title':'TEXT NOT NULL','category':'TEXT NOT NULL','date':'TEXT NOT NULL','time':'TEXT NOT NULL','location':'TEXT NOT NULL','capacity':'INTEGER NOT NULL','registered':'INTEGER NOT NULL DEFAULT 0','audience':'TEXT NOT NULL','description':'TEXT NOT NULL','tag':'TEXT NOT NULL'},
    'tickets': {'id':'TEXT PRIMARY KEY','owner_id':'TEXT','resident':'TEXT NOT NULL','phone':'TEXT NOT NULL DEFAULT \'\'','location':'TEXT NOT NULL','category':'TEXT NOT NULL','description':'TEXT NOT NULL','status':'TEXT NOT NULL','assignee':'TEXT NOT NULL','created_at':'TEXT NOT NULL','updated_at':'TEXT NOT NULL','priority':'TEXT NOT NULL DEFAULT \'普通\'','assigned_staff_id':"TEXT NOT NULL DEFAULT ''",'resolution':"TEXT NOT NULL DEFAULT ''",'due_at':"TEXT NOT NULL DEFAULT ''",'version':'INTEGER NOT NULL DEFAULT 0'},
    'registrations': {'id':'TEXT PRIMARY KEY','activity_id':'TEXT NOT NULL REFERENCES activities(id)','owner_id':'TEXT','resident':'TEXT NOT NULL','created_at':'TEXT NOT NULL'},
}
SCHEMA = [
    'CREATE TABLE IF NOT EXISTS snapshots (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, action TEXT, resource_id TEXT, actor TEXT, created_at TEXT)',
    "CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('resident','admin')), created_at TEXT NOT NULL)",
    'CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, csrf_token TEXT NOT NULL, expires_at INTEGER NOT NULL)',
    'CREATE INDEX IF NOT EXISTS session_user ON sessions(user_id)',
    'CREATE TABLE IF NOT EXISTS captcha (id TEXT PRIMARY KEY, answer_hash TEXT NOT NULL, client_key TEXT NOT NULL, purpose TEXT NOT NULL, expires_at INTEGER NOT NULL)',
    'CREATE TABLE IF NOT EXISTS rate_limits (bucket TEXT PRIMARY KEY, count INTEGER NOT NULL, until_at INTEGER NOT NULL)',
    'CREATE TABLE IF NOT EXISTS idempotency (owner_id TEXT NOT NULL, key TEXT NOT NULL, digest TEXT NOT NULL, response TEXT NOT NULL, created_at INTEGER NOT NULL, PRIMARY KEY(owner_id,key))',
    "CREATE TABLE IF NOT EXISTS chat_threads (owner_id TEXT NOT NULL, thread_id TEXT NOT NULL, messages TEXT NOT NULL DEFAULT '[]', turns INTEGER NOT NULL DEFAULT 0, locked_until INTEGER NOT NULL DEFAULT 0, updated_at INTEGER NOT NULL, PRIMARY KEY(owner_id,thread_id))",
    "CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, document_key TEXT NOT NULL, version INTEGER NOT NULL, title TEXT NOT NULL, source TEXT NOT NULL, source_url TEXT NOT NULL DEFAULT '', filename TEXT NOT NULL, content_hash TEXT NOT NULL, content TEXT NOT NULL, original BLOB, status TEXT NOT NULL CHECK(status IN ('draft','published','archived')), effective_on TEXT NOT NULL DEFAULT '', expires_on TEXT NOT NULL DEFAULT '', created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(document_key,version))",
    'CREATE TABLE IF NOT EXISTS document_chunks (id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE, ordinal INTEGER NOT NULL, page INTEGER, content TEXT NOT NULL, start_offset INTEGER NOT NULL, end_offset INTEGER NOT NULL, UNIQUE(document_id,ordinal))',
    'CREATE TABLE IF NOT EXISTS retrieval_chunks (id TEXT PRIMARY KEY, kind TEXT NOT NULL, resource_id TEXT NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL, metadata TEXT NOT NULL, fingerprint TEXT NOT NULL)',
    "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(chunk_id UNINDEXED, title_tokens, body_tokens, tokenize='unicode61')",
    'CREATE TABLE IF NOT EXISTS chunk_vectors (chunk_id TEXT PRIMARY KEY REFERENCES retrieval_chunks(id) ON DELETE CASCADE, provider TEXT NOT NULL, fingerprint TEXT NOT NULL, dimensions INTEGER NOT NULL, vector TEXT NOT NULL)',
    'CREATE INDEX IF NOT EXISTS chunks_document ON document_chunks(document_id)',
    'CREATE INDEX IF NOT EXISTS retrieval_resource ON retrieval_chunks(kind,resource_id)',
    'CREATE INDEX IF NOT EXISTS document_status ON documents(status,effective_on,expires_on)',
    'CREATE INDEX IF NOT EXISTS audit_resource ON audit(resource_id,id)',
]


def _key(table, row, index=0):
    if table != 'registrations': return row['id']
    if row.get('owner_id'): return row['activity_id'] + ':' + row['owner_id']
    return row.get('id') or 'legacy:' + hashlib.sha256((json.dumps(row,sort_keys=True,ensure_ascii=False)+str(index)).encode()).hexdigest()


def _upsert(db, table, row, position):
    fields=list(BUSINESS[table])+['_position']
    values=[]
    for field in fields:
        value=position if field=='_position' else _key(table,row,position) if field=='id' else row.get(field, None if field=='owner_id' else 0 if field=='version' else '普通' if field=='priority' else '')
        if field in ('steps','keywords'): value=json.dumps(value,ensure_ascii=False)
        values.append(value)
    updates=','.join(f'{field}=excluded.{field}' for field in fields if field!='id')
    db.execute(f"INSERT INTO {table} ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)}) ON CONFLICT(id) DO UPDATE SET {updates}",values)


def _read_business(db, tables=None):
    result={}
    for table in (tables or BUSINESS):
        rows=[]
        for record in db.execute(f'SELECT * FROM {table} ORDER BY _position,id'):
            row=dict(record); row.pop('_position')
            if table=='policies':
                row['steps']=json.loads(row['steps']); row['keywords']=json.loads(row['keywords'])
            rows.append(row)
        result[table]=rows
    return result


def _initialize(db):
    path=str(DB_PATH.resolve())
    if path in _initialized: return
    with _lock:
        if path in _initialized: return
        version=db.execute('PRAGMA user_version').fetchone()[0]
        if version>5: raise RuntimeError('Database schema is newer than this application')
        if version<2 and db.execute("SELECT 1 FROM sqlite_master WHERE name='snapshots'").fetchone():
            backup=DB_PATH.with_name(DB_PATH.stem+'.pre-v2.'+datetime.now().strftime('%Y%m%d%H%M%S%f')+'.db')
            destination=sqlite3.connect(backup)
            try: db.backup(destination)
            finally: destination.close()
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('BEGIN IMMEDIATE')
        try:
            # Recheck after obtaining the cross-process migration lock.
            version=db.execute('PRAGMA user_version').fetchone()[0]
            for statement in SCHEMA: db.execute(statement)
            for table,columns in BUSINESS.items():
                db.execute(f"CREATE TABLE IF NOT EXISTS {table} ({','.join(name+' '+definition for name,definition in columns.items())}, _position INTEGER NOT NULL DEFAULT 0)")
            db.execute('CREATE INDEX IF NOT EXISTS ticket_owner ON tickets(owner_id,created_at)')
            db.execute('CREATE INDEX IF NOT EXISTS ticket_status ON tickets(status,created_at)')
            db.execute('CREATE UNIQUE INDEX IF NOT EXISTS registration_owner ON registrations(activity_id,owner_id) WHERE owner_id IS NOT NULL')
            if version<2:
                legacy=db.execute('SELECT payload FROM snapshots WHERE id=1').fetchone()
                if legacy:
                    data=json.loads(legacy[0])
                    for table in BUSINESS:
                        for index,row in enumerate(data.get(table,[])): _upsert(db,table,row,index)
                    from app.retrieval import index_policy
                    for policy in data.get('policies',[]): index_policy(db,policy)
                    db.execute("INSERT OR IGNORE INTO snapshots(id,payload) VALUES (2,'migrated-to-relational-tables')")
                db.execute('PRAGMA user_version=2')
            if version<3:
                from app.civic import SCHEMA as civic_schema
                for statement in civic_schema: db.execute(statement)
                db.execute('PRAGMA user_version=3')
            if version<4:
                if 'source_url' not in {row[1] for row in db.execute('PRAGMA table_info(policies)')}:
                    db.execute("ALTER TABLE policies ADD COLUMN source_url TEXT NOT NULL DEFAULT ''")
                db.execute('PRAGMA user_version=4')
            if version<5:
                from app.operations_schema import SCHEMA as operation_schema, TICKET_COLUMNS
                existing={row[1] for row in db.execute('PRAGMA table_info(tickets)')}
                for name,definition in TICKET_COLUMNS.items():
                    if name not in existing:db.execute(f'ALTER TABLE tickets ADD COLUMN {name} {definition}')
                for statement in operation_schema:db.execute(statement)
                db.execute('PRAGMA user_version=5')
            db.commit()
            _initialized.add(path)
        except Exception:
            db.rollback(); raise


@contextmanager
def connection(write=False):
    if is_postgres():
        from app.postgres import connect
        with connect(os.environ['DATABASE_URL'],write=write) as db: yield db
        return
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not DB_PATH.exists(): _initialized.discard(str(DB_PATH.resolve()))
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=15000')
        _initialize(db)
        db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def load_or_seed(collections):
    with connection(write=True) as db:
        seeded=db.execute("SELECT 1 FROM snapshots WHERE id=2").fetchone()
        if not seeded:
            if not db.execute('SELECT 1 FROM policies LIMIT 1').fetchone():
                from app.retrieval import index_policy
                for table,rows in collections.items():
                    for index,row in enumerate(rows): _upsert(db,table,row,index)
                for policy in collections['policies']: index_policy(db,policy)
            db.execute("INSERT INTO snapshots(id,payload) VALUES (2,'migrated-to-relational-tables')")
        data=_read_business(db)
        for key,target in collections.items(): target[:]=data[key]


@contextmanager
def transaction(write=False,tables=None):
    with connection(write=write) as db:
        data = _read_business(db,tables)
        before=copy.deepcopy(data) if write else None
        yield data, db
        if write:
            for table,rows in data.items():
                previous={_key(table,row,i):(row,i) for i,row in enumerate(before[table])}
                current={_key(table,row,i) for i,row in enumerate(rows)}
                for key in previous.keys()-current:
                    db.execute(f'DELETE FROM {table} WHERE id=?',(key,))
                    if table=='policies':
                        from app.retrieval import remove_resource
                        remove_resource(db,'policy',key)
                for index,row in enumerate(rows):
                    if previous.get(_key(table,row,index)) != (row,index):
                        _upsert(db,table,row,index)
                        if table=='policies':
                            from app.retrieval import index_policy
                            index_policy(db,row)


def read_data(tables=None):
    with transaction(tables=tables) as (data, _):
        return data


def tickets_for(owner_id=None,status='',query=''):
    clauses=[]; params=[]
    if owner_id is not None: clauses.append('owner_id=?'); params.append(owner_id)
    if status and status!='全部': clauses.append('status=?'); params.append(status)
    if query:
        clauses.append("position(lower(?) in lower(id||' '||resident||' '||location||' '||category||' '||description))>0" if is_postgres() else "instr(lower(id||' '||resident||' '||location||' '||category||' '||description),lower(?))>0"); params.append(query)
    with connection() as db:
        rows=db.execute('SELECT * FROM tickets'+(' WHERE '+' AND '.join(clauses) if clauses else '')+' ORDER BY _position DESC,id',params).fetchall()
    return [{k:r[k] for k in r.keys() if k!='_position'} for r in rows]


def is_postgres():
    url=os.getenv('DATABASE_URL','').strip()
    if url and not url.startswith(('postgres://','postgresql://')): raise RuntimeError('DATABASE_URL must be a PostgreSQL connection URL')
    return bool(url)


def audit(db, action, resource_id, actor):
    db.execute('INSERT INTO audit(action,resource_id,actor,created_at) VALUES (?,?,?,?)', (action, resource_id, actor, datetime.now().isoformat(timespec='seconds')))


def events(resource_id):
    with connection() as db:
        return [dict(row) for row in db.execute('SELECT a.action,COALESCE(u.display_name,a.actor) AS actor,a.created_at FROM audit a LEFT JOIN users u ON a.actor=u.id WHERE resource_id=? ORDER BY a.id', (resource_id,))]


def claim_chat(owner_id, thread_id):
    now=int(time.time())
    with connection(write=True) as db:
        db.execute('DELETE FROM chat_threads WHERE updated_at<? AND locked_until<?',(now-30*86400,now))
        row=db.execute('SELECT * FROM chat_threads WHERE owner_id=? AND thread_id=?',(owner_id,thread_id)).fetchone()
        if row and row['locked_until']>now:
            raise HTTPException(409,'上一条消息仍在处理中，请稍后再试')
        if row and row['turns']>=80:
            raise HTTPException(409,'当前对话已达到长度上限，请开始新对话')
        if not row:
            count=db.execute('SELECT COUNT(*) FROM chat_threads WHERE owner_id=?',(owner_id,)).fetchone()[0]
            if count>=40:
                oldest=db.execute('SELECT thread_id FROM chat_threads WHERE owner_id=? AND locked_until<=? ORDER BY updated_at LIMIT 1',(owner_id,now)).fetchone()
                if not oldest:
                    raise HTTPException(429,'正在处理的对话过多')
                db.execute('DELETE FROM chat_threads WHERE owner_id=? AND thread_id=?',(owner_id,oldest[0]))
            db.execute('INSERT INTO chat_threads(owner_id,thread_id,updated_at) VALUES (?,?,?)',(owner_id,thread_id,now))
        lease=now+90
        db.execute('UPDATE chat_threads SET locked_until=? WHERE owner_id=? AND thread_id=?',(lease,owner_id,thread_id))
        return (json.loads(row['messages']) if row else []),lease


def finish_chat(owner_id,thread_id,lease,messages=None):
    with connection(write=True) as db:
        if messages is None:
            db.execute('UPDATE chat_threads SET locked_until=0 WHERE owner_id=? AND thread_id=? AND locked_until=?',(owner_id,thread_id,lease))
        else:
            trimmed=messages[-30:]
            while trimmed and trimmed[0].get('type')!='human':
                trimmed=trimmed[1:]
            db.execute('UPDATE chat_threads SET messages=?,turns=turns+1,locked_until=0,updated_at=? WHERE owner_id=? AND thread_id=? AND locked_until=?',(json.dumps(trimmed,ensure_ascii=False),int(time.time()),owner_id,thread_id,lease))


def chat_history(owner_id,thread_id):
    with connection() as db:
        row=db.execute('SELECT messages FROM chat_threads WHERE owner_id=? AND thread_id=?',(owner_id,thread_id)).fetchone()
        return json.loads(row['messages']) if row else []
