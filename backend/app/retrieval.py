"""SQLite FTS5/BM25 + optional OpenAI-compatible embeddings; no vector server."""
import hashlib
import json
import logging
import math
import os
import re
import threading
import time
import urllib.request
from datetime import date
from urllib.parse import urlsplit
from app import storage

STOP = {'怎么','什么','如何','需要','可以','办理','一下','请问','我要','帮我','是否','哪些','查询','申请','材料','流程','社区','居民','服务','咨询','政策','指南','的','了','吗'}
ALIASES = [
    (('外地人','长期住','暂住证','外来人口'), '居住证 居住登记'),
    (('老人补助','老年补贴','老人补贴'), '高龄 津贴 养老'),
    (('低收入','生活困难','困难家庭'), '低保 社会救助'),
]
_slots=threading.BoundedSemaphore(2)
_cache={}
_cache_lock=threading.Lock()
_failed_until=0


def tokens(text):
    result=[]
    for part in re.findall(r'[a-z0-9_-]+|[\u4e00-\u9fff]+',text.lower()):
        if re.fullmatch(r'[\u4e00-\u9fff]+',part):
            result.extend(part[i:i+2] for i in range(len(part)-1))
        else: result.append(part)
    return list(dict.fromkeys(term for term in result if term not in STOP))


def query_tokens(query):
    expanded=query
    for aliases,terms in ALIASES:
        if any(alias in query for alias in aliases): expanded+=' '+terms
    expanded=re.sub('|'.join(re.escape(word) for word in sorted(STOP,key=len,reverse=True)), ' ', expanded)
    return tokens(expanded)[:64]


def remove_resource(db,kind,resource_id):
    ids=[r[0] for r in db.execute('SELECT id FROM retrieval_chunks WHERE kind=? AND resource_id=?',(kind,resource_id))]
    for chunk_id in ids:
        db.execute('DELETE FROM knowledge_fts WHERE chunk_id=?',(chunk_id,))
    db.execute('DELETE FROM retrieval_chunks WHERE kind=? AND resource_id=?',(kind,resource_id))


def index_chunk(db,chunk_id,kind,resource_id,title,content,metadata):
    fingerprint=hashlib.sha256((title+'\n'+content).encode()).hexdigest()
    existing=db.execute('SELECT fingerprint FROM retrieval_chunks WHERE id=?',(chunk_id,)).fetchone()
    db.execute('INSERT INTO retrieval_chunks VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,content=excluded.content,metadata=excluded.metadata,fingerprint=excluded.fingerprint',
               (chunk_id,kind,resource_id,title,content,json.dumps(metadata,ensure_ascii=False),fingerprint))
    db.execute('DELETE FROM knowledge_fts WHERE chunk_id=?',(chunk_id,))
    db.execute('INSERT INTO knowledge_fts(chunk_id,title_tokens,body_tokens) VALUES (?,?,?)',(chunk_id,' '.join(tokens(title)),' '.join(tokens(content))))
    if existing and existing[0]!=fingerprint: db.execute('DELETE FROM chunk_vectors WHERE chunk_id=?',(chunk_id,))


def index_policy(db,policy):
    content=policy['summary']+'\n'+'\n'.join(policy['steps'])+'\n'+' '.join(policy['keywords'])
    index_chunk(db,'policy:'+policy['id'],'policy',policy['id'],policy['title'],content,policy)


def embedding_settings():
    base=os.getenv('EMBEDDING_BASE_URL','').strip().rstrip('/')
    model=os.getenv('EMBEDDING_MODEL','').strip()
    key=os.getenv('EMBEDDING_API_KEY','').strip()
    if not (base and model and key): return None
    parsed=urlsplit(base)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('EMBEDDING_BASE_URL 必须为 HTTPS API 地址，不含凭据或查询参数')
    dimensions=os.getenv('EMBEDDING_DIMENSIONS','').strip()
    try: dim=int(dimensions) if dimensions else None
    except ValueError: raise ValueError('EMBEDDING_DIMENSIONS 须为整数或留空') from None
    if dim is not None and not 1<=dim<=8192: raise ValueError('Embedding 维度须为 1–8192')
    provider=hashlib.sha256((base+'|'+model+'|'+str(dim)+'|'+os.getenv('EMBEDDING_INDEX_VERSION','1')).encode()).hexdigest()
    return {'base':base,'model':model,'key':key,'dimensions':dim,'provider':provider}


def _normalize(vector):
    if not isinstance(vector,list) or not 1<=len(vector)<=8192: raise ValueError('Invalid embedding dimensions')
    if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in vector): raise ValueError('Invalid embedding values')
    norm=math.sqrt(sum(float(x)*float(x) for x in vector))
    if not math.isfinite(norm) or norm==0: raise ValueError('Invalid embedding norm')
    return [float(x)/norm for x in vector]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None


