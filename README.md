# VibeChat

> AI 驱动的匿名情绪社交应用：先理解此刻的情绪，再连接真正同频的人。

VibeChat 是第三期灵治擂台赛作品。用户写下当前心情后，系统会分析主情绪、混合情绪、强度、正负向和关键词，并将这些字段真正用于匹配计算。匹配成功后，双方以系统生成的匿名身份进入实时聊天室。

**在线体验：** https://vibechat-nine.vercel.app  
**在线体验：** 120.24.207.84

## 核心功能

- 结构化情绪分析：标签、强度、正负向、唤醒度、关键词和温和解释。
- 可解释同频匹配：分析结果直接进入加权匹配算法，展示匹配指数与理由。
- 真实匿名聊天：WebSocket 优先、REST 轮询降级、时间顺序、在线状态、匿名身份。
- 未匹配兜底：等待后可连接明确标识的“同频向导”，便于单人体验和稳定演示。
- 双标准接口：OpenAI Chat Completions 与 Anthropic Messages，通过环境变量切换。
- 安全边界：识别高风险表达并展示求助提醒，不进行医疗诊断。
- 完整交付：FastAPI + Next.js 前后端分离、Docker 配置和自动测试。

## 技术架构

```text
Next.js 16 / React 19
  ├─ 情绪输入与分析结果卡
  ├─ 匹配等待与兜底
  └─ WebSocket 匿名聊天室
             │ REST + WebSocket
FastAPI
  ├─ Emotion Provider Adapter
  │    ├─ OpenAI 标准接口
  │    ├─ Anthropic 标准接口
  │    └─ Demo 演示引擎
  ├─ Emotion Match Queue
  └─ Conversation / Message Store
```

本地开发默认使用零依赖内存存储；配置 `KV_REST_API_URL` 与 `KV_REST_API_TOKEN` 后会自动切换到 Upstash Redis，使匹配、会话和消息可跨 Vercel 实例共享。

## 目录结构

```text
VibeChat/
├─ backend/
│  ├─ app/
│  │  ├─ config.py       # 环境配置
│  │  ├─ llm.py          # OpenAI / Anthropic / Demo Provider
│  │  ├─ models.py       # 统一 Pydantic Schema
│  │  ├─ store.py        # 内存 / Redis 匹配、会话与消息状态
│  │  └─ main.py         # FastAPI 路由
│  └─ tests/             # 匹配和双用户聊天测试
├─ frontend/
│  └─ app/               # Next.js 单页完整体验
├─ docker-compose.yml
└─ SUBMISSION.md         # 提交文案与录屏脚本
```

## 本地启动

### 1. 启动后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload --port 8000
```

默认 `LLM_PROVIDER=demo`，无需密钥即可体验完整流程。API 文档：`http://localhost:8000/docs`。

### 2. 启动前端

```powershell
cd frontend
corepack enable
pnpm install
Copy-Item .env.example .env.local
pnpm dev
```

访问 `http://localhost:3000`。打开两个普通/无痕窗口并输入相近情绪，即可验证真实双用户匹配和聊天。

### 3. 运行测试与构建

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q

cd ..\frontend
pnpm build
```

也可使用 Docker：

```bash
docker compose up --build
```

## LLM API 配置

所有密钥只配置在后端，禁止放入 `NEXT_PUBLIC_*` 变量或提交到 Git。

### OpenAI 标准接口

后端调用 `{OPENAI_BASE_URL}/chat/completions`，使用 Bearer Token 和标准 `messages` 请求体。

```dotenv
LLM_PROVIDER=openai
OPENAI_API_KEY=your-key
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-v4-flash
```

也可将 `OPENAI_BASE_URL` 替换为兼容 OpenAI Chat Completions 的服务根地址。

### Anthropic 标准接口

后端调用 `{ANTHROPIC_BASE_URL}/messages`，使用 `x-api-key` 和 `anthropic-version` 请求头。

```dotenv
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-key
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_MODEL=deepseek-v4-flash
```

修改配置后重启后端。`GET /health` 会返回当前 Provider 名称，但不会泄露模型密钥。

### DeepSeek 同时验证两种标准

DeepSeek 同时提供 OpenAI 与 Anthropic 格式。本项目已使用同一 DeepSeek Key 对两种接口进行真实调用验证：

```dotenv
OPENAI_API_KEY=your-deepseek-key
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-v4-flash

