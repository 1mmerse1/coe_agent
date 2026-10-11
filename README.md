# 学生会推送档案助手

这是一个本地运行的活动策划和公众号推送助手。它会读取本地历史推送数据库和图片素材，由 Brainstorm、策划、推送、海报、问卷、PPT 等 Agent 协作生成结果，并保留人工修改环节。

## 目录结构

```text
coe_agent/
├─ README.md                    # 项目说明（本文件）
├─ requirements.txt             # Python 依赖
├─ .env.example                 # 模型 API Key 配置模板
├─ 启动推送助手.bat              # 双击启动本地服务
├─ 开始导入.bat                  # 双击导入公众号文章
├─ 配置API密钥.bat               # 双击编辑 .env
├─ 推送URL_test.txt              # 导入用的链接清单
├─ src/                         # 应用代码
│  ├─ paths.py                  # 统一目录解析（根目录、data、resources…）
│  ├─ app.py                    # FastAPI 服务和 Agent 接口
│  ├─ launch_chat.py            # 启动入口
│  ├─ importer.py               # 公众号文章入库
│  ├─ activity_store.py         # 活动草稿与附件存储
│  ├─ planning_templates.py     # 策划案模板选择
│  ├─ planning_documents.py     # 策划案 Word/PDF 导出
│  ├─ local_media_library.py    # 本地图片素材检索
│  ├─ workflow_framework.py     # Agent 分工与路由契约
│  ├─ export_shared_bundle.py   # 导出共享数据包
│  └─ web/index.html            # 前端页面
├─ scripts/                     # 独立采集脚本（微信客户端 / 网页）
├─ references/                  # 规则、规划和使用说明
├─ resources/                   # 策划案模板与编写要求
└─ data/                        # 运行数据，不进 Git
```

`data/` 是程序运行目录：历史文章数据库、图片、活动草稿和导出结果都放在这里，已被 `.gitignore` 忽略，不会误提交到 GitHub。

## 你需要准备的三样东西

合作者第一次使用时，需要分别拿到：

1. **GitHub 仓库**：程序代码、网页、Agent 配置和模板。
2. **你发送的数据包**：历史推送数据库和指定图片素材。数据不在 GitHub 仓库中，因为 `data/` 被 `.gitignore` 忽略。
3. **合作者自己的模型 API Key**：每个人在自己的电脑上配置，不共享、不提交到 GitHub。

建议发送一个压缩包，例如 `coe_shared.zip`。压缩包解压后应包含下面的结构：

```text
coe_shared/
├─ manifest.json
└─ data/
   ├─ articles.sqlite3       # 历史推送数据库
   ├─ media/                 # 历史推送图片
   ├─ articles/              # 历史文章预览
   ├─ 学校学院/              # 固定首图、尾图和学院素材
   └─ 过渡图标/              # 正文分隔图标
```

当前不建议发送 `activity_projects.sqlite3`。它保存本机“办一场活动”的草稿、附件和生成结果，可能包含个人输入；每位合作者应保留自己的活动历史。

## 合作者安装步骤

### 1. 克隆代码

```powershell
git clone https://github.com/1mmerse1/coe_agent.git
cd coe_agent
```

### 2. 放入你发送的数据

把数据包中的 `data/` 文件夹复制到项目根目录。如果系统询问是否合并文件夹，选择合并；不要删除代码仓库中的其他文件。

完成后，项目根目录应同时存在：

```text
coe_agent/
├─ src/
├─ scripts/
├─ references/
├─ resources/
├─ .env.example
└─ data/
   ├─ articles.sqlite3
   ├─ articles/
   ├─ media/
   ├─ 学校学院/
   └─ 过渡图标/
```

### 3. 配置自己的模型 API Key

复制配置模板：

```powershell
copy .env.example .env
```

然后用记事本打开 `.env`，至少填写以下四项：

