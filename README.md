# 邻里智服 Agent

基于《社区智能服务 Agent 商业方案》的 Web MVP。包含居民服务端、社区工作台和 FastAPI 接口；业务数据使用本地假数据，不包含微信小程序或外部政务接口。Agent 使用 LangGraph 编排流程、LangChain 工具接入 DeepSeek；未配置 API key 时自动使用假数据对话模式。

## 功能

- 账号：居民注册、一次性图片验证码、账号密码登录、退出和修改密码。管理员通过本机命令创建，管理接口有服务端权限校验。

- 居民端：社区政策问答（展示政策来源）、报事报修、工单查询、活动浏览与报名。
- 工作台：工单状态处理、政策和活动信息查看、基础运营数据。
- 对话入口：LangGraph Agent 可调用本地政策检索、活动查询与报名、居民工单查询和报修登记工具；政策回答展示资料来源及更新时间。
- 数据：首次启动载入假数据，后续修改保存到 `backend/data/community.db`（SQLite），政策、活动、工单和报名使用独立表；旧快照自动备份并迁移，重启后保留。工单按登录用户 ID 隔离，报名与写入在事务中完成。
- 统一检索：通过首页导航或 `Ctrl+K` 查找政策、办理流程、活动和本人工单；返回可展开的结果卡片和服务入口。
- 办理协助：Agent 将报修需求整理为草稿，经居民核对并提交后生成工单；本地检索在模型未配置或调用失败时仍可使用。
- 界面：全局搜索、会话本地保存、工单详情、检索反馈、卡片和弹窗动效；支持系统“减少动态效果”设置。
- 知识库：管理员可导入 TXT、Markdown、DOCX、文字型 PDF 或粘贴正文，预览审核后发布；支持版本、有效期、归档、片段引用及原文查看。
- 检索：SQLite FTS5 / BM25 中文全文检索，可配置独立 Embedding 接口，将 SQLite 中的向量与全文检索通过 RRF 融合。未配置或模型服务故障时继续使用全文检索。

## 环境要求

云端部署使用 **GitHub + Render Free + Neon PostgreSQL**，本地仍保留 SQLite。完整步骤、私密环境变量和管理员初始化见 [云端部署说明](docs/RENDER_DEPLOYMENT.md)。配置文件存在不代表服务已经上线；以 Render 实际构建和健康检查结果为准。

需要 Anaconda/Miniconda、Node.js 22+ 和 pnpm 11。后端依赖声明在 `backend/requirements.txt`，安装时使用 `backend/requirements-lock.txt` 约束为本轮 Windows/Python 3.11 验证过的版本；前端使用 `pnpm-lock.yaml`。Conda 环境由你自行创建和激活，项目命令不会创建环境，后端安装脚本拒绝在 base 中安装。

## 根目录命令

先在 Anaconda PowerShell Prompt 中自行创建并激活环境：

```powershell
conda create -n neighborhood-agent python=3.11 -y
conda activate neighborhood-agent
conda install -c conda-forge nodejs=22 -y
```

然后在项目根目录 `F:\aiopc` 安装项目依赖：

```powershell
pnpm run deps:install
```

该命令会安装前端 pnpm 依赖，并将后端依赖装入当前已激活的 Conda 环境。每次新开终端后，先运行 `conda activate neighborhood-agent` 再启动项目。

## 配置 DeepSeek Agent

在项目根目录 `.env` 中填写你自己新生成的 DeepSeek API key：

