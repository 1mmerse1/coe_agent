# 学生会推送档案助手

这是一个本地运行的学生会公众号工作流助手，当前包含：

- 公众号文章 URL 导入本地 SQLite 文章库；
- 历史推送关键词检索和对话查询；
- 使用历史文章作为参考生成活动推送；
- 生成带图片素材和历史模板参考的秀米 HTML 预览；
- 生成后可以复制 HTML 到秀米继续人工修改。
- 按工作流阶段分配 GPT-6 Luna/Sol，并提供 Agent 注册表和流程清单；推送、海报、问卷、PPT 是四个并列下游 Agent。

## 本地运行

1. 安装 Python 3.11 或更新版本。
2. 复制 `.env.example` 为 `.env`，填写 `OPENAI_API_KEY`。
3. 双击 `启动推送助手.bat`，或运行：

   ```powershell
   python -m pip install -r requirements.txt
   python launch_chat.py
   ```

4. 浏览器打开 <http://127.0.0.1:8000>。

## 分享给同一局域网的人

网页必须由你的电脑运行后端，不能只把 HTML 文件发给别人。复制下面三行到本地 `.env` 并修改访问码：

```text
APP_HOST=0.0.0.0
APP_PORT=8000
APP_ACCESS_CODE=请设置一个共享访问码
```

重启 `启动推送助手.bat` 后，启动窗口会显示一个局域网地址，例如 `http://192.168.1.23:8000`。把这个地址和访问码发给同一局域网的人即可。访问码通过后端 Cookie 保存，AI API Key 只在你的电脑后端使用，不会发给浏览器。

如果别人无法打开，确认两台电脑在同一个 Wi-Fi 或局域网，并在 Windows 防火墙提示时允许 Python 在“专用网络”通信。不要把 `APP_HOST=0.0.0.0` 的服务直接暴露到公网；需要公网访问时，应放到有 HTTPS、登录和反向代理的服务器上。

## 导入公众号文章

把公众号文章链接逐行放进 `推送URL_test.txt`，运行 `开始导入.bat`。文章数据库、图片和预览会保存在本地 `data/` 目录，该目录默认不会提交到 GitHub。

## 生成秀米预览

在网页中点击“办活动”进入工作台，点击左侧“新建活动”创建新记录，按 Brainstorm → 策划 → 内容制作三步推进。第一步整理长篇对话总结/群聊消息，第二步结合补充信息生成策划案，第三步可选生成图文推送、海报、问卷或 PPT。图文推送会生成秀米 HTML 和本地预览页面。旧的 `POST /api/generate-push-html` 和 `/api/generate-xiumi-push` 仍兼容。

活动各阶段支持拖入 TXT、Markdown、CSV、JSON、PDF、DOCX、XLSX、PPTX、ODT、ODS、ODP 和图片。常见文档由本地服务提取文字；扫描版 PDF 的前 6 页会作为页面图像送给视觉模型。单文件上限 12 MB，文本只截取前 6000 字进入当前 Agent 提示词。Brainstorm 底稿以可编辑卡片呈现，修改后同步到下一阶段；高级编辑可展开原始 JSON。左侧的 Brainstorm 建议 Agent 会读取当前页面已填写的资料、关键信息、策划案和内容要求，回答活动创意与下一步建议。

“办一场活动”会自动保存到本地活动历史。左侧可新建或切换活动，保存输入、附件、Brainstorm 底稿、策划案及内容制作结果。策划阶段可选详细版（新生手册类）、中等版（交流会类）、简洁版（图书漂流类），也可由 Agent 自动匹配。三份策划案范例和编写要求保存在 `resources/planning_templates/`，只作为结构与写法参考。生成策划案时同时生成可下载的 Word 和 PDF；人工修改页面正文后，可点击“按当前修改重新导出”。活动数据库、素材和导出文件保存在本地 `data/` 目录。

内容制作阶段会根据活动名称检索 `data/` 中的学院图片素材，页面显示缩略图与出处，默认推荐少量图片，可勾选或取消。勾选图片由本地服务转成较小的 JPEG 预览后发给图文、海报和 PPT Agent，无须重复上传。JPG、PNG、GIF、WebP、可读取的 PSD，以及内含 PDF 预览的 AI 文件可供检索；无法生成预览的设计源文件需先导出 JPG/PNG。历史推送图片保留在文章库中用于检索和排版模板提取，不会作为本次活动配图。推送 Agent 可以从已勾选的学院素材中选图，后端核对后嵌入 HTML。

素材规则：`data/学校学院/首图.*` 和 `data/学校学院/尾图.*` 是推送固定首图、尾图；`data/过渡图标/` 只作为正文分隔图标候选，历史推送图片暂不作为本次配图。用户上传图片时可以填写用途和位置。历史推送排版模板可从文章 HTML 中提取多种样式，模板只包含排版属性，不包含往期事实。

Agent 会从本地历史文章中选择相似排版风格，生成带行内样式的 HTML。打开预览后可以复制 HTML 到秀米，再进行人工修改和审核。

## 配置说明

旧接口默认模型仍是 `gpt-6-sol`，推理强度为 `high`。工作流接口使用：

- `gpt-6-luna`：消息整合、历史检索、海报字段、问卷等高频结构化任务；
- `gpt-6-sol`：策划案、推送 HTML、PPT 叙事、活动总结对照和发布前复核。

当前 Luna 暂时不可用，原本分配给 Luna 的角色已临时映射到 `gpt-6-sol` + `low`。复杂 Agent 继续使用 `gpt-6-sol` + `high`。可以在 `.env` 中分别设置 `OPENAI_MODEL_LUNA`、`OPENAI_MODEL_SOL`、`OPENAI_REASONING_LUNA` 和 `OPENAI_REASONING_SOL`。`OPENAI_BASE_URL` 可以配置为 OpenAI 兼容服务地址，例如 Aizex Codex API。真实密钥只放在本地 `.env`，不要提交到仓库。

完整的阶段、输入输出合同和人工卡点见 [工作流Agent分工方案.md](工作流Agent分工方案.md)。管理页面可通过 `GET /api/workflow/manifest` 读取流程定义。

`POST /api/workflow/route` 接收 `{"task_type":"push|poster|survey|ppt"}`，返回对应的并列 Agent 和模型配置。

本地自动重载、接口测试和秀米 HTML 预览调试步骤见 [本地调试说明.md](本地调试说明.md)。

历史推送数据库和部分图片素材的共享方式见 [数据库共享方案.md](数据库共享方案.md)。可以运行 `python export_shared_bundle.py --output D:\coe_shared` 导出一个不含密钥和活动草稿的共享数据包。
