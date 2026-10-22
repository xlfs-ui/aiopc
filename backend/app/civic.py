"""Administrator-only civic analytics. Deterministic, explainable aggregates."""
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from app import storage
from app.auth import require_admin, enforce_rate

SCHEMA=[
    'CREATE TABLE IF NOT EXISTS civic_events (id TEXT PRIMARY KEY, topic TEXT NOT NULL, occurred_at TEXT NOT NULL)',
    'CREATE INDEX IF NOT EXISTS civic_event_date ON civic_events(occurred_at)',
    'CREATE TABLE IF NOT EXISTS civic_reports (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, created_by TEXT NOT NULL, days INTEGER NOT NULL, payload TEXT NOT NULL)',
    'CREATE INDEX IF NOT EXISTS civic_report_date ON civic_reports(created_at)',
    "CREATE TABLE IF NOT EXISTS civic_places (id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, zone TEXT NOT NULL, kind TEXT NOT NULL, households INTEGER NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL)",
    'CREATE TABLE IF NOT EXISTS civic_resident_links (user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, place_id TEXT NOT NULL REFERENCES civic_places(id), updated_at TEXT NOT NULL)',
]
router=APIRouter(prefix='/api/civic',tags=['civic-analytics'],dependencies=[Depends(require_admin)])
TOPICS=[('停车管理',('停车','车位','乱停','占道')),('公共照明',('照明','路灯','楼道灯','灯泡','灯坏')),('虫害防治',('蚊','蟑螂','虫','老鼠','鼠患')),('邻里噪音',('噪音','噪声','吵','纠纷','争执')),('环境卫生',('垃圾','卫生','清洁','异味')),('给排水',('漏水','水管','排水','积水','下水')),('道路设施',('道路','路面','坑洼','井盖')),('公共设施',('电梯','扶手','设施','报修','维修')),('养老救助',('老人','高龄','养老','低保','救助','津贴')),('居住办事',('居住证','户籍','落户','居住登记')),('社区活动',('活动','报名','义诊','亲子'))]
TZ=timezone(timedelta(hours=8))


def now(): return datetime.now(TZ)
def classify(text):
    return next((name for name,words in TOPICS if any(word in text for word in words)),'其他咨询')


def record_consultation(text,event_key):
    # Keep no raw question, address, account identifier, or model response.
    with storage.connection(write=True) as db:
        db.execute('DELETE FROM civic_events WHERE occurred_at<?',((now()-timedelta(days=365)).isoformat(),))
        db.execute('INSERT INTO civic_events VALUES (?,?,?) ON CONFLICT(id) DO NOTHING',(hashlib.sha256(event_key.encode()).hexdigest(),classify(text),now().isoformat()))


def day_of(value):
    try:
        parsed=datetime.fromisoformat(value)
        if len(value)>10:
            from app import config
            if parsed.tzinfo is None: parsed=parsed.replace(tzinfo=timezone.utc if config.PRODUCTION else TZ)
            return parsed.astimezone(TZ).date()
        return parsed.date()
    except (ValueError,TypeError): return None


def area_of(location,places):
    for place in sorted(places,key=lambda p:len(p['name']),reverse=True):
        if place['name'] in location: return place['name']
    match=re.search(r'([\u4e00-\u9fffA-Za-z0-9]{2,18}(?:小区|社区|花园|公寓))',location)
    if match: return match[1]
    match=re.search(r'([一二三四五六七八九十\d]+\s*(?:幢|栋|号楼))',location)
    return match[1] if match else '其他 / 未归属区域'


def demo_data(days):
    today=now().date(); tickets=[]; events=[]
    for i in range(days*3):
        when=today-timedelta(days=i%(days*2))
        category=['公共照明','公共设施','噪音问题','环境卫生'][i%4]
        description=['楼道灯不亮','停车占道','晚间噪音','蚊虫较多'][i%4]
        tickets.append({'id':f'DEMO-{i}','created_at':when.isoformat(),'category':category,'description':description,'location':['云水花园 3幢','春和小区 2栋','云水花园 东门'][i%3],'status':'已完成' if i%3==0 else '待受理','priority':'较急' if i%9==0 else '普通'})
    for i in range(days*5): events.append({'topic':['居住办事','公共照明','养老救助','停车管理'][i%4],'occurred_at':(today-timedelta(days=i%(days*2))).isoformat()})
    return tickets,events