ANTHROPIC_API_KEY=your-deepseek-key
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_MODEL=deepseek-v4-flash
```

这两条调用链分别经过独立的请求格式、认证请求头和响应解析逻辑，最终统一为 `EmotionResult`。

## 匹配算法

匹配分数由四部分组成：

- 主/次情绪重合：55%。
- 情绪强度接近：25%。
- 正负向接近：12%。
- 唤醒度接近：8%。

同主情绪获得最高标签分；不同主情绪只有在混合情绪重叠时获得部分分数。默认阈值为 `0.56`。这确保 AI 分析不是装饰性标签，而是实际改变匹配结果。

## 主要 API

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/health` | 健康检查与 Provider 状态 |
| `POST` | `/api/emotions/analyze` | 情绪分析 |
| `POST` | `/api/matches/join` | 加入匹配队列 |
| `GET` | `/api/matches/{ticket_id}` | 查询匹配状态 |
| `POST` | `/api/matches/{ticket_id}/demo` | 连接演示伙伴 |
| `GET` | `/api/conversations/{id}` | 获取会话与消息 |
| `POST` | `/api/conversations/{id}/messages` | 发送消息（REST 降级通道） |
| `WS` | `/ws/conversations/{id}` | 实时收发消息 |

匿名会话凭证由后端生成，聊天接口不会暴露真实身份。比赛版本的匿名机制适用于临时会话，不等同于端到端加密。

## 公网部署

仓库根目录的 `vercel.json` 支持将 Next.js 前端与 FastAPI 后端作为两个 Web Service 部署到同一个 Vercel 项目：前端位于 `/`，后端挂载到 `/_/backend`。前端未显式配置公网变量时会自动使用该同源路径。

Vercel Functions 不支持充当 WebSocket 服务器，因此前端会在 WebSocket 不可用时自动切换到 REST 发送与短轮询接收；部署到支持长连接的容器平台时仍会优先使用 WebSocket。

### Vercel 多服务部署

1. 导入 GitHub 仓库根目录，Vercel 会读取 `experimentalServices`。
2. 在项目 Secret 中配置后端的 `LLM_PROVIDER`、两套 API Key、Base URL 与模型名。
3. 在 Vercel Marketplace 创建免费的 Upstash Redis，并连接到项目；平台会注入 `KV_REST_API_URL` 与 `KV_REST_API_TOKEN`。
4. 重新部署后验证 `/_/backend/health` 返回 `"storage":"redis"`，并检查 `/_/backend/docs`。

### 分离部署

1. 将 `backend/` 部署到支持持续运行和 WebSocket 的容器服务，保持单实例。
2. 配置后端 Provider 密钥、模型、`CORS_ORIGINS=https://前端域名`。
3. 将 `frontend/` 部署到 Next.js 托管服务，并在构建阶段设置：

```dotenv
NEXT_PUBLIC_API_URL=https://后端域名
NEXT_PUBLIC_WS_URL=wss://后端域名
```

4. 依次检查 `/health`、情绪分析、两个无痕窗口匹配、双向消息和刷新后的页面状态。

## 稳定演示建议

- 正式演示前保留两个无痕窗口，分别作为用户 A/B。
- 先展示相近情绪得到高分，再说明不同情绪不会立即匹配。
- 外部 LLM 异常时界面会显示明确错误；可切换 `demo` 完成产品流程演示。
- 单人体验等待 8 秒后可连接“同频向导”，不会卡在空队列。
- 录屏与截图中不得出现 API Key 或部署平台 Secret。

## 产品介绍（100 字以内）

VibeChat 是一款 AI 驱动的匿名情绪社交应用。它理解用户此刻的情绪类型、强度与倾向，据此寻找真正“同频”的陌生人，并生成自然的匿名对话空间，让每次连接从被理解开始。
