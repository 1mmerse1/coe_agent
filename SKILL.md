---
name: coe-agent
description: 运行和维护"工映青春"学生会活动策划与公众号推送助手：整理活动底稿、生成策划案、写公众号推送/海报/问卷/PPT、检索历史推文、导入公众号文章到本地库。当用户提到活动策划、推送文案、公众号排版、秀米 HTML、历史推文检索或本仓库的启动与调试时使用。
---

# 学生会活动策划与推送助手

本地运行的 FastAPI 服务 + 网页工作台。它把"办一场活动"拆成工作流，由多个 Agent 分别负责 Brainstorm 整理、策划案、推送、海报、问卷、PPT 和发布前复核，并保留人工确认环节。

## 目录约定

| 路径 | 用途 |
|---|---|
| `src/` | 应用代码（`app.py` 是服务入口，`paths.py` 统一解析目录） |
| `src/web/index.html` | 前端页面，由服务在 `/` 提供 |
| `scripts/` | 独立采集脚本：从微信客户端缓存或网页导出文章链接 |
| `references/` | 规则、规划和说明文档 |
| `resources/planning_templates/` | 策划案范例与编写要求（运行时读取） |
| `resources/article_reference/` | 历史文章参考语料（全文 jsonl、索引、Markdown） |
| `data/` | 运行数据，已被 `.gitignore` 忽略 |

**所有代码都通过 `src/paths.py` 取路径**。新增模块请从它导入 `DATA_DIR`、`RESOURCES_DIR` 等常量，不要在文件里重新写 `Path(__file__).parent`。

## 启动与调试

```powershell
python -m venv .\.venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python .\src\launch_chat.py          # 或双击 启动推送助手.bat
```

命令行调试服务用 `python -m uvicorn app:app --app-dir src --reload --port 8000 --ws none`，状态接口是 `GET /api/status`。模型 API Key 只写在根目录 `.env`（模板见 `.env.example`），后端读取，不下发到浏览器。

导入公众号文章：双击 `开始导入.bat`，或 `python src\importer.py import "链接清单.txt"`（默认读根目录 `推送URL_test.txt`）。

## 必守规则

1. `references/推送Agent最高层指示.md` 优先级最高，生成推送前必须读；`app.py` 在运行时加载它。
2. 历史文章只能参考语气、顺序和模板，**不能**补全本次活动的事实。
3. 缺少的时间、地点、人名、人数、报名方式、审核人一律写 `[待确认]` / `[待填写]`，不得编造。
4. 所有模型产物都是"初稿"，必须人工复核后才进入下一步或发布。
5. 推送 HTML 要能直接导入秀米：用行内样式，正文 16 号、行距 1.8、字距 2px。

## 延伸阅读

- [本地调试说明](references/本地调试说明.md)
- [工作流Agent分工方案](references/工作流Agent分工方案.md)
- [公众号文章入库实现规划](references/公众号文章入库实现规划.md)
- [图文Agent实现规划](references/图文Agent实现规划.md)
- [数据库共享方案](references/数据库共享方案.md)