```dotenv
DEEPSEEK_API_KEY=在这里填写你的新API密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

`.env` 已加入 Git 忽略规则，不要把密钥粘贴到前端代码或提交到仓库。当前聊天里曾发送过的 key 已暴露，建议在 DeepSeek 控制台撤销并换新。修改 `.env` 后重启后端生效。留空 API key 时 `/api/chat` 使用本地假数据演示；`/api/health` 会显示当前模式。

启动前后端：

```powershell
pnpm dev
```

前端地址：<http://127.0.0.1:5173>；后端接口文档：<http://127.0.0.1:8000/docs>。前端开发服务器会将 `/api` 代理到 FastAPI。

只需在一个终端运行一次 `pnpm dev`，它会同时启动前后端。在该终端按 `Ctrl+C` 会停止本次启动的全部服务进程，然后可以重新运行。启动前会检查 5173 和 8000；如果提示端口被占用，先停止原终端的服务，或直接访问已经运行的页面。请先停止 `pnpm dev:api` / `pnpm dev:web` 的独立实例，再使用同时启动命令。

生产构建：`pnpm build`。仅启动后端或前端时，分别执行 `pnpm dev:api` 或 `pnpm dev:web`。

数据库命令：`pnpm db:backup` 生成一致备份，`pnpm db:migrate` 迁移结构，`pnpm db:info` 查看结构版本及记录数量。迁移前先停止旧服务。**文档入库、Embedding 配置、数据恢复与使用限制见 [SQLite 与知识库指南](docs/RAG_SQLITE_GUIDE.md)**。本轮新增 `pypdf` 依赖，安装由你在自己的 Conda 环境执行。

## 登录与管理员

打开页面后先注册居民账号，密码为12–128位，登录与注册均需图片验证码（不区分大小写，3分钟有效）。图片验证不代表短信或邮箱身份认证。没有默认账号和默认密码。

需要社区工作台时，在激活的 Conda 环境、项目根目录执行：

```powershell
python backend/admin.py create-admin --username community_admin
```

按提示输入并确认密码，密码不要写进命令参数。等价根目录命令：`pnpm admin:create --username community_admin`。管理员登录后出现工作台；注册用户不能选择管理员角色。

账号与安全入口在侧栏底部，支持改密和退出。改密会注销全部设备；忘记密码时，由管理员核实身份后执行 `python backend/admin.py reset-password --username 账号名`。历史假数据不自动归属任何新注册的同名用户。

安全实现、扫描结果和正式部署要求见 [安全检查记录](docs/SECURITY_REVIEW.md)。本轮没有代你执行依赖安装。

## 演示操作

1. 在居民端通过快捷问题咨询“居住证怎么办理”，查看带有来源和更新时间的政策回答。
2. 点击“提交报修”创建工单，或在对话框输入带有位置的问题描述。
3. 切换到社区工作台受理工单、更新处理状态；新增/编辑政策资料和社区活动。
4. 回到居民端查询工单、浏览活动并报名。

居民只看到自己的工单和报名状态。管理员可查看管理数据；顶部切换只是管理员的页面模式切换，不能改变服务端角色。

## 项目结构

```text
package.json             根目录依赖与开发命令
pnpm-workspace.yaml      前端 workspace 配置
scripts/setup.ps1         将项目依赖安装到当前激活的 Conda 环境
scripts/dev.mjs           同时启动 FastAPI 与 Vue
backend/requirements.txt FastAPI 后端依赖
backend/app/main.py       FastAPI 初始化、安全中间件、初始假数据
backend/app/api.py        有身份与角色校验的业务接口
backend/app/auth.py       注册、验证码、密码与会话
backend/app/agent.py      LangGraph 状态流程、DeepSeek 模型和业务工具
backend/app/services.py   内容与服务目录、中文检索和允许的页面操作
backend/app/storage.py    SQLite 本地保存和操作记录
backend/tests/            不调用真实模型的流程回归检查
frontend/package.json    Vue 前端依赖与构建命令
frontend/src/App.vue      居民端与社区工作台交互界面
frontend/src/style.css    响应式界面样式
frontend/src/experience.css 服务导航、结果卡片和动效样式
docs/PROJECT_REVIEW.md    本轮补充与后续基础建设清单
```

## 后续替换假数据

SQLite 业务数据已拆表并通过事务处理读写，知识库已支持审核和混合检索。部分业务列表仍需扩展 SQL 分页与更高并发下的压力评估；轻量向量检索上限为 5000 个索引片段，暂不支持扫描件 OCR。正式部署必须使用 HTTPS 并设置生产安全参数，详细要求见 `docs/SECURITY_REVIEW.md`。

回归检查（使用已激活环境，在 `backend` 目录执行）：`python -m unittest discover -s tests -v`。检查使用独立临时数据库和模拟模型，不调用 DeepSeek。