def analyze(days=30,demo=False):
    today=now().date(); start=today-timedelta(days=days-1); previous=start-timedelta(days=days)
    with storage.connection() as db:
        places=[dict(r) for r in db.execute('SELECT * FROM civic_places ORDER BY name')]
        tickets=storage._read_business(db,('tickets',))['tickets']
        events=[dict(r) for r in db.execute('SELECT topic,occurred_at FROM civic_events WHERE occurred_at>=?',(previous.isoformat(),))]
        people=db.execute("SELECT COUNT(*) FROM users WHERE role='resident'").fetchone()[0]
        linked=db.execute('SELECT COUNT(*) FROM civic_resident_links').fetchone()[0]
        published=db.execute("SELECT COUNT(*) FROM documents WHERE status='published'").fetchone()[0]
    if demo: tickets,events=demo_data(days)
    dated=[(t,day_of(t['created_at'])) for t in tickets]
    current=[t for t,d in dated if d and start<=d<=today]
    old=[t for t,d in dated if d and previous<=d<start]
    queries=[e for e in events if (d:=day_of(e['occurred_at'])) and start<=d<=today]
    topic=lambda t:classify(t['description']+' '+t['category'])
    counts=Counter(topic(t) for t in current); before=Counter(topic(t) for t in old)
    topics=[]
    for name in sorted(counts.keys()|before.keys(),key=lambda x:(-counts[x],x)):
        count,prior=counts[name],before[name]
        topics.append({'name':name,'count':count,'previous':prior,'delta':count-prior,'change_pct':round((count-prior)/prior*100,1) if prior else None,'signal':'样本不足' if count+prior<5 else '新增关注' if prior==0 else '上升' if count>prior else '下降' if count<prior else '持平'})
    areas=Counter(area_of(t['location'],places) for t in current)
    series=[{'date':(start+timedelta(days=i)).isoformat(),'tickets':sum(day_of(t['created_at'])==start+timedelta(days=i) for t in current),'consultations':sum(day_of(e['occurred_at'])==start+timedelta(days=i) for e in queries)} for i in range(days)]
    pending=sum(t['status']!='已完成' for t in current)
    suggestions=[]
    actions={'公共照明':'按区域核查灯具和供电情况，合并安排巡检。','停车管理':'现场确认高峰时段与通行影响，再协调物业调整停车引导。','虫害防治':'核查积水和垃圾点位，再安排清洁及专业消杀。','邻里噪音':'核实发生时段与具体情形，优先开展沟通协调。','给排水':'排查漏水或积水原因，评估是否需要专业维修。'}
    for t in topics[:4]:
        if not t['count']: continue
        suggestions.append({'topic':t['name'],'evidence':f"本期 {t['count']} 件，上期 {t['previous']} 件，变化 {t['delta']:+d} 件。",'action':actions.get(t['name'],'复核集中问题，按职责安排工作人员跟进，并记录处理结果。'),'priority':'优先核查' if t['count']>=5 and t['delta']>0 else '常规跟进'})
    invalid=sum(d is None for _,d in dated)
    return {'days':days,'start':start.isoformat(),'end':today.isoformat(),'generated_at':now().isoformat(),'demo':demo,
            'metrics':{'consultations':len(queries),'tickets':len(current),'previous_tickets':len(old),'pending':pending,'completion_rate':round((len(current)-pending)/len(current)*100) if current else 0,'areas':len(areas)},
            'daily':series,'consultation_topics':[{'name':k,'count':v} for k,v in Counter(e['topic'] for e in queries).most_common(12)],'topics':topics,'areas':[{'name':k,'count':v,'pending':sum(area_of(t['location'],places)==k and t['status']!='已完成' for t in current)} for k,v in areas.most_common(12)],'suggestions':suggestions,
            'ledger':{'residents':people,'places':len(places),'households':sum(p['households'] for p in places),'linked_residents':linked,'published_documents':published},
            'quality':{'undated_tickets':invalid,'unassigned_tickets':areas.get('其他 / 未归属区域',0),'notes':['咨询为本功能上线后完成对话的次数，不等于独立人数；分类使用可解释关键词规则。','环比比较此前相同天数；两期合计不足 5 件时提示样本不足，不据此判定社会矛盾升级。','区域按地点底册名称或楼栋文字归并，未匹配记录单列；非标准日期不纳入趋势。','建议为统计辅助，不代表原因认定或自动派单；需工作人员核实。']}}