def embed(texts,settings):
    if not _slots.acquire(timeout=.1): raise RuntimeError('Embedding 服务繁忙，请稍后重试')
    try:
        body={'model':settings['model'],'input':texts,'encoding_format':'float'}
        if settings['dimensions']: body['dimensions']=settings['dimensions']
        request=urllib.request.Request(settings['base']+'/embeddings',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+settings['key']},method='POST')
        with urllib.request.build_opener(_NoRedirect()).open(request,timeout=8) as response:
            raw=response.read(8*1024*1024+1)
        if len(raw)>8*1024*1024: raise ValueError('Embedding response too large')
        data=json.loads(raw)['data']
        if not isinstance(data,list) or len(data)!=len(texts): raise ValueError('Embedding result count mismatch')
        if sorted(item['index'] for item in data)!=list(range(len(texts))): raise ValueError('Invalid embedding indices')
        vectors=[_normalize(item['embedding']) for item in sorted(data,key=lambda item:item['index'])]
        if len({len(v) for v in vectors})!=1 or (settings['dimensions'] and len(vectors[0])!=settings['dimensions']): raise ValueError('Embedding dimensions mismatch')
        return vectors
    finally: _slots.release()


def _query_vector(query,settings):
    global _failed_until
    key=(settings['provider'],hashlib.sha256(query.encode()).hexdigest())
    with _cache_lock:
        cached=_cache.get(key)
        if cached and cached[0]>time.monotonic(): return cached[1]
        if _failed_until>time.monotonic(): return None
    try: vector=embed([query],settings)[0]
    except Exception as exc:
        logging.getLogger(__name__).warning('Embedding unavailable: %s',type(exc).__name__)
        with _cache_lock: _failed_until=time.monotonic()+30
        return None
    with _cache_lock:
        if len(_cache)>=128: _cache.pop(next(iter(_cache)))
        _cache[key]=(time.monotonic()+60,vector)
    return vector


def _active(db):
    today=date.today().isoformat()
    return {r[0] for r in db.execute("SELECT id FROM documents WHERE status='published' AND (effective_on='' OR effective_on<=?) AND (expires_on='' OR expires_on>=?)",(today,today))}


def retrieve(query,limit=8,semantic=True):
    terms=query_tokens(query)
    if not terms: return []
    match=' OR '.join('"'+term.replace('"','""')+'"' for term in terms)
    with storage.connection() as db:
        active=_active(db)
        # Apply visibility before LIMIT: unpublished material cannot crowd out results.
        if storage.is_postgres():
            expression=' | '.join("'"+term.replace("'","''")+"'" for term in terms)
            lexical=[dict(r) for r in db.execute("SELECT c.*,ts_rank_cd(f.search_vector,to_tsquery('simple',?)) AS relevance FROM knowledge_fts f JOIN retrieval_chunks c ON c.id=f.chunk_id WHERE f.search_vector @@ to_tsquery('simple',?) AND (c.kind='policy' OR EXISTS(SELECT 1 FROM documents d WHERE d.id=c.resource_id AND d.status='published' AND (d.effective_on='' OR d.effective_on<=?) AND (d.expires_on='' OR d.expires_on>=?))) ORDER BY relevance DESC,c.id LIMIT 40",(expression,expression,date.today().isoformat(),date.today().isoformat()))]
        else:
            lexical=[dict(r) for r in db.execute("SELECT c.*,bm25(knowledge_fts,0,4,1) AS bm25 FROM knowledge_fts JOIN retrieval_chunks c ON c.id=knowledge_fts.chunk_id WHERE knowledge_fts MATCH ? AND (c.kind='policy' OR EXISTS(SELECT 1 FROM documents d WHERE d.id=c.resource_id AND d.status='published' AND (d.effective_on='' OR d.effective_on<=?) AND (d.expires_on='' OR d.expires_on>=?))) ORDER BY bm25 LIMIT 40",(match,date.today().isoformat(),date.today().isoformat()))]
        settings=None
        try: settings=embedding_settings() if semantic else None
        except ValueError: pass
        vectors=[dict(r) for r in db.execute('SELECT c.*,v.vector,v.dimensions FROM chunk_vectors v JOIN retrieval_chunks c ON c.id=v.chunk_id AND c.fingerprint=v.fingerprint WHERE v.provider=? LIMIT 5001',(settings['provider'],))] if settings else []
    filtered=[]
    for row in lexical:
        matches=set(terms)&set(tokens(row['title']+' '+row['content']))
        meta=json.loads(row['metadata'])
        anchors=set(tokens(row['title']+' '+' '.join(meta.get('keywords',[]))))
        if len(matches)>=min(2,len(terms)) or matches&anchors: filtered.append(row)
    lexical=filtered
    scores={}; candidates={}; methods={}
    for rank,row in enumerate(lexical):
        scores[row['id']]=1/(60+rank+1); candidates[row['id']]=row; methods[row['id']]={'postgres-fts' if storage.is_postgres() else 'fts5'}
    if vectors and len(vectors)<=5000:
        query_vector=_query_vector(query,settings)
        if query_vector:
            similarities=[]
            try: minimum=float(os.getenv('EMBEDDING_MIN_SIMILARITY','0.55'))
            except ValueError: minimum=.55
            minimum=max(0,min(1,minimum)) if math.isfinite(minimum) else .55
            for row in vectors:
                if row['kind']=='document' and row['resource_id'] not in active: continue
                if row['dimensions']!=len(query_vector): continue
                vector=json.loads(row['vector'])
                similarity=sum(a*b for a,b in zip(query_vector,vector))
                if similarity>=minimum: similarities.append((similarity,row))
            for rank,(similarity,row) in enumerate(sorted(similarities,key=lambda pair:pair[0],reverse=True)[:40]):
                chunk_id=row['id']; scores[chunk_id]=scores.get(chunk_id,0)+1/(60+rank+1)
                candidates[chunk_id]=row; methods.setdefault(chunk_id,set()).add('vector')
    results=[]; seen=set()
    for chunk_id in sorted(scores,key=scores.get,reverse=True):
        row=candidates[chunk_id]
        if row['resource_id'] in seen: continue
        # Recheck status after the provider call; a concurrent archive takes effect now.
        if row['kind']=='document':
            with storage.connection() as db:
                if row['resource_id'] not in _active(db): continue
        seen.add(row['resource_id'])
        meta=json.loads(row['metadata'])
        results.append({'id':row['resource_id'],'kind':row['kind'],'title':row['title'],'excerpt':row['content'][:900],'chunk_id':chunk_id,'retrieval_method':'+'.join(sorted(methods[chunk_id])),'metadata':meta})
        if len(results)>=limit: break
    return results