```text
LLM_PROVIDER=deepseek
LLM_API_KEY=你的Key
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

API Key 只写在本机 `.env`，不要发给其他人，也不要提交到 GitHub。后端读取 Key，浏览器不会接触 Key。

## 支持的模型服务

| 厂商 | `LLM_PROVIDER` | `LLM_BASE_URL` | `LLM_MODEL` 示例 | 接口模式 |
|---|---|---|---|---|
| OpenAI 官方 | `openai` | `https://api.openai.com/v1` | 账号可用的 GPT 模型 | `responses` |
| OpenAI 兼容中转 | `aizex` | `https://codex-api.aizex.net/v1` | 中转站提供的模型名 | `responses` 或 `auto` |
| DeepSeek | `deepseek` | `https://api.deepseek.com/v1` | `deepseek-chat` | `chat` 或 `auto` |
| GLM | `glm` | `https://open.bigmodel.cn/api/paas/v4` | 账号可用的 GLM 模型 | `chat` 或 `auto` |

如果服务商给了不同的地址或模型名，以服务商控制台为准。需要强制指定接口时，可设置：

```text
LLM_API_MODE=responses
```

或：

```text
LLM_API_MODE=chat
```

旧版本的 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL` 仍然兼容。OpenAI 官方文档建议把 API Key 放在环境变量或服务端密钥管理中，不要放进浏览器代码。[OpenAI API 快速开始](https://platform.openai.com/docs/quickstart/make-your-first-api-request)

## 安装依赖并启动

Windows 可以双击：

```text
启动推送助手.bat
```

也可以在 PowerShell 中运行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python src\launch_chat.py
```

建议为这个项目单独建虚拟环境（上面的 `.venv`），不要和电脑上其他 Python 环境混用。`启动推送助手.bat` 会优先使用项目里的 `.venv`。

浏览器打开：<http://127.0.0.1:8000>

如果页面显示“等待配置 API 密钥”，检查 `.env` 是否位于项目根目录，并确认修改后重新启动了服务。

## 工作流怎么用

点击左侧“新建活动”，按以下顺序操作：

1. **Brainstorm**：拖入群聊、PDF、Word、表格、图片等资料，整理出可编辑的活动关键信息。
2. **策划**：补充要求，选择详细版、中等版、简洁版模板，生成可下载的 Word/PDF 策划案，人工修改后可重新导出。
3. **内容制作**：按需勾选图文推送、海报、问卷、PPT，生成结果后人工复核。

图片规则如下：

- `data/学校学院/首图.*` 固定放在推送开头。
- `data/学校学院/尾图.*` 固定放在推送结尾。
- `data/过渡图标/` 作为正文分隔图标候选。
- 往期推送图片只用于检索和排版模板参考，不作为本次活动配图。
- 用户上传图片可以填写用途和位置，支持首图、正文、尾图或自动判断。

## 你发送的数据包怎么生成

如果需要从当前电脑重新导出一份共享数据包，在项目根目录运行：

```powershell
python src\export_shared_bundle.py --output D:\coe_shared
```

默认导出：

- `data/articles.sqlite3`
- `data/media/`
- `data/articles/`
- `data/学校学院/`
- `data/过渡图标/`
- `manifest.json` 和文件校验值

需要增加其他素材文件夹时：

```powershell
python src\export_shared_bundle.py --output D:\coe_shared `
  --folder 学校学院 --folder 过渡图标 --folder 迎新专用
```

数据包可以通过学院网盘、OneDrive 或对象存储发送。不要把含有 API Key、活动草稿或个人附件的数据包上传到公开位置。

## 局域网访问

如果只想让同一局域网的人访问你电脑上运行的服务，在 `.env` 中设置：

```text
APP_HOST=0.0.0.0
APP_PORT=8000
```

然后重启服务，启动窗口会显示局域网地址。当前版本已取消访问码，因此只建议在可信局域网中使用；合作者仍然可以各自 clone 仓库、放入同一份数据包，并使用自己的 API Key 独立运行。

## 数据和代码的边界

- GitHub：程序代码、网页、模板、提示词和导出脚本。
- 你发送的数据包：历史推送数据库、历史图片和指定素材。
- 每台电脑本地：API Key、活动草稿、上传附件、生成的 Word/PDF/HTML。

SQLite 适合每个人各自使用一份只读历史数据库。多人同时修改同一份活动记录时，不要把 SQLite 文件放在共享文件夹里；以后如果需要多人实时编辑，再升级到 PostgreSQL 加对象存储。

更多内容见：

- [数据库共享方案.md](references/数据库共享方案.md)
- [本地调试说明.md](references/本地调试说明.md)
- [工作流Agent分工方案.md](references/工作流Agent分工方案.md)