def report_markdown(data):
    m=data['metrics']
    lines=['# 社区民情需求分析报告',f"统计周期：{data['start']} 至 {data['end']}（北京时间）",'数据模式：'+('演示数据，不用于实际调度' if data['demo'] else '真实业务数据'),f"咨询 {m['consultations']} 次；诉求 {m['tickets']} 件；待完成 {m['pending']} 件；完成率 {m['completion_rate']}%。",'## 热门咨询']
    lines += [f"- {t['name']}：{t['count']} 次" for t in data['consultation_topics']] or ['- 暂无可统计咨询。']
    lines += ['## 诉求变化']+[f"- {t['name']}：本期 {t['count']} 件，上期 {t['previous']} 件；{t['signal']}。" for t in data['topics']]
    lines += ['## 区域分布']+[f"- {a['name']}：{a['count']} 件，其中 {a['pending']} 件未完成。" for a in data['areas']]
    lines += ['## 资源安排建议']+[f"- {s['topic']}（{s['priority']}）：{s['evidence']} {s['action']}" for s in data['suggestions']]
    lines += ['## 新网格员交接提示','先阅读高频诉求与未完成事项，再结合地点底册定位区域；按职责核实并跟进，不能凭报告直接判断个体资格或责任。','## 数据口径与限制']+['- '+n for n in data['quality']['notes']]
    if data['quality']['undated_tickets']: lines.append(f"- {data['quality']['undated_tickets']} 件历史记录日期不规范，未计入趋势。")
    return '\n\n'.join(lines)


@router.get('/analytics')
def analytics(days:Literal[7,30,90]=30,demo:bool=False,user=Depends(require_admin)):
    enforce_rate('civic-read:'+user['id'],30,60)
    return analyze(days,demo)


class ReportInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    days:Literal[7,30,90]=30


@router.post('/reports',status_code=201)
def create_report(payload:ReportInput,user=Depends(require_admin)):
    enforce_rate('civic-report:'+user['id'],6,60)
    data=analyze(payload.days); identifier=str(uuid4()); created=now().isoformat()
    report={'id':identifier,'created_at':created,'days':payload.days,'title':f"{data['start']}—{data['end']} 民情分析",'markdown':report_markdown(data),'data':data}
    with storage.connection(write=True) as db:
        if db.execute('SELECT COUNT(*) FROM civic_reports').fetchone()[0]>=1000: raise HTTPException(409,'已保存 1000 份报告，请先清理不再需要的历史报告')
        db.execute('INSERT INTO civic_reports VALUES (?,?,?,?,?)',(identifier,created,user['id'],payload.days,json.dumps(report,ensure_ascii=False)))
        storage.audit(db,'生成民情报告',identifier,user['id'])
    return report


@router.get('/reports')
def list_reports():
    with storage.connection() as db: return [{'id':r['id'],'created_at':r['created_at'],'days':r['days']} for r in db.execute('SELECT id,created_at,days FROM civic_reports ORDER BY created_at DESC LIMIT 50')]


@router.get('/reports/{identifier}')
def get_report(identifier:str):
    with storage.connection() as db: row=db.execute('SELECT payload FROM civic_reports WHERE id=?',(identifier,)).fetchone()
    if not row: raise HTTPException(404,'报告不存在')
    return json.loads(row[0])


