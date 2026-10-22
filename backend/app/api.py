"""Business routes. Every route requires a session; identity comes from it."""
import hashlib
import json
import logging
import re
import time
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from app import storage
from app.auth import current_user, require_admin, enforce_rate

router=APIRouter(prefix='/api',dependencies=[Depends(current_user)])
TicketStatus=Literal['待受理','处理中','待确认','已完成']
ShortText=Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=160)]


class Payload(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)


class TicketCreate(Payload):
    phone: str = Field(default='',max_length=30,pattern=r'^[0-9+*()\-\s]*$')
    location: str = Field(min_length=2,max_length=100)
    category: Literal['公共设施','公共照明','道路设施','给排水','环境卫生','噪音问题','其他诉求']='其他诉求'
    description: str = Field(min_length=3,max_length=500)
    priority: Literal['普通','较急']='普通'


class TicketUpdate(Payload):
    status: TicketStatus | None=None
    assignee: str | None=Field(default=None,min_length=1,max_length=40)


class ChatRequest(Payload):
    message: str=Field(min_length=1,max_length=1000)
    thread_id: str=Field(default_factory=lambda:str(uuid4()),min_length=1,max_length=80,pattern=r'^[A-Za-z0-9_-]+$')


class PolicyPayload(Payload):
    title: str=Field(min_length=2,max_length=100)
    category: str=Field(min_length=2,max_length=40)
    summary: str=Field(min_length=5,max_length=1000)
    steps: list[ShortText]=Field(default_factory=list,max_length=8)
    source: str=Field(min_length=2,max_length=160)
    phone: str=Field(default='',max_length=30)
    keywords: list[Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=40)]]=Field(default_factory=list,max_length=20)


class ActivityPayload(Payload):
    title: str=Field(min_length=2,max_length=100)
    category: str=Field(min_length=2,max_length=40)
    date: str=Field(min_length=10,max_length=10)
    time: str=Field(min_length=3,max_length=50)
    location: str=Field(min_length=2,max_length=160)
    capacity: int=Field(gt=0,le=10000)
    audience: str=Field(min_length=2,max_length=100)
    description: str=Field(min_length=5,max_length=500)
    tag: str=Field(default='开放报名',max_length=30)

    @field_validator('date')
    @classmethod
    def valid_date(cls,value):
        date.fromisoformat(value)
        return value


def ticket_view(ticket):
    return {k:v for k,v in ticket.items() if k!='owner_id'}


def activity_views(data,user_id=None):
    return [{**a,'registered':a['registered']+sum(r['activity_id']==a['id'] for r in data['registrations']),'is_registered':any(r['activity_id']==a['id'] and r.get('owner_id')==user_id for r in data['registrations']) if user_id else False} for a in data['activities']]


@router.get('/search')
def search(q: str=Query(default='',max_length=1000),user=Depends(current_user)):
    enforce_rate('resource-search:'+user['id'],30,60)
    from app.services import search_resources
    results=search_resources(q,user['id'])
    return {'query':q,'results':results,'total':len(results)}


@router.get('/overview')
def overview(user=Depends(require_admin)):
    data=storage.read_data(tables=('tickets',))
    tickets=data['tickets']
    counts=Counter(t['category'] for t in tickets)
    total=max(1,len(tickets))
    today=date.today()
    return {'open_tickets':sum(t['status']!='已完成' for t in tickets),'today_new':sum(t['created_at'].startswith(today.isoformat()) for t in tickets),'avg_response':'—','resolution_rate':round(sum(t['status']=='已完成' for t in tickets)/total*100),'ticket_trend':[sum(t['created_at'].startswith((today-timedelta(days=i)).isoformat()) for t in tickets) for i in range(6,-1,-1)],'category_stats':[{'name':k,'value':round(v/total*100)} for k,v in counts.most_common(4)]}


@router.get('/policies')
def list_policies(q: str=Query(default='',max_length=100)):
    items=storage.read_data(tables=('policies',))['policies']
    if q:
        key=q.strip().lower()
        items=[p for p in items if key in (p['title']+' '+p['summary']+' '+' '.join(p['keywords'])).lower()]
    return [{k:v for k,v in p.items() if k!='keywords'} for p in items]


@router.post('/policies',status_code=201)
def create_policy(payload: PolicyPayload,user=Depends(require_admin)):
    with storage.transaction(write=True,tables=('policies',)) as (data,db):
        if len(data['policies'])>=2000: raise HTTPException(409,'资料数量已达上限')
        policy={'id':'P-'+uuid4().hex[:12].upper(),**payload.model_dump(),'updated_at':date.today().isoformat()}
        data['policies'].insert(0,policy)
        storage.audit(db,'发布政策资料',policy['id'],user['id'])
        return policy


