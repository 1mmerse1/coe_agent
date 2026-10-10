"""统一的目录解析。

应用代码放在 `src/` 下，运行时数据、素材和文档放在仓库根目录的
`data/`、`resources/`、`references/` 中。所有模块都从这里取路径，
这样移动文件时不必各自重新推算目录层级。
"""

from __future__ import annotations

from pathlib import Path


SRC_DIR = Path(__file__).resolve().parent
ROOT_DIR = SRC_DIR.parent

DATA_DIR = ROOT_DIR / "data"
RESOURCES_DIR = ROOT_DIR / "resources"
REFERENCES_DIR = ROOT_DIR / "references"
SCRIPTS_DIR = ROOT_DIR / "scripts"
WEB_DIR = SRC_DIR / "web"

ENV_FILE = ROOT_DIR / ".env"
TEMPLATE_DIR = RESOURCES_DIR / "planning_templates"
ARTICLE_REFERENCE_DIR = RESOURCES_DIR / "article_reference"
GUIDELINES_PATH = REFERENCES_DIR / "推送Agent最高层指示.md"
