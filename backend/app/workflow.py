"""Account-scoped work orders, real assignee records, feedback and notifications."""
import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal
from app import storage
from app.auth import current_user, require_admin, enforce_rate

router=APIRouter(prefix='/api',dependencies=[Depends(current_user)])
TZ=timezone(timedelta(hours=8))
def stamp(): return datetime.now(TZ).isoformat(timespec='microseconds')

def staff_for(db,user):
    return db.execute('SELECT * FROM service_staff WHERE user_id=? AND active=1',(user['id'],)).fetchone()

def permitted(ticket,user,staff=None):
    return user['role']=='admin' or ticket.get('owner_id')==user['id'] or bool(staff and ticket.get('assigned_staff_id')==staff['id'])

def ticket_view(ticket,user,staff=None):
    return {**{k:v for k,v in ticket.items() if k not in ('owner_id','_position')},'can_confirm':ticket.get('owner_id')==user['id'],'can_manage':user['role']=='admin','can_handle':bool(staff and ticket.get('assigned_staff_id')==staff['id'])}

def notify(db,recipient,event,kind,title,body,resource):
    if not recipient: return
    identifier=hashlib.sha256((recipient+'|'+event).encode()).hexdigest()
    db.execute("INSERT INTO notifications(id,recipient_id,event_key,kind,title,body,resource_id,created_at,read_at) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(recipient_id,event_key) DO NOTHING",(identifier,recipient,event,kind,title,body,resource,stamp(),''))

def notify_ticket_created(db,ticket,user):
    notify(db,user['id'],'created:'+ticket['id'],'ticket','工单已提交',ticket['category']+' · '+ticket['location'],ticket['id'])
    for admin in db.execute("SELECT id FROM users WHERE role='admin'"):
        if admin['id']!=user['id']:notify(db,admin['id'],'new:'+ticket['id'],'ticket','新工单待分派',ticket['category']+' · '+ticket['location'],ticket['id'])

def notify_activity(db,activity,title):
    for row in db.execute('SELECT owner_id FROM registrations WHERE activity_id=? AND owner_id IS NOT NULL',(activity['id'],)):
        notify(db,row['owner_id'],'activity-update:'+activity['id']+':'+stamp(),'activity_update',title,activity['title']+' · '+activity['date']+' '+activity['time']+' · '+activity['location'],activity['id'])