@router.put('/policies/{policy_id}')
def update_policy(policy_id: str,payload: PolicyPayload,user=Depends(require_admin)):
    with storage.transaction(write=True,tables=('policies',)) as (data,db):
        policy=next((p for p in data['policies'] if p['id']==policy_id),None)
        if not policy: raise HTTPException(404,'未找到该政策资料')
        policy.update(payload.model_dump())
        policy['updated_at']=date.today().isoformat()
        storage.audit(db,'更新政策资料',policy_id,user['id'])
        return policy


@router.get('/tickets')
def list_tickets(status: str=Query(default='',max_length=20),q: str=Query(default='',max_length=100),mine: bool=False,user=Depends(current_user)):
    items=storage.tickets_for(user['id'] if user['role']!='admin' or mine else None,status,q)
    return [ticket_view(t) for t in items]


@router.post('/tickets',status_code=201)
def create_ticket(payload: TicketCreate,key: str | None=Header(default=None,alias='Idempotency-Key',max_length=80,pattern=r'^[A-Za-z0-9_-]+$'),user=Depends(current_user)):
    if not key: raise HTTPException(400,'缺少提交标识，请刷新表单后重试')
    enforce_rate('ticket:'+user['id'],30,3600)
    encoded=json.dumps(payload.model_dump(),sort_keys=True,ensure_ascii=False)
    signature=hashlib.sha256(encoded.encode()).hexdigest()
    with storage.transaction(write=True,tables=('tickets',)) as (data,db):
        db.execute('DELETE FROM idempotency WHERE created_at<?',(int(time.time())-7*86400,))
        existing=db.execute('SELECT digest,response FROM idempotency WHERE owner_id=? AND key=?',(user['id'],key)).fetchone()
        if existing:
            if existing['digest']!=signature: raise HTTPException(409,'该提交标识已使用，请重新打开报修表单')
            return json.loads(existing['response'])
        if len(data['tickets'])>=10000: raise HTTPException(409,'记录数量已达上限，请联系管理员')
        stamp=datetime.now().isoformat(timespec='seconds')
        ticket={'id':f'YS-{date.today().year}-{uuid4().hex[:12].upper()}',**payload.model_dump(),'owner_id':user['id'],'resident':user['display_name'],'status':'待受理','assignee':'待指派','created_at':stamp,'updated_at':stamp}
        data['tickets'].append(ticket)
        result=ticket_view(ticket)
        db.execute('INSERT INTO idempotency VALUES (?,?,?,?,?)',(user['id'],key,signature,json.dumps(result,ensure_ascii=False),int(time.time())))
        storage.audit(db,'提交工单',ticket['id'],user['id'])
        return result


@router.get('/tickets/{ticket_id}')
def ticket_detail(ticket_id: str,user=Depends(current_user)):
    ticket=next((t for t in storage.tickets_for(None if user['role']=='admin' else user['id']) if t['id']==ticket_id),None)
    if not ticket: raise HTTPException(404,'未找到该工单')
    return {**ticket_view(ticket),'events':storage.events(ticket_id) or [{'action':'历史演示记录 · '+ticket['status'],'actor':ticket['assignee'],'created_at':ticket['updated_at']}]}


@router.patch('/tickets/{ticket_id}')
def update_ticket(ticket_id: str,payload: TicketUpdate,user=Depends(require_admin)):
    changes=payload.model_dump(exclude_none=True)
    if not changes: raise HTTPException(422,'请指定需要更新的内容')
    allowed={'待受理':{'处理中'},'处理中':{'待确认'},'待确认':{'处理中','已完成'},'已完成':set()}
    with storage.transaction(write=True,tables=('tickets',)) as (data,db):
        ticket=next((t for t in data['tickets'] if t['id']==ticket_id),None)
        if not ticket: raise HTTPException(404,'未找到该工单')
        if 'status' in changes and changes['status']!=ticket['status'] and changes['status'] not in allowed[ticket['status']]:
            raise HTTPException(409,'不允许跳过工单处理步骤')
        ticket.update(changes)
        ticket['updated_at']=datetime.now().isoformat(timespec='seconds')
        storage.audit(db,'工单更新为'+ticket['status'],ticket_id,user['id'])
        return ticket_view(ticket)


