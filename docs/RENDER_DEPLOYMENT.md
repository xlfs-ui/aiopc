# GitHub + Render Free + Neon 部署

当前状态：代码已上传 https://github.com/xlfs-ui/aiopc，Render 免费服务已上线。公网地址为 https://neighborhood-agent.onrender.com 。首页、前端 JS/CSS、健康检查和验证码接口均返回 200；健康检查确认 `storage=postgresql`。未登录用户接口返回 401，生产 API 文档、`.env` 和数据库文件路径均返回 404。

## 架构

```text
访问者 → Render HTTPS → FastAPI
                         ├─ Vue 构建产物（同域）
                         ├─ Neon PostgreSQL（账号、业务、原始文档、片段、向量）
                         ├─ DeepSeek 对话 API
                         └─ text-embedding-3-small 中转 API
```

- 本地 Conda + SQLite：不配置 `DATABASE_URL`，继续使用本地数据库。
- 云端 Docker + PostgreSQL：Render 私密环境变量配置 Neon 连接串，不向镜像复制本地 `.env` 或 SQLite。
- Render 免费实例休眠或重启不会删除 Neon 中的数据，但有冷启动及免费额度限制。
- 云端使用 PostgreSQL 原生全文索引、中文双字预分词和全文相关性排序；本地仍使用 FTS5/BM25。两端均支持余弦向量召回与 RRF。PostgreSQL 全文排序不是 BM25。
- 为保留现有并发保护，小规模云部署在写事务内使用 PostgreSQL advisory transaction lock；更高并发需要继续拆分写锁。

## 1. GitHub

创建私有仓库 `neighborhood-agent`，初始化 README。上传本项目的代码及部署文件：

```text
Dockerfile / .dockerignore / render.yaml
package.json / pnpm-lock.yaml / pnpm-workspace.yaml
frontend/（排除 node_modules、dist）
backend/（排除 data、__pycache__、虚拟环境）
scripts/
```

不要上传 `.env`、`.env.deploy`、数据库文件、SSH 密钥或商业方案原件。Git 忽略规则和 Docker 忽略规则已加入相关限制；上传时仍应检查所选文件。

## 2. Neon

在现有免费项目中点 **Connect**，选择用于该应用的数据库，打开连接池开关，取得 PostgreSQL URL。URL 含数据库密码，只保存在本地私密文件或 Render 环境变量中。

现有项目位于 AWS US East 2 (Ohio)，因此 Render 优先选 Ohio，减少跨区域数据库延迟。若改用新项目，按实际地区匹配。

不要使用 Render 自带的免费 PostgreSQL 代替这一步：其免费数据库有 30 天有效期。

## 3. Render

在 Render 连接该 GitHub 私有仓库，创建 **Web Service**：

| 设置 | 值 |
| --- | --- |
| Runtime / Language | Docker |
| Dockerfile | `./Dockerfile` |
| Root directory | 留空（仓库根目录） |
| Region | Ohio（与现有 Neon 地区匹配） |
| Instance plan | Free |
| Health check | `/api/health` |
| Docker command | 留空，使用镜像 CMD |

环境变量：

```dotenv
APP_ENV=production
COOKIE_SECURE=true
DATABASE_URL=你的Neon连接池URL
DEEPSEEK_API_KEY=你的后端对话密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
EMBEDDING_BASE_URL=https://api.openai-proxy.org/v1
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_API_KEY=你的后端嵌入密钥
```

不要把本地的 `ALLOWED_ORIGINS=http://localhost...` 和 `TRUSTED_HOSTS=localhost...` 原样复制到云端；应用会根据 Render 提供的 `RENDER_EXTERNAL_URL` 自动配置同域来源及主机校验。使用自定义域名时再配置明确的 `PUBLIC_URL` 和需要允许的域名。

生产环境必须是 HTTPS，Cookie 使用 Secure / HttpOnly / SameSite=Lax。没有 `DATABASE_URL` 时 Render 生产启动会失败，防止意外把账户保存到临时磁盘。

免费实例不能使用云端 Shell。初次需要管理员时，可在 Render 私密环境变量中填写：