class StaffInput(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    name:str=Field(min_length=2,max_length=40)
    team:str=Field(min_length=2,max_length=60)
    phone:str=Field(default='',max_length=30,pattern=r'^[0-9+*()\-\s]*$')
    user_id:str|None=Field(default=None,max_length=80)
    active:bool=True

@router.get('/workforce')
def workforce(user=Depends(require_admin)):
    with storage.connection() as db:
        return [dict(r) for r in db.execute('SELECT s.*,u.username,u.display_name FROM service_staff s LEFT JOIN users u ON u.id=s.user_id ORDER BY s.active DESC,s.name,s.id')]

@router.get('/workforce/accounts')
def workforce_accounts(q:str=Query(default='',max_length=40),user=Depends(require_admin)):
    with storage.connection() as db:
        # Disabled demonstration identities must not be presented as login accounts.
        rows=db.execute("SELECT id,username,display_name FROM users WHERE password_hash NOT LIKE '!%' ORDER BY username LIMIT 500").fetchall()
    return [dict(r) for r in rows if not q or q.casefold() in (r['username']+' '+r['display_name']).casefold()]

def save_staff(identifier,payload,user,create=False):
    with storage.connection(write=True) as db:
        old=db.execute('SELECT * FROM service_staff WHERE id=?',(identifier,)).fetchone()
        if not create and not old:raise HTTPException(404,'处理人员不存在')
        account=payload.user_id or None
        if account:
            found=db.execute('SELECT id,password_hash FROM users WHERE id=?',(account,)).fetchone()
            if not found or found['password_hash'].startswith('!'):raise HTTPException(422,'请选择可登录的真实账号')
            duplicate=db.execute('SELECT id FROM service_staff WHERE user_id=? AND id<>?',(account,identifier)).fetchone()
            if duplicate:raise HTTPException(409,'该账号已关联其他处理人员')
        # Prevent silent ownership changes or removing access to unfinished work.
        if old and (not payload.active or old['user_id']!=account):
            if db.execute("SELECT 1 FROM tickets WHERE assigned_staff_id=? AND status<>'已完成' LIMIT 1",(identifier,)).fetchone():
                raise HTTPException(409,'该人员仍有未完成工单，请先改派或结单，再停用或更换关联账号')
        values=(payload.name,payload.team,payload.phone,account,int(payload.active))
        if create:
            db.execute('INSERT INTO service_staff VALUES (?,?,?,?,?,?,?)',(identifier,*values,stamp()))
        else:
            db.execute('UPDATE service_staff SET name=?,team=?,phone=?,user_id=?,active=? WHERE id=?',(*values,identifier))
            db.execute('UPDATE tickets SET assignee=?,version=version+1,updated_at=? WHERE assigned_staff_id=?',(payload.name,stamp(),identifier))
        storage.audit(db,'新增处理人员' if create else '更新处理人员',identifier,user['id'])
        if account:notify(db,account,'staff-access:'+identifier+':'+stamp(),'account','处理人员权限已更新',payload.name+' · '+payload.team+'。刷新或重新登录后可进入工单工作台。',identifier)
    return {'id':identifier,'message':'处理人员已保存'}

@router.post('/workforce',status_code=201)
def create_staff(payload:StaffInput,user=Depends(require_admin)):
    return save_staff('staff-'+uuid4().hex,payload,user,True)

@router.put('/workforce/{staff_id}')
def update_staff(staff_id:str,payload:StaffInput,user=Depends(require_admin)):
    return save_staff(staff_id,payload,user)

class WorkAction(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    action:Literal['assign','progress','report','confirm','reject']
    expected_version:int=Field(ge=0)
    staff_id:str=Field(default='',max_length=80)
    note:str=Field(min_length=3,max_length=1000)
    due_at:str|None=Field(default=None,max_length=40)

    @field_validator('due_at')
    @classmethod
    def due_date(cls,value):
        if not value:return value
        try:
            parsed=datetime.fromisoformat(value)
            return (parsed.replace(tzinfo=TZ) if parsed.tzinfo is None else parsed).astimezone(TZ).isoformat(timespec='seconds')
        except ValueError:raise ValueError('预约处理时间格式错误') from None

@router.get('/tickets/{ticket_id}')
def detail(ticket_id:str,user=Depends(current_user)):
    with storage.connection() as db:
        row=db.execute('SELECT * FROM tickets WHERE id=?',(ticket_id,)).fetchone()
        staff=staff_for(db,user)
        if not row or not permitted(dict(row),user,staff):raise HTTPException(404,'未找到该工单')
        result=ticket_view(dict(row),user,staff)
        assigned=db.execute('SELECT name,team,phone,active,user_id FROM service_staff WHERE id=?',(row['assigned_staff_id'],)).fetchone() if row['assigned_staff_id'] else None
        if assigned:
            result['handler']={k:assigned[k] for k in ('name','team','phone','active')}
            result['handler']['has_account']=bool(assigned['user_id'])
        else:result['handler']=None
        result['events']=[dict(r) for r in db.execute('SELECT a.action,COALESCE(u.display_name,a.actor) AS actor,a.created_at FROM audit a LEFT JOIN users u ON u.id=a.actor WHERE resource_id=? ORDER BY a.id',(ticket_id,))]
    if not result['events']:result['events']=[{'action':'历史记录 · '+result['status'],'actor':result['assignee'],'created_at':result['updated_at']}]
    return result

@router.patch('/tickets/{ticket_id}')
def act(ticket_id:str,payload:WorkAction,user=Depends(current_user)):
    enforce_rate('work-action:'+user['id'],60,60)
    with storage.transaction(write=True,tables=('tickets',)) as (data,db):
        ticket=next((t for t in data['tickets'] if t['id']==ticket_id),None)
        staff=staff_for(db,user);admin=user['role']=='admin'
        if not ticket or not permitted(ticket,user,staff):raise HTTPException(404,'未找到该工单')
        if int(ticket.get('version',0))!=payload.expected_version:raise HTTPException(409,'工单已被其他人更新，请刷新详情后再操作')
        if ticket['status']=='已完成':raise HTTPException(409,'已完成工单不可继续修改')
        previous=ticket['status'];recipient=None
        if payload.action=='assign':
            if not admin:raise HTTPException(403,'仅管理员可以分派或改派')
            if previous not in ('待受理','处理中'):raise HTTPException(409,'请先将待确认工单退回处理，再改派')
            handler=db.execute('SELECT * FROM service_staff WHERE id=? AND active=1',(payload.staff_id,)).fetchone()
            if not handler:raise HTTPException(422,'请选择在岗处理人员，不可直接填写任意姓名')
            if payload.due_at and datetime.fromisoformat(payload.due_at)<=datetime.now(TZ):raise HTTPException(422,'预约处理时间须晚于当前时间')
            old_name=ticket['assignee']
            old_staff=db.execute('SELECT user_id FROM service_staff WHERE id=?',(ticket.get('assigned_staff_id',''),)).fetchone()
            if old_staff and old_staff['user_id'] and old_staff['user_id']!=handler['user_id']:
                notify(db,old_staff['user_id'],'reassigned:'+ticket_id+':'+str(payload.expected_version),'info','工单已改派',ticket_id+' 已从你的任务中移出。',ticket_id)
            ticket.update(assigned_staff_id=handler['id'],assignee=handler['name'],status='处理中')
            if payload.due_at is not None:ticket['due_at']=payload.due_at
            recipient=handler['user_id']
            action=('分派' if previous=='待受理' else '改派')+'给 '+handler['name']+'（'+handler['team']+'），原处理人：'+old_name
        elif payload.action in ('progress','report'):
            if not (admin or (staff and ticket.get('assigned_staff_id')==staff['id'])):raise HTTPException(403,'仅当前处理人员或管理员可填写处理反馈')
            if previous!='处理中':raise HTTPException(409,'请先分派并进入处理中')
            if not ticket.get('assigned_staff_id'):raise HTTPException(409,'历史工单尚未关联处理人员，请管理员先选择人员并分派')
            if payload.action=='report':ticket.update(status='待确认',resolution=payload.note)
            action=('提交处理结果，等待居民确认' if payload.action=='report' else '补充处理进展')+('（管理员代录）' if admin else '')
        else:
            if not (admin or ticket.get('owner_id')==user['id']):raise HTTPException(403,'仅提交居民或管理员可确认结果或要求返工')
            if previous!='待确认':raise HTTPException(409,'仅待确认工单可以确认或退回')
            if payload.action=='confirm' and not ticket.get('resolution'):raise HTTPException(409,'尚无处理结果，请退回处理并补充反馈后再确认')
            ticket['status']='已完成' if payload.action=='confirm' else '处理中'
            action=('管理员代确认完成（原因）' if admin and ticket.get('owner_id')!=user['id'] else '居民确认完成') if payload.action=='confirm' else '退回处理（原因）'
        ticket['version']=payload.expected_version+1;ticket['updated_at']=stamp()
        storage.audit(db,action+'：'+payload.note,ticket_id,user['id'])
        if not recipient:
            handler=db.execute('SELECT user_id FROM service_staff WHERE id=?',(ticket.get('assigned_staff_id',''),)).fetchone()
            recipient=handler['user_id'] if handler else None
        audience={ticket.get('owner_id'),recipient}
        for who in audience:
            if who:notify(db,who,'ticket:'+ticket_id+':'+str(ticket['version']),'ticket',action.split('（')[0],ticket_id+' · '+ticket['status']+' · '+payload.note,ticket_id)
        return ticket_view(ticket,user,staff)

@router.get('/notifications')
def notifications(user=Depends(current_user)):
    from app.api import activity_reminders
    reminders=activity_reminders(user)['items']
    today=datetime.now(TZ).date().isoformat()
    reminder_keys=['upcoming:'+a['id']+':'+a['date']+':'+today for a in reminders]
    # Materialize only this account's reminders, once per activity/day. This is
    # not an external push and never accepts a recipient from the browser.
    with storage.connection(write=True) as db:
        for item in reminders:
            notify(db,user['id'],'upcoming:'+item['id']+':'+item['date']+':'+today,'activity',item['title']+' · '+item['label'],item['date']+' '+item['time']+' · '+item['location'],item['id'])
        # Surface recent genuine legacy tickets on first use, not hundreds of samples.
        for ticket in db.execute("SELECT id,status,category,assignee,updated_at FROM tickets WHERE owner_id=? AND id NOT LIKE 'DEMO-%' AND updated_at>=? ORDER BY updated_at DESC LIMIT 20",(user['id'],(datetime.now(TZ)-timedelta(days=30)).date().isoformat())):
            if db.execute("SELECT 1 FROM notifications WHERE recipient_id=? AND resource_id=? AND kind='ticket' LIMIT 1",(user['id'],ticket['id'])).fetchone():continue
            notify(db,user['id'],'snapshot:'+ticket['id']+':'+ticket['updated_at'],'ticket','我的工单 · '+ticket['status'],ticket['category']+' · 处理人：'+ticket['assignee'],ticket['id'])
        visibility="kind<>'activity'" if not reminder_keys else "(kind<>'activity' OR event_key IN ("+','.join('?' for _ in reminder_keys)+'))'
        params=(user['id'],*reminder_keys)
        counts=db.execute("SELECT COUNT(*) AS total,COALESCE(SUM(CASE WHEN read_at='' THEN 1 ELSE 0 END),0) AS unread FROM notifications WHERE recipient_id=? AND "+visibility,params).fetchone()
        rows=[dict(r) for r in db.execute('SELECT * FROM notifications WHERE recipient_id=? AND '+visibility+' ORDER BY created_at DESC,id DESC LIMIT 100',params)]
    return {'items':[{k:v for k,v in r.items() if k not in ('recipient_id','event_key')} for r in rows],'unread':counts['unread'],'limited':counts['total']>100}

@router.post('/notifications/read-all')
def read_all(user=Depends(current_user)):
    with storage.connection(write=True) as db:db.execute("UPDATE notifications SET read_at=? WHERE recipient_id=? AND read_at=''",(stamp(),user['id']))
    return {'ok':True}

@router.post('/notifications/{notification_id}/read')
def read_one(notification_id:str,user=Depends(current_user)):
    with storage.connection(write=True) as db:
        row=db.execute('SELECT id FROM notifications WHERE id=? AND recipient_id=?',(notification_id,user['id'])).fetchone()
        if not row:raise HTTPException(404,'通知不存在')
        db.execute("UPDATE notifications SET read_at=? WHERE id=? AND recipient_id=? AND read_at=''",(stamp(),notification_id,user['id']))
    return {'ok':True}
