# Hiro

[English](README.md)

Hiro 是一个 AI 辅助的渗透测试和 CTF 工作流平台。它结合了 FastAPI 后端、Vue Web UI、基于 DeepAgents 的 agent 执行、会话级文件存储、可选 RAG 上下文、MCP 工具集成，以及用于信息收集和报告生成的专用工作流 agent。

> [!CAUTION]
> **免责声明**
>
> Hiro 仅用于经授权的安全研究、教学、内部验证和 CTF 环境。不要在未获得明确授权的系统上使用 Hiro。使用者需自行确保遵守适用法律法规、授权范围、测试规则和第三方服务条款。Hiro 的作者和贡献者不对因使用或滥用本项目造成的未授权访问、服务中断、数据丢失、法律后果或其它损害负责。Hiro 可能执行由模型驱动的工具和 shell 命令；请在采取行动前审查目标、命令、输出和生成的 artifacts。

> [!IMPORTANT]
> Hiro 目前处于快速开发阶段，并包含大量由 LLM 生成的代码。项目中可能存在安全问题、严重 bug、破坏性变更和未完成的功能。请将本项目视为实验性项目：使用前仔细审查代码、配置、生成的命令和部署环境；未经额外安全加固，不建议在生产环境或敏感环境中运行。

## 截图

以下截图展示当前桌面版 Web UI。Hiro 仍在快速迭代，实际界面细节可能与最新构建有所不同。

### Chat

![Hiro Web UI，展示带有实时 assistant 输出的 agent session](docs/hiro-screenshot-1.png)

### Token 用量统计

![Hiro Web UI，展示 session workspace、agent controls 和辅助面板](docs/hiro-screenshot-2.png)

## 项目结构

```text
.
+-- main.py                    # FastAPI 入口
+-- pyproject.toml             # Python 项目元数据和依赖
+-- server/                    # API、模型、agent runtime、工具、服务
|   +-- agent/                 # Agent runtime、streaming、subagents、tools
|   +-- api/v1/endpoints/      # REST 和 WebSocket endpoints
|   +-- core/                  # Settings、security、installation、utility helpers
|   +-- models/                # SQLAlchemy models
|   +-- service/               # RAG 和 MCP services
+-- skills/                    # DeepAgent skill instructions
+-- tests/                     # 后端测试套件
+-- web/                       # Vue 前端
```

## 环境要求

- 推荐使用 Linux。Agent 的 shell 执行依赖 Bubblewrap。
- Python 3.12 或更高版本。
- 使用 `uv` 管理 Python 依赖。
- Node.js 20 或更高版本，以及 npm。
- 安装器会检查以下系统工具：
  - `curl`
  - `wget`
  - `bwrap`，来自 `bubblewrap` 包
  - `feroxbuster`

## 快速开始

启动后端：

```bash
uv sync
uv run python main.py
```

API 默认运行在 `http://localhost:8000`。

在第二个终端启动 Web UI：

```bash
cd web
npm install
npm run dev
```

打开 `http://localhost:5173`。

开发模式下，Vite 会把 `/api` 请求代理到 `http://localhost:8000`，默认配置不需要额外设置前端 API 地址。

## 首次安装

当 Hiro 尚未安装时，Web UI 会跳转到 `/install`。

1. 输入数据库 DSN。本地开发可以使用：

   ```text
   sqlite:///./hiro.db
   ```

2. 运行环境检查。安装器会验证 `wget`、`curl`、`bwrap` 和 `feroxbuster`。
3. 创建管理员账号。
4. Hiro 会将安装配置写入 `.env`，创建数据库表，并重启后端进程。
5. 使用刚创建的管理员用户名和密码在 `/login` 登录。

安装器会写入：

```text
DATABASE_URL=...
INSTALLATION_COMPLETED=true
```

如果要部署到更接近生产环境的场景，请在对外暴露服务前在 `.env` 中设置强 `SECRET_KEY`。

## 配置

Hiro 通过 Pydantic settings 从环境变量和 `.env` 读取配置。

常用配置：

```text
PROJECT_NAME=Hiro API
PROJECT_DESCRIPTION=A scalable FastAPI application
VERSION=0.1.0
SECRET_KEY=change-this-value
API_KEY_HEADER=X-API-Key
DATABASE_URL=sqlite:///./hiro.db
INSTALLATION_COMPLETED=true
ALLOWED_ORIGINS=["*"]
```

默认数据库是 `./hiro.db` 处的 SQLite。其它 SQLAlchemy 数据库 URL 在安装了对应 async driver 且 URL 使用正确 async dialect 时也可以使用。

## 使用说明

### 1. 配置 LLM

打开 LLM 页面并创建 provider 配置。

UI 支持的 provider 类型：

- `openai`
- `anthropic`

> [!NOTE]
> 如果你希望通过 CLI 使用 LLM，例如 Gemini CLI、ChatGPT Codex 等，或使用其它 provider，例如 Codex、Gemini，请参考 [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) 项目。

你也可以为 OpenAI-compatible 或 Anthropic-compatible gateway 配置自定义 base URL。会话中选择的模型也可以按 workflow agent 覆盖，例如 `main_agent`、`information_collect_agent` 和 `writeup_agent`。

### 2. 创建 Session

打开 Sessions，创建或选择一个 session，选择 LLM 配置，按需启用 tools/MCP/RAG，然后发送 prompt。Session 页面会实时流式展示：

- assistant 文本
- 内联 tool calls
- MCP tool events
- token usage
- 最终持久化的 messages

### 3. 使用 RAG

打开 RAG 页面上传文档或注册文档来源。Hiro 会把支持的文档索引到配置的 vector store 中；当 session 启用 RAG 时，相关片段会被注入 agent run。

后端支持的 embedding providers：

- OpenAI
- Cohere
- Ollama

Vector storage 默认使用 Milvus Lite (`hiro_rag.db`)，也可以指向远程 Milvus endpoint。

### 4. 配置 MCP Servers

打开 MCP 页面添加并测试 MCP servers。Hiro 会保存每个 server 配置，并为 session 加载选中的 MCP tools。Agent 通过 `mcp_search` 和 `mcp_call` 以 router 风格访问 MCP tools，而不是一开始就暴露所有远程工具。

### 5. 生成 API Tokens

打开 API Tokens 页面创建用于 API 访问的 token。生成的 token 使用方式：

```text
X-API-Key: hiro_...
```

浏览器登录使用 `/api/v1/auth/login` 签发的 JWT bearer token。

## 开发

运行后端测试：

```bash
uv run pytest
```

构建前端：

```bash
cd web
npm run build
```

构建后预览前端：

```bash
cd web
npm run preview
```

## 安全说明

Hiro 会为测试工作流执行由模型驱动的工具和 shell 命令。请将其部署在可信网络中，仅用于授权测试，并审查生成的命令和 artifacts。Bubblewrap 能提升隔离性，但不应被视为完整的多租户安全边界。

共享实例前请修改默认的 `SECRET_KEY`。如果 `.env`、数据库文件、RAG stores 或 `data/` artifacts 包含敏感信息，不要将它们提交到版本库。

## License

MIT LICENSE
