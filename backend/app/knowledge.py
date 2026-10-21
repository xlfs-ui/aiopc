"""Admin-reviewed knowledge ingestion, versioning and resident citations."""
import base64
import hashlib
import json
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app import storage, retrieval
from app.auth import current_user, require_admin, enforce_rate

router=APIRouter(prefix='/api/knowledge',dependencies=[Depends(current_user)])


class DocumentInput(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    title:str=Field(min_length=2,max_length=120)
    source:str=Field(min_length=2,max_length=200)
    source_url:str=Field(default='',max_length=1000)
    filename:str=Field(default='资料.txt',min_length=1,max_length=160)
    text:str=Field(default='',max_length=200_000)
    file_base64:str=Field(default='',max_length=1_398_104)
    document_key:str=Field(default='',max_length=80,pattern=r'^[A-Za-z0-9_-]*$')
    effective_on:str=Field(default='',max_length=10)
    expires_on:str=Field(default='',max_length=10)

    @model_validator(mode='after')
    def validate_fields(self):
        if bool(self.text)==bool(self.file_base64): raise ValueError('正文和文件须选择其中一种')
        if self.source_url:
            from urllib.parse import urlsplit
            parsed=urlsplit(self.source_url)
            if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password or any(ord(c)<32 for c in self.source_url): raise ValueError('来源链接须为公开 HTTP(S) 地址')
        for value in (self.effective_on,self.expires_on):
            if value and date.fromisoformat(value).isoformat()!=value: raise ValueError('日期格式须为 YYYY-MM-DD')
        if self.effective_on and self.expires_on and self.expires_on<self.effective_on: raise ValueError('失效日期不能早于生效日期')
        if '/' in self.filename or '\\' in self.filename: raise ValueError('文件名不能包含路径')
        return self


def extract(payload):
    if payload.text: return [(None,payload.text)]
    try: raw=base64.b64decode(payload.file_base64,validate=True)
    except Exception: raise HTTPException(422,'文件编码错误')
    if len(raw)>1024*1024: raise HTTPException(413,'单个文件最大 1 MiB')
    if Path(payload.filename).suffix.lower() not in ('.pdf','.docx','.txt','.md'): raise HTTPException(422,'仅支持 PDF、DOCX、TXT 和 Markdown')
    try:
        startup=None
        if sys.platform=='win32':
            startup=subprocess.STARTUPINFO(); startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW; startup.wShowWindow=0
        result=subprocess.run([sys.executable,'-m','app.document_parser',payload.filename],input=raw,capture_output=True,timeout=15,cwd=Path(__file__).resolve().parents[1],startupinfo=startup)
        output=json.loads(result.stdout)
    except subprocess.TimeoutExpired: raise HTTPException(422,'文档解析超时，请拆分文档或转换为 TXT')
    except Exception: raise HTTPException(422,'无法解析该文档，请转换为 UTF-8 TXT 重试')
    if output.get('error'): raise HTTPException(422,output['error'])
    return output['pages']


def split_pages(pages):
    chunks=[]; offset=0
    for page,text in pages:
        text=text.replace('\r\n','\n').replace('\r','\n').strip()
        start=0
        while start<len(text):
            end=min(start+700,len(text))
            if end<len(text):
                boundary=max(text.rfind('\n',start+350,end),text.rfind('。',start+350,end))
                if boundary>start: end=boundary+1
            content=text[start:end].strip()
            if content: chunks.append({'page':page,'content':content,'start_offset':offset+start,'end_offset':offset+end})
            if end==len(text): break
            start=max(start+1,end-100)
        offset+=len(text)+1
    return chunks


def public_document(row,detail=False):
    result={k:row[k] for k in ('id','document_key','version','title','source','source_url','filename','status','effective_on','expires_on','created_at','updated_at')}
    if detail: result['content']=row['content']
    return result


@router.get('/status')
def knowledge_status(user=Depends(require_admin)):
    return retrieval.status()


@router.get('/documents')
def list_documents(offset:int=Query(default=0,ge=0),limit:int=Query(default=25,ge=1,le=100),user=Depends(require_admin)):
    with storage.connection() as db:
        total=db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]
        rows=db.execute('SELECT d.*, (SELECT COUNT(*) FROM document_chunks c WHERE c.document_id=d.id) AS chunk_count FROM documents d ORDER BY created_at DESC LIMIT ? OFFSET ?',(limit,offset)).fetchall()
    return {'items':[{**public_document(r),'chunk_count':r['chunk_count']} for r in rows],'total':total}