@router.get('/activities')
def list_activities(user=Depends(current_user)):
    return activity_views(storage.read_data(tables=('activities','registrations')),user['id'])


@router.post('/activities',status_code=201)
def create_activity(payload: ActivityPayload,user=Depends(require_admin)):
    with storage.transaction(write=True,tables=('activities',)) as (data,db):
        if len(data['activities'])>=2000: raise HTTPException(409,'活动数量已达上限')
        activity={'id':'A-'+uuid4().hex[:12].upper(),**payload.model_dump(),'registered':0}
        data['activities'].insert(0,activity)
        storage.audit(db,'发布活动',activity['id'],user['id'])
        return activity


@router.put('/activities/{activity_id}')
def update_activity(activity_id: str,payload: ActivityPayload,user=Depends(require_admin)):
    with storage.transaction(write=True,tables=('activities','registrations')) as (data,db):
        activity=next((a for a in data['activities'] if a['id']==activity_id),None)
        if not activity: raise HTTPException(404,'未找到该活动')
        used=activity['registered']+sum(r['activity_id']==activity_id for r in data['registrations'])
        if payload.capacity<used: raise HTTPException(409,'活动名额不能小于已报名人数')
        activity.update(payload.model_dump())
        storage.audit(db,'更新活动',activity_id,user['id'])
        return activity


def register_for_user(activity_id,user):
    enforce_rate('registration:'+user['id'],30,3600)
    with storage.transaction(write=True,tables=('activities','registrations')) as (data,db):
        activity=next((a for a in data['activities'] if a['id']==activity_id),None)
        if not activity: raise HTTPException(404,'活动不存在')
        if any(r['activity_id']==activity_id and r.get('owner_id')==user['id'] for r in data['registrations']):
            raise HTTPException(409,'你已报名该活动')
        if activity['registered']+sum(r['activity_id']==activity_id for r in data['registrations'])>=activity['capacity']:
            raise HTTPException(409,'活动名额已满')
        row={'activity_id':activity_id,'resident':user['display_name'],'owner_id':user['id'],'created_at':date.today().isoformat()}
        data['registrations'].append(row)
        storage.audit(db,'报名活动',activity_id,user['id'])
        return {'message':'报名成功','registration':{k:v for k,v in row.items() if k!='owner_id'}}


@router.post('/activities/{activity_id}/register',status_code=201)
def register_activity(activity_id: str,payload: Payload,user=Depends(current_user)):
    return register_for_user(activity_id,user)


@router.get('/chat/history/{thread_id}')
def history(thread_id: str,user=Depends(current_user)):
    items=storage.chat_history(user['id'],thread_id)
    return {'messages':[{'role':'user' if m['type']=='human' else 'assistant','text':m['data']['content']} for m in items if m['type']=='human' or (m['type']=='ai' and not m['data'].get('tool_calls'))]}


@router.post('/chat')
def chat(payload: ChatRequest,user=Depends(current_user)):
    from app.services import search_resources,local_answer
    enforce_rate('chat-minute:'+user['id'],20,60)
    enforce_rate('chat-day:'+user['id'],200,86400)
    previous,lease=storage.claim_chat(user['id'],payload.thread_id)
    saved=False
    try:
        resources=search_resources(payload.message,user['id'])
        result=local_answer(payload.message,user['display_name'],resources)
        messages=previous+[{'type':'human','data':{'content':payload.message}},{'type':'ai','data':{'content':result['reply']}}]
        try:
            from app.agent import agent_configured,run_agent
            if agent_configured():
                output=run_agent(payload.message,user['display_name'],payload.thread_id,user['id'],previous)
                messages=output.pop('_history')
                result={**result,**output,'resources':output.get('resources') or resources,'mode':'deepseek-langgraph'}
        except Exception as exc:
            logging.getLogger(__name__).warning('Agent request failed: %s',type(exc).__name__)
            result['notice']='智能整理暂不可用，已为你保留本地检索与服务入口。'
        result['trace']=['检索社区资料','匹配内容与办理流程',f"找到 {len(result['resources'])} 项结果"]
        storage.finish_chat(user['id'],payload.thread_id,lease,messages)
        saved=True
        try:
            from app.civic import record_consultation
            if user['role']=='resident': record_consultation(payload.message,f'{user["id"]}:{payload.thread_id}:{lease}')
        except Exception as exc:
            logging.getLogger(__name__).warning('Consultation aggregate unavailable: %s',type(exc).__name__)
        return result
    finally:
        if not saved: storage.finish_chat(user['id'],payload.thread_id,lease)
