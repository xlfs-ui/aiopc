from __future__ import annotations
import importlib.util
import logging
import os
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from app import storage, config
from app.auth import router as auth_router
from app.api import router as business_router
from app.security import SecurityMiddleware

POLICIES = [
    {
        "id": "P-001", "title": "高龄津贴申请指南", "category": "养老服务", "updated_at": "2026-09-15",
        "summary": "具有本社区户籍或符合属地服务要求的高龄老人，可按年龄档申请高龄津贴。具体年龄门槛和金额以杭州市及所在街道最新口径为准。",
        "steps": ["准备身份证、户口簿及银行卡信息", "向所在社区服务窗口提交申请", "等待街道审核并按月发放"],
        "source": "杭州市民政局 · 高龄津贴办事指南", "phone": "0571-12345",
        "keywords": ["高龄", "老人", "养老", "津贴", "补贴"],
    },
    {
        "id": "P-002", "title": "居住证办理与签注", "category": "居住服务", "updated_at": "2026-08-28",
        "summary": "居住证办理通常需要有效身份证明、居住地址证明及符合规定的居住登记记录。办理条件可能因个人情况不同而不同。",
        "steps": ["先确认居住登记信息完整", "准备身份证明和居住证明材料", "通过浙里办或属地服务窗口提交"],
        "source": "浙江政务服务网 · 居住证办理事项", "phone": "0571-12345",
        "keywords": ["居住证", "居住登记", "签注", "租房"],
    },
    {
        "id": "P-003", "title": "最低生活保障申请咨询", "category": "社会救助", "updated_at": "2026-09-02",
        "summary": "低保认定需综合核查家庭收入、财产及共同生活家庭成员情况。系统仅提供办事信息，最终资格以民政部门审核结果为准。",
        "steps": ["联系社区社会救助窗口做初步咨询", "按工作人员指引提交家庭情况材料", "配合街道及相关部门核查"],
        "source": "杭州市民政局 · 社会救助服务指引", "phone": "0571-12345",
        "keywords": ["低保", "最低生活保障", "救助", "困难"],
    },
    {
        "id": "P-004", "title": "退役军人优待服务咨询", "category": "优待服务", "updated_at": "2026-07-20",
        "summary": "退役军人可向属地退役军人服务站咨询优待政策、优待证服务及相关办事事项。具体资格和材料以主管部门答复为准。",
        "steps": ["联系所在街道退役军人服务站", "说明个人情况并确认适用政策", "按要求提交材料或预约办理"],
        "source": "杭州市退役军人事务局 · 服务信息", "phone": "0571-12345",
        "keywords": ["退役军人", "优待证", "军人", "优待"],
    },
]

ACTIVITIES = [
    {"id": "A-1001", "title": "银龄健康义诊", "category": "健康服务", "date": "2026-10-24", "time": "09:00–11:30", "location": "云水社区党群服务中心一楼", "capacity": 40, "registered": 28, "audience": "60岁及以上居民", "description": "血压血糖筛查、慢病咨询与家庭医生现场答疑。", "tag": "本周六"},
    {"id": "A-1002", "title": "反诈安全小课堂", "category": "便民讲座", "date": "2026-10-26", "time": "14:00–15:00", "location": "云水社区活动室", "capacity": 60, "registered": 36, "audience": "全体居民", "description": "民警讲解常见电信网络诈骗识别方法，现场答疑。", "tag": "免费报名"},
    {"id": "A-1003", "title": "秋日亲子手作活动", "category": "亲子活动", "date": "2026-10-29", "time": "15:30–17:00", "location": "云水社区儿童之家", "capacity": 20, "registered": 12, "audience": "亲子家庭", "description": "利用秋日自然材料制作手工作品，名额有限。", "tag": "剩余8席"},
]

TICKETS: list[dict] = [
    {"id": "YS-2026-0318", "resident": "林女士", "phone": "138****6218", "location": "3幢 2单元 5楼", "category": "公共照明", "description": "走廊灯泡坏了，晚上楼道比较暗。", "status": "处理中", "assignee": "王师傅", "created_at": "今天 09:42", "updated_at": "今天 10:15", "priority": "普通"},
    {"id": "YS-2026-0317", "resident": "陈先生", "phone": "137****0832", "location": "小区东门", "category": "道路设施", "description": "入口旁边路面有一处坑洼，雨天容易积水。", "status": "待受理", "assignee": "待指派", "created_at": "今天 08:26", "updated_at": "今天 08:26", "priority": "较急"},
    {"id": "YS-2026-0316", "resident": "赵女士", "phone": "匿名用户", "location": "5幢楼下", "category": "环境卫生", "description": "垃圾桶周边需要清理。", "status": "待确认", "assignee": "社区网格员", "created_at": "昨天 16:08", "updated_at": "昨天 17:20", "priority": "普通"},
    {"id": "YS-2026-0315", "resident": "周先生", "phone": "159****1480", "location": "1幢 1单元", "category": "公共设施", "description": "楼道扶手有些松动，麻烦检查一下。", "status": "已完成", "assignee": "刘师傅", "created_at": "昨天 10:33", "updated_at": "昨天 14:02", "priority": "普通"},
]

REGISTRATIONS: list[dict] = [
    {"activity_id": "A-1001", "resident": "林女士", "created_at": "2026-10-18"},
    {"activity_id": "A-1002", "resident": "陈先生", "created_at": "2026-10-17"},
]


COLLECTIONS={'policies':POLICIES,'activities':ACTIVITIES,'tickets':TICKETS,'registrations':REGISTRATIONS}
storage.load_or_seed(COLLECTIONS)
if config.PRODUCTION:
    from app.bootstrap import bootstrap_admin
    bootstrap_admin()

app=FastAPI(title="邻里智服 Agent API",version="0.2.0",docs_url=None if config.PRODUCTION else '/docs',redoc_url=None if config.PRODUCTION else '/redoc',openapi_url=None if config.PRODUCTION else '/openapi.json')
app.add_middleware(SecurityMiddleware)
app.add_middleware(CORSMiddleware,allow_origins=config.ALLOWED_ORIGINS,allow_credentials=True,allow_methods=['GET','POST','PUT','PATCH','DELETE'],allow_headers=['Content-Type','X-CSRF-Token','Idempotency-Key'])
app.add_middleware(TrustedHostMiddleware,allowed_hosts=config.TRUSTED_HOSTS)
app.include_router(auth_router)
app.include_router(business_router)
from app.knowledge import router as knowledge_router
app.include_router(knowledge_router)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request,exc: RequestValidationError):
    # Pydantic input/ctx can contain passwords: never echo them to a response.
    errors=[{'loc':list(e['loc']),'msg':e['msg'],'type':e['type']} for e in exc.errors()]
    return JSONResponse(status_code=422,content={'detail':errors})


@app.exception_handler(Exception)
async def unexpected_error(request: Request,exc: Exception):
    logging.getLogger(__name__).error('Unhandled request error: %s',type(exc).__name__)
    return JSONResponse(status_code=500,content={'detail':'服务暂时不可用，请稍后重试'},headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})


@app.get('/api/health')
def health():
    ready=bool(os.getenv('DEEPSEEK_API_KEY','').strip()) and importlib.util.find_spec('langgraph') is not None
    return {'status':'ok','mode':'deepseek-langgraph' if ready else 'local-search','storage':'postgresql' if storage.is_postgres() else 'sqlite'}


from app.web import mount_frontend
mount_frontend(app)


if __name__=='__main__':
    import uvicorn
    uvicorn.run('app.main:app',host='127.0.0.1',port=8000,reload=not config.PRODUCTION,proxy_headers=False)