def reindex_vectors():
    settings=embedding_settings()
    if not settings: raise ValueError('请先配置独立的 EMBEDDING_BASE_URL、EMBEDDING_MODEL 和 EMBEDDING_API_KEY')
    with storage.connection() as db:
        active=_active(db)
        rows=[dict(r) for r in db.execute('SELECT c.* FROM retrieval_chunks c LEFT JOIN chunk_vectors v ON c.id=v.chunk_id AND c.fingerprint=v.fingerprint AND v.provider=? WHERE v.chunk_id IS NULL ORDER BY c.id',(settings['provider'],)) if r['kind']=='policy' or r['resource_id'] in active]
        total=db.execute('SELECT COUNT(*) FROM retrieval_chunks').fetchone()[0]
    if total>5000: raise ValueError('轻量向量检索上限为 5000 个片段，请先归档或清理资料，或迁移专用向量索引')
    selected=rows[:64]; saved=0
    for start in range(0,len(selected),16):
        batch=selected[start:start+16]
        vectors=embed([r['title']+'\n'+r['content'] for r in batch],settings)
        with storage.connection(write=True) as db:
            active=_active(db)
            for row,vector in zip(batch,vectors):
                current=db.execute('SELECT fingerprint FROM retrieval_chunks WHERE id=?',(row['id'],)).fetchone()
                if not current or current[0]!=row['fingerprint'] or (row['kind']=='document' and row['resource_id'] not in active): continue
                db.execute('INSERT INTO chunk_vectors VALUES (?,?,?,?,?) ON CONFLICT(chunk_id) DO UPDATE SET provider=excluded.provider,fingerprint=excluded.fingerprint,dimensions=excluded.dimensions,vector=excluded.vector',(row['id'],settings['provider'],row['fingerprint'],len(vector),json.dumps(vector)))
                saved+=1
    return {'indexed':saved,'remaining':max(0,len(rows)-saved),'message':'本批索引已保存，可继续构建剩余片段' if len(rows)>saved else '当前已发布资料的向量索引已完成'}


def status():
    try: settings=embedding_settings(); error=''
    except ValueError as exc: settings=None; error=str(exc)
    with storage.connection() as db:
        chunks=db.execute('SELECT COUNT(*) FROM retrieval_chunks').fetchone()[0]
        indexed=db.execute('SELECT COUNT(*) FROM chunk_vectors v JOIN retrieval_chunks c ON c.id=v.chunk_id AND c.fingerprint=v.fingerprint WHERE provider=?',(settings['provider'],)).fetchone()[0] if settings else 0
    return {'engine':'postgres-fulltext-rank' if storage.is_postgres() else 'sqlite-fts5-bm25','embedding_configured':bool(settings),'embedding_model':settings['model'] if settings else '', 'chunks':chunks,'indexed':indexed,'vector_limit':5000,'configuration_error':error}
