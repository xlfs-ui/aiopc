"""Shared retrieval and allowlisted UI actions, independent of LLM packages."""
import re

SERVICES = [
    {"id": "service-repair", "kind": "service", "title": "报事报修 · 问题登记", "description": "灯坏了、漏水、公共设施损坏？填写位置和问题，由社区受理并跟进。", "keywords": "报修 维修 报事 灯 路灯 漏水 垃圾 噪音 坏了 登记 提交工单", "steps": ["描述具体位置和问题", "核对并提交报修表单", "社区受理并安排人员", "查看处理进度与结果"], "materials": ["问题位置", "问题描述", "联系电话（可选）"], "action": {"type": "create_ticket", "label": "填写报修单"}},
    {"id": "service-tickets", "kind": "service", "title": "我的工单 · 处理进度", "description": "查询本人提交的诉求、处理人和最新状态。", "keywords": "我的工单 进度 处理 状态 记录 查询 报修记录", "steps": ["进入我的工单", "选择对应工单", "查看状态、处理人和流转记录"], "action": {"type": "open_tickets", "label": "查看我的工单"}},
    {"id": "service-policy", "kind": "service", "title": "政策查询 · 办事指引", "description": "查找本地政策、准备材料和办理步骤，查看资料来源。", "keywords": "政策 办事 指南 流程 程序 材料 申请 补贴 服务 养老 居住", "steps": ["检索办理事项", "核对资料来源与更新时间", "按指引准备材料并咨询服务窗口"], "action": {"type": "open_policies", "label": "进入政策资料库"}},
    {"id": "service-activities", "kind": "service", "title": "社区活动 · 浏览报名", "description": "查看近期活动、时间地点、适合人群和剩余名额。", "keywords": "活动 报名 参加 义诊 讲座 亲子 健康 反诈", "steps": ["选择活动并核对时间地点", "确认适合人群和名额", "在活动页点击报名"], "action": {"type": "open_activities", "label": "查看可报名活动"}},
]


def relevance(query: str, text: str, keywords: list[str] | None = None) -> float:
    query, text = query.lower().strip(), text.lower()
    if not query:
        return 1
    tokens = re.findall(r"[a-z0-9-]+|[\u4e00-\u9fff]", query)
    grams = set("".join(tokens[i:i + 2]) for i in range(len(tokens) - 1))
    score = sum(1 for gram in grams if gram in text)
    score += sum(5 for word in keywords or [] if word and word.lower() in query)
    if query in text:
        score += 8
    return score


def search_resources(query: str, resident: str) -> list[dict]:
    from app import storage
    from app.retrieval import retrieve
    from app.api import activity_views
    data=storage.read_data(tables=('policies','activities','registrations'))
    POLICIES,TICKETS=data['policies'],storage.tickets_for(resident)

    candidates = []
    retrieved=retrieve(query) if query.strip() else []
    retrieval_order={item['id']:index for index,item in enumerate(retrieved)}
    policy_topics = {p["id"] for p in POLICIES if any(word in query for word in p["keywords"] if len(word) >= 2)}
    other_intent = any(word in query for word in ("活动", "报名", "义诊", "亲子", "工单", "进度", "报修", "维修"))
    for p in POLICIES:
        if query.strip() and p['id'] not in retrieval_order: continue
        candidates.append({"id": p["id"], "kind": "policy", "title": p["title"], "description": p["summary"], "steps": p["steps"], "source": p["source"], "updated_at": p["updated_at"], "keywords": " ".join(p["keywords"]), "action": {"type": "view_policy", "label": "查看完整办事指引", "resource_id": p["id"]}})
    for item in retrieved:
        if item['kind']!='document': continue
        meta=item['metadata']
        candidates.append({'id':item['id'],'kind':'knowledge','title':item['title'],'description':item['excerpt'],'source':meta['source'],'updated_at':meta['updated_at'],'meta':f"版本 {meta['version']} · "+(f"第 {meta['page']} 页 · " if meta.get('page') else '')+item['retrieval_method'],'chunk_id':item['chunk_id'],'source_url':meta.get('source_url',''),'is_demo':False,'action':{'type':'view_document','label':'查看原文与引用片段','resource_id':item['id']}})
    for service in SERVICES:
        candidates.append({**service})
    for a in activity_views(data,resident):
        candidates.append({"id": a["id"], "kind": "activity", "title": a["title"], "description": a["description"], "meta": f"{a['date']} {a['time']} · {a['location']} · 剩余{max(0, a['capacity'] - a['registered'])}席", "keywords": a["category"] + " " + a["audience"] + " 活动 报名", "action": {"type": "open_activities", "label": "查看活动并报名", "resource_id": a["id"]}})
    for t in TICKETS:
        if resident != t.get("owner_id"):
            continue
        candidates.append({"id": t["id"], "kind": "ticket", "title": f"{t['category']} · {t['status']}", "description": t["description"], "meta": f"{t['id']} · {t['location']} · {t['assignee']}", "keywords": "我的工单 进度 报修记录 " + t["id"], "action": {"type": "view_ticket", "label": "查看工单详情", "resource_id": t["id"]}})
    ranked = []
    for item in candidates:
        # Generic words such as “材料” should not pull handicraft activities
        # into an otherwise specific residence-permit request.
        if policy_topics and not other_intent and item['kind']!='knowledge' and item["id"] not in policy_topics and item["id"] != "service-policy":
            continue
        keywords = item.get("keywords", "").split()
        score = relevance(query, item["title"] + " " + item["description"] + " " + item.get("meta", "") + " " + " ".join(item.get("steps", [])), keywords)
        if item["kind"] == "policy" and any(word in query for word in keywords):
            score += 8
        if item['id'] in retrieval_order: score=1000-retrieval_order[item['id']]
        if score:
            ranked.append((score, {k: v for k, v in item.items() if k != "keywords"}))
    ranked.sort(key=lambda row: row[0], reverse=True)
    return [item for _, item in ranked[:8]]


def local_answer(query: str, resident: str, resources: list[dict]) -> dict:
    if resources:
        first = resources[0]
        reply = f"为你找到 {len(resources)} 项相关内容和服务。\n\n**{first['title']}**\n{first['description']}\n\n可以展开下方卡片查看办理步骤，或点击按钮进入对应服务。"
    else:
        reply = "暂未找到匹配的社区资料。你可以换个关键词，例如“居住证材料”“报修流程”或“我的工单进度”，也可以咨询社区服务窗口。"
    return {"reply": reply, "intent": "resource_search", "sources": [{"title": r["source"], "updated_at": r["updated_at"]} for r in resources if r.get("source")], "resources": resources, "trace": ["检索社区资料", "匹配内容与办理流程", f"找到 {len(resources)} 项结果"], "mode": "local-search"}