```dotenv
BOOTSTRAP_ADMIN_USERNAME=你选择的管理员账号
BOOTSTRAP_ADMIN_PASSWORD=你自己设置的12至128位强密码
```

启动时仅在此账号不存在时创建管理员，不会重置或提权已有账号。首次成功后移除这两个初始化变量，再部署一次；数据库中的管理员会保留。

## 4. 构建及启动流程

1. Render 克隆 GitHub 代码。
2. Docker 的 Node 22 阶段安装 pnpm 11.25.0，按锁文件安装前端依赖并构建 Vue。
3. Python 3.11 阶段安装后端依赖，只复制后端源码、启动脚本和前端构建产物，不包含密钥和本地数据库。
4. 使用非 root 用户启动 `scripts/serve.py`，监听 Render 的 `PORT`。
5. 应用连接 Neon，自动创建业务、会话、文档及检索表；首次载入业务演示资料。
6. `/api/health` 检查通过后，Render 提供 `.onrender.com` HTTPS 地址。
7. 初次登录后在“文档知识库”审核发布资料并构建向量索引。

## 5. 数据范围与验证

新云数据库默认初始化演示业务，不会自动上传本地 SQLite 中的真实账号、工单、聊天或用户文档。需要迁移这些已有数据时，应先备份并单独执行受控迁移，不能简单把 SQLite 文件上传到 Neon。

上线后应核对首页、验证码、注册登录、会话、资料搜索、工单归属和知识库。再次部署后确认刚注册的账号和新增记录仍存在，再将网址交付使用。

本地没有安装新增 `psycopg` 依赖；Render 已从依赖清单安装并构建镜像。云端驱动已锁定为 `psycopg` / `psycopg-binary` 3.3.6。首次云端启动发现 PostgreSQL 的 `session_user` 保留字与原索引名冲突，已将云端索引改名为 `sessions_by_user`。

## 本次部署及后续更新

- 仓库为用户现有的公开仓库，只上传审核过的应用源码和部署文件。
- Git 上传使用本机已有 Git Credential Manager；没有使用或保存聊天中的 GitHub 密码。本次命令跳过全局的第三方 GitHub URL 代理配置，直接连接 GitHub，没有修改全局配置。
- 推送 checkout 为 `F:\aiopc\deploy-private\repository`；原开发目录仍为 `F:\aiopc`。后续开发修改要先同步到此 checkout，再提交推送，或自行将开发根目录配置成正式 Git 工作区。
- 本次 Render 是通过公开仓库 URL + API 创建的；尚未验证 GitHub 应用 webhook 自动部署。推送后在 Render 选择 **Manual Deploy → Deploy latest commit**，或者在激活已有 Conda 环境后于根目录运行 `python scripts/render-deploy.py deploy`。
- `python scripts/render-deploy.py status` 查看部署状态，`python scripts/render-deploy.py logs` 查看日志。命令只读取根目录私密 `.env.deploy`，不需要重新安装本地依赖。
- 初始管理员凭据保存在本地 `deploy-private/administrator.env`；不要上传。可在登录后的账户设置修改密码。初始化环境变量移除后，账号仍保存在 Neon。
- Render 的私密环境变量已存放数据库和模型凭据；模型请求可能产生供应商费用，Render 和 Neon 使用本次选择的免费规格。

## 浏览器不能操作时

项目根目录 `.env.deploy` 可私密保存下列内容，供后续 API 部署使用（已被 Git 忽略）：

```dotenv
GITHUB_REPOSITORY=https://github.com/你的账号/neighborhood-agent
DATABASE_URL=Neon连接池URL
RENDER_API_KEY=由你自己创建的Render账号API密钥
```

无需把凭据发到聊天。若不愿创建 Render API Key，可在 Render 控制台按上述设置手动创建服务。

## 官方资料

- [Render Docker 部署](https://render.com/docs/docker)
- [Render 免费限制](https://render.com/docs/free)
- [Render 环境变量](https://render.com/docs/environment-variables)
- [Render API](https://render.com/docs/api)
- [Neon 连接应用](https://neon.com/docs/connect/connect-from-any-app)
