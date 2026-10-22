"""Explicit, one-time sample dataset. No real user rows are overwritten."""
import hashlib
import json
import logging
from datetime import timedelta
from app import storage
from app.civic import now, classify, analyze, report_markdown
from app import retrieval

BATCH='community-demo-v1'
MARKER=100001
AREAS=[('云水花园（演示）','第一网格',128),('春和小区（演示）','第二网格',96),('邻里公寓（演示）','第三网格',72),('滨河家园（演示）','第四网格',156)]
CASES=[('公共照明','3幢楼道灯不亮，晚间通行不便，请安排检查。'),('公共设施','门口有车辆占道停车，建议核查车位引导与通行情况。'),('噪音问题','晚间公共区域有噪音，希望工作人员帮助沟通。'),('环境卫生','垃圾点位附近蚊虫较多，希望安排清理和虫害巡查。'),('给排水','公共水管有漏水现象，请协助排查。'),('道路设施','步行道路出现坑洼，建议安排现场核查。'),('公共设施','公共区域扶手松动，请检查固定情况。')]


def seed_demo():
    clock=now(); today=clock.date(); stamp=clock.isoformat()
    with storage.connection(write=True) as db:
        marker=db.execute('SELECT payload FROM snapshots WHERE id=?',(MARKER,)).fetchone()
        if marker:
            summary=json.loads(marker[0])
            if summary.get('batch')!=BATCH: raise RuntimeError('Sample dataset marker collision')
            admin_id=summary['owner_id']
        else:
            admin=db.execute("SELECT id,username FROM users WHERE role='admin' ORDER BY CASE WHEN username='community_admin' THEN 0 ELSE 1 END,created_at LIMIT 1").fetchone()
            if not admin: raise RuntimeError('Create an administrator before adding the sample dataset')
            admin_id=admin['id']
            counts={'residents':0,'places':0,'tickets':0,'consultations':0,'activities':0,'registrations':0,'policies':0,'documents':0}
            positions={table:db.execute('SELECT COALESCE(MAX(_position),-1) FROM '+table).fetchone()[0]+1 for table in storage.BUSINESS}
            def business(table,row):
                identifier=row['id']
                if db.execute('SELECT 1 FROM '+table+' WHERE id=?',(identifier,)).fetchone(): raise RuntimeError('Sample identifier collision; existing records retained')
                storage._upsert(db,table,row,positions[table]); positions[table]+=1; counts[table]+=1
            people=[]
            for i in range(12):
                identifier=f'demo-resident-v1-{i+1:02d}'
                username=f'demo_resident_v1_{i+1:02d}'
                if db.execute('SELECT 1 FROM users WHERE id=? OR username=?',(identifier,username)).fetchone(): raise RuntimeError('Sample user collision; no existing account changed')
                name=['林晓','陈晨','周悦','赵宁','王晴','刘安','许航','李可','郑心','吴南','孙禾','冯溪'][i]
                created=(clock-timedelta(days=85-i*4)).isoformat()
                db.execute('INSERT INTO users VALUES (?,?,?,?,?,?)',(identifier,username,'演示居民·'+name,'!disabled-demo-v1','resident',created))
                people.append(identifier); counts['residents']+=1
            for i,(name,zone,households) in enumerate(AREAS):
                db.execute('INSERT INTO civic_places VALUES (?,?,?,?,?,?,?)',(f'demo-place-v1-{i+1}',name,zone,'小区',households,'仅用于功能演示：关注公共照明、停车秩序及卫生巡查；不是实际辖区资料。',stamp)); counts['places']+=1
            for i,person in enumerate(people):
                db.execute('INSERT INTO civic_resident_links VALUES (?,?,?)',(person,f'demo-place-v1-{i%4+1}',stamp))
            serial=0
            for offset in range(180):
                quantity=1+(offset*5+3)%3+(1 if offset<30 else 0)
                for slot in range(quantity):
                    serial+=1
                    case=1 if offset<30 and slot==0 else (offset+slot*2)%len(CASES)
                    category,description=CASES[case]
                    owner=admin_id if serial%5==0 else people[serial%len(people)]
                    status=['待受理','处理中','待确认','已完成'][serial%4] if offset<10 else ('处理中' if serial%8==0 else '已完成')
                    created=(clock-timedelta(days=offset,hours=(slot*3)%9)).replace(hour=9+slot*2,minute=(serial*7)%60).isoformat()
                    identifier=f'DEMO-TICKET-V1-{serial:04d}'
                    business('tickets',{'id':identifier,'owner_id':owner,'resident':'演示居民（本人预览）' if owner==admin_id else '演示居民·'+str(serial%12+1),'phone':'','location':AREAS[(offset+slot)%4][0]+f' {serial%6+1}幢公共区域','category':category,'description':'【演示工单】'+description,'status':status,'assignee':'待指派' if status=='待受理' else ['演示·网格员小许','演示·物业维修组','演示·环境服务组'][serial%3],'created_at':created,'updated_at':created,'priority':'较急' if serial%11==0 else '普通'})
                    storage.audit(db,'演示工单创建',identifier,admin_id)
                    if status!='待受理': storage.audit(db,'演示状态：'+status,identifier,admin_id)
                for q in range(3+offset%4+(3 if offset<20 else 0)):
                    topic=['居住办事','养老救助','停车管理','公共照明','社区活动','虫害防治','邻里噪音'][(offset+q)%7]
                    event=f'demo-consult-v1-{offset:03d}-{q:02d}'
                    when=(clock-timedelta(days=offset)).replace(hour=10+q%8,minute=q*7%60).isoformat()
                    db.execute('INSERT INTO civic_events VALUES (?,?,?)',(event,topic,when)); counts['consultations']+=1
            activity_titles=['邻里健康义诊','亲子自然手作','社区防诈讲堂','旧物交换集市','长者手机课堂','志愿者巡园行动']
            for i,title in enumerate(activity_titles):
                activity_id=f'DEMO-ACTIVITY-V1-{i+1:02d}'
                business('activities',{'id':activity_id,'title':'【演示】'+title,'category':['健康服务','亲子活动','便民讲座','邻里互助','数字助老','志愿服务'][i],'date':(today+timedelta(days=2+i*3)).isoformat(),'time':'09:00–11:00' if i%2==0 else '14:00–16:00','location':AREAS[i%4][0]+'邻里中心','capacity':24+i*6,'registered':0,'audience':'社区居民（演示活动）','description':'这是功能演示活动，不是真实邀约。可体验活动检索、名额统计和报名；请勿据此前往现场。','tag':'演示 · 可体验报名'})
                participants=people[:4+i]+([admin_id] if i==0 else [])
                for j,owner in enumerate(participants):
                    business('registrations',{'id':f'{activity_id}:{owner}','activity_id':activity_id,'owner_id':owner,'resident':'演示报名居民' if owner!=admin_id else '演示报名（本人预览）','created_at':(clock-timedelta(hours=j+2)).isoformat()})
            for i,(title,category,words) in enumerate([('停车与公共通道','物业服务',['停车','车位','占道']),('公共照明报修','便民服务',['楼道灯','照明','报修']),('蚊虫与环境卫生反馈','环境服务',['虫害','蚊虫','垃圾']),('噪音问题沟通','邻里服务',['噪音','邻里','协调']),('社区活动报名','活动服务',['报名','活动','名额']),('新网格员交接清单','社区工作',['网格','交接','民情'])]):
                row={'id':f'DEMO-POLICY-V1-{i+1:02d}','title':'【演示指引】'+title,'category':category,'summary':'用于展示资料检索与办理步骤，不代表真实政策或办事承诺。可描述具体问题，核对检索结果，再通过站内服务入口办理。','steps':['记录问题所在公共区域与具体情况','在智能助手或服务入口查找对应事项','核对信息后提交工单或查看活动，结果以实际工作人员答复为准'],'source':'演示知识资料 · 非官方政策','phone':'','keywords':words+['演示'],'updated_at':today.isoformat()}
                business('policies',row); retrieval.index_policy(db,row)
            from app.knowledge import public_document, split_pages
            texts=[('停车与公共通道服务说明','【演示文档】这是虚构社区的功能展示资料，不是真实规定。停车占道问题可通过报修入口反馈，描述地点和通行影响。不要在公开描述中上传身份证号、车主电话等敏感信息。工作人员需先现场核查，再协调物业处理。'),('照明与虫害反馈流程','【演示文档】本资料仅用于检索引用展示。楼道灯、路灯故障可提交公共照明工单；蚊虫与垃圾点位问题可提交环境卫生诉求。描述现象、时间与公共区域，不必提供无关个人信息。可在我的工单查看后续状态。'),('新网格员入职交接手册','【演示文档】先查看民情分析中的咨询热点、区域排行及未完成事项。再核对人房事底册中的网格、地点与备注。统计包含演示样本时，不能用于实际资源调度。演示报告展示统计口径，不作资格、责任或矛盾性质认定。'),('待审核的社区活动草稿','【演示草稿】仅管理员可见，用于体验文档审核发布。请核实真实活动信息后再发布正式资料。')]
            for i,(title,content) in enumerate(texts):
                document_id=f'demo-document-v1-{i+1}'; status='draft' if i==3 else 'published'
                db.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(document_id,document_id,1,'【演示】'+title,'演示资料 · 非官方政策','',f'演示资料-{i+1}.txt',hashlib.sha256(content.encode()).hexdigest(),content,content.encode(),status,(today-timedelta(days=7)).isoformat(),'',admin_id,stamp,stamp))
                row=db.execute('SELECT * FROM documents WHERE id=?',(document_id,)).fetchone()
                for j,chunk in enumerate(split_pages([(None,content)])):
                    chunk_id=f'{document_id}:{j}'
                    db.execute('INSERT INTO document_chunks VALUES (?,?,?,?,?,?,?)',(chunk_id,document_id,j,chunk['page'],chunk['content'],chunk['start_offset'],chunk['end_offset']))
                    if status=='published': retrieval.index_chunk(db,chunk_id,'document',document_id,row['title'],chunk['content'],{**public_document(row),'page':None,'ordinal':j,'chunk_id':chunk_id})
                counts['documents']+=1
            summary={'batch':BATCH,'seeded_at':stamp,'owner_id':admin_id,'owner_username':admin['username'],'counts':counts,'note':'全部为虚构演示记录；未改写已有记录；演示居民账号禁用登录。'}
            db.execute('INSERT INTO snapshots VALUES (?,?)',(MARKER,json.dumps(summary,ensure_ascii=False)))
            storage.audit(db,'导入演示数据批次',BATCH,admin_id)
    for days in (7,30,90):
        identifier=f'demo-report-v1-{days}'
        with storage.connection() as db: exists=db.execute('SELECT 1 FROM civic_reports WHERE id=?',(identifier,)).fetchone()
        if exists: continue
        data=analyze(days); report={'id':identifier,'created_at':stamp,'days':days,'title':f'【演示样本】近{days}天民情分析','markdown':report_markdown(data),'data':data,'is_sample':True}
        with storage.connection(write=True) as db:
            db.execute('INSERT INTO civic_reports VALUES (?,?,?,?,?) ON CONFLICT(id) DO NOTHING',(identifier,stamp,admin_id,days,json.dumps(report,ensure_ascii=False)))
    with storage.connection() as db:
        reports=db.execute("SELECT COUNT(*) FROM civic_reports WHERE id IN (?,?,?)",tuple(f'demo-report-v1-{d}' for d in (7,30,90))).fetchone()[0]
    logging.getLogger('uvicorn.error').info('Sample dataset ready: %s; reports=%s',json.dumps(summary['counts']),reports)
    return {**summary,'reports':reports}


def seed_if_requested():
    import os
    if os.getenv('DEMO_SEED_BATCH','')==BATCH: return seed_demo()
    return None