@router.post('/documents',status_code=201)
def ingest(payload:DocumentInput,user=Depends(require_admin)):
    enforce_rate('knowledge-import:'+user['id'],10,3600)
    pages=extract(payload); chunks=split_pages(pages)
    if not chunks: raise HTTPException(422,'资料正文为空')
    if len(chunks)>400: raise HTTPException(422,'片段过多，请拆分文档')
    content='\n'.join(text.strip() for _,text in pages)
    if '\x00' in content: raise HTTPException(422,'正文包含非法字符')
    stamp=datetime.now().isoformat(timespec='microseconds'); document_id='D-'+uuid4().hex
    key=payload.document_key or uuid4().hex
    with storage.connection(write=True) as db:
        if db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]>=500: raise HTTPException(409,'知识文档最多 500 个版本，请先清理旧草稿或归档版本')
        if db.execute('SELECT COUNT(*) FROM document_chunks').fetchone()[0]+len(chunks)>20_000: raise HTTPException(409,'知识片段数量已达上限')
        previous=db.execute('SELECT MAX(version) FROM documents WHERE document_key=?',(key,)).fetchone()[0]
        version=(previous or 0)+1
        original=base64.b64decode(payload.file_base64) if payload.file_base64 else None
        db.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(document_id,key,version,payload.title,payload.source,payload.source_url,payload.filename,hashlib.sha256(content.encode()).hexdigest(),content,original,'draft',payload.effective_on,payload.expires_on,user['id'],stamp,stamp))
        for index,chunk in enumerate(chunks):
            db.execute('INSERT INTO document_chunks VALUES (?,?,?,?,?,?,?)',(document_id+':'+str(index),document_id,index,chunk['page'],chunk['content'],chunk['start_offset'],chunk['end_offset']))
        storage.audit(db,'导入知识草稿',document_id,user['id'])
        row=db.execute('SELECT * FROM documents WHERE id=?',(document_id,)).fetchone()
    return {**public_document(row),'chunk_count':len(chunks)}


@router.get('/documents/{document_id}')
def document_detail(document_id:str,user=Depends(current_user)):
    with storage.connection() as db:
        row=db.execute('SELECT * FROM documents WHERE id=?',(document_id,)).fetchone()
        today=date.today().isoformat()
        if not row or (user['role']!='admin' and (row['status']!='published' or (row['effective_on'] and row['effective_on']>today) or (row['expires_on'] and row['expires_on']<today))): raise HTTPException(404,'资料不存在或尚未生效')
        chunks=[{k:r[k] for k in ('id','ordinal','page','content','start_offset','end_offset')} for r in db.execute('SELECT * FROM document_chunks WHERE document_id=? ORDER BY ordinal',(document_id,))]
    return {**public_document(row,True),'chunks':chunks}


class Transition(BaseModel):
    model_config=ConfigDict(extra='forbid')
    status:Literal['published','archived']


@router.patch('/documents/{document_id}')
def transition(document_id:str,payload:Transition,user=Depends(require_admin)):
    with storage.connection(write=True) as db:
        row=db.execute('SELECT * FROM documents WHERE id=?',(document_id,)).fetchone()
        if not row: raise HTTPException(404,'资料不存在')
        if row['status']==payload.status: return public_document(row)
        if payload.status=='published':
            if row['status']!='draft': raise HTTPException(409,'归档资料不可重新发布，请导入新版本')
            newer=db.execute("SELECT 1 FROM documents WHERE document_key=? AND version>? AND status IN ('published','archived')",(row['document_key'],row['version'])).fetchone()
            if newer: raise HTTPException(409,'已有较新版本发布或归档，请导入新的版本，不能发布旧草稿')
            if row['expires_on'] and row['expires_on']<date.today().isoformat(): raise HTTPException(409,'资料已失效，不能发布')
            # A future version must be reviewed on its effective date so it does
            # not archive the still-effective previous version prematurely.
            if row['effective_on'] and row['effective_on']>date.today().isoformat(): raise HTTPException(409,'尚未到生效日期，请于生效后发布')
            older=db.execute("SELECT id FROM documents WHERE document_key=? AND status='published'",(row['document_key'],)).fetchall()
            for old in older:
                db.execute("UPDATE documents SET status='archived',updated_at=? WHERE id=?",(datetime.now().isoformat(),old[0]))
                retrieval.remove_resource(db,'document',old[0])
            for chunk in db.execute('SELECT * FROM document_chunks WHERE document_id=?',(document_id,)).fetchall():
                meta={**public_document(row),'status':'published','page':chunk['page'],'ordinal':chunk['ordinal'],'chunk_id':chunk['id']}
                retrieval.index_chunk(db,chunk['id'],'document',document_id,row['title'],chunk['content'],meta)
        else: retrieval.remove_resource(db,'document',document_id)
        db.execute('UPDATE documents SET status=?,updated_at=? WHERE id=?',(payload.status,datetime.now().isoformat(timespec='microseconds'),document_id))
        storage.audit(db,'知识资料'+('审核发布' if payload.status=='published' else '归档'),document_id,user['id'])
        row=db.execute('SELECT * FROM documents WHERE id=?',(document_id,)).fetchone()
    return public_document(row)


@router.delete('/documents/{document_id}')
def delete_document(document_id:str,user=Depends(require_admin)):
    with storage.connection(write=True) as db:
        row=db.execute('SELECT status FROM documents WHERE id=?',(document_id,)).fetchone()
        if not row: raise HTTPException(404,'资料不存在')
        if row[0]=='published': raise HTTPException(409,'请先归档已发布资料')
        retrieval.remove_resource(db,'document',document_id)
        db.execute('DELETE FROM documents WHERE id=?',(document_id,))
        storage.audit(db,'删除知识资料',document_id,user['id'])
    return {'message':'已删除该版本资料及其索引'}


@router.post('/reindex')
def reindex(user=Depends(require_admin)):
    enforce_rate('knowledge-index:'+user['id'],10,3600)
    try: return retrieval.reindex_vectors()
    except ValueError as exc: raise HTTPException(409,str(exc))
    except Exception: raise HTTPException(502,'Embedding 调用失败，本地全文检索仍可用；请核对模型、接口、配额和网络')


@router.get('/search')
def knowledge_search(q:str=Query(min_length=1,max_length=1000),user=Depends(current_user)):
    enforce_rate('knowledge-search:'+user['id'],30,60)
    results=retrieval.retrieve(q)
    return {'results':results,'total':len(results)}