@router.delete('/reports/{identifier}')
def delete_report(identifier:str,user=Depends(require_admin)):
    with storage.connection(write=True) as db:
        if db.execute('DELETE FROM civic_reports WHERE id=?',(identifier,)).rowcount==0: raise HTTPException(404,'报告不存在')
        storage.audit(db,'删除民情报告',identifier,user['id'])
    return {'message':'报告已删除'}


class PlaceInput(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    name:str=Field(min_length=2,max_length=50)
    zone:str=Field(min_length=1,max_length=40)
    kind:Literal['小区','楼栋','公共空间']='小区'
    households:int=Field(default=0,ge=0,le=100000)
    note:str=Field(default='',max_length=300)


@router.get('/ledger')
def ledger():
    with storage.connection() as db:
        return {'places':[dict(r) for r in db.execute('SELECT * FROM civic_places ORDER BY name')],
                'residents':[dict(r) for r in db.execute("SELECT u.id,u.display_name,u.username,l.place_id FROM users u LEFT JOIN civic_resident_links l ON l.user_id=u.id WHERE u.role='resident' ORDER BY u.created_at DESC LIMIT 300")],
                'resident_limit':300}


@router.post('/places',status_code=201)
def create_place(payload:PlaceInput,user=Depends(require_admin)):
    import sqlite3
    identifier=str(uuid4())
    try:
        with storage.connection(write=True) as db:
            if db.execute('SELECT COUNT(*) FROM civic_places').fetchone()[0]>=2000: raise HTTPException(409,'地点数量已达上限')
            db.execute('INSERT INTO civic_places VALUES (?,?,?,?,?,?,?)',(identifier,payload.name,payload.zone,payload.kind,payload.households,payload.note,now().isoformat()))
            storage.audit(db,'添加底册地点',identifier,user['id'])
    except sqlite3.IntegrityError: raise HTTPException(409,'地点名称已存在') from None
    return {'id':identifier}


@router.put('/places/{identifier}')
def update_place(identifier:str,payload:PlaceInput,user=Depends(require_admin)):
    import sqlite3
    try:
        with storage.connection(write=True) as db:
            count=db.execute('UPDATE civic_places SET name=?,zone=?,kind=?,households=?,note=? WHERE id=?',(payload.name,payload.zone,payload.kind,payload.households,payload.note,identifier)).rowcount
            if count==0: raise HTTPException(404,'地点不存在')
            storage.audit(db,'更新底册地点',identifier,user['id'])
    except sqlite3.IntegrityError: raise HTTPException(409,'地点名称已存在') from None
    return {'id':identifier}


@router.delete('/places/{identifier}')
def delete_place(identifier:str,user=Depends(require_admin)):
    with storage.connection(write=True) as db:
        if db.execute('SELECT 1 FROM civic_resident_links WHERE place_id=? LIMIT 1',(identifier,)).fetchone(): raise HTTPException(409,'请先解除此地点的居民关联')
        if db.execute('DELETE FROM civic_places WHERE id=?',(identifier,)).rowcount==0: raise HTTPException(404,'地点不存在')
        storage.audit(db,'删除底册地点',identifier,user['id'])
    return {'message':'地点已删除'}


class LinkInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    place_id:str|None=Field(default=None,max_length=64)


@router.put('/residents/{identifier}/place')
def link_place(identifier:str,payload:LinkInput,user=Depends(require_admin)):
    with storage.connection(write=True) as db:
        if not db.execute("SELECT 1 FROM users WHERE id=? AND role='resident'",(identifier,)).fetchone(): raise HTTPException(404,'居民账号不存在')
        if payload.place_id:
            if not db.execute('SELECT 1 FROM civic_places WHERE id=?',(payload.place_id,)).fetchone(): raise HTTPException(404,'地点不存在')
            db.execute('INSERT INTO civic_resident_links VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET place_id=excluded.place_id,updated_at=excluded.updated_at',(identifier,payload.place_id,now().isoformat()))
        else: db.execute('DELETE FROM civic_resident_links WHERE user_id=?',(identifier,))
        storage.audit(db,'更新居民地点关联',identifier,user['id'])
    return {'message':'居民地点关联已更新'}
