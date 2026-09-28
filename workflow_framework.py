"""Agent roles and workflow contracts for the college publicity assistant.

This module deliberately contains policy and routing metadata only.  The actual
model call stays in :mod:`app` so existing endpoints and provider fallbacks keep
working.  Keeping the contracts here makes it possible to add poster, survey,
PPT, and activity-summary agents without scattering model choices through the
HTTP handlers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


ModelName = Literal["luna", "sol"]


@dataclass(frozen=True)
class AgentPolicy:
    key: str
    label: str
    model: ModelName
    reasoning: str
    purpose: str
    input_contract: str
    output_contract: str
    human_gate: str
    fallback: ModelName


# Luna handles repeatable extraction and formatting.  Sol is reserved for
# decisions that compare several sources, make a plan, or perform a final QA.
AGENT_POLICIES: dict[str, AgentPolicy] = {
    "brainstorm_advisor": AgentPolicy(
        key="brainstorm_advisor",
        label="Brainstorm 建议 Agent",
        model="luna",
        reasoning="low",
        purpose="读取当前活动工作台的全部已输入信息，回答活动创意、流程和下一步建议。",
        input_contract="当前 Brainstorm 底稿、策划案、补充要求、素材和已选内容",
        output_contract="针对用户问题给出建议；区分已知信息、推断和待确认事项",
        human_gate="建议必须由用户决定是否写回活动资料",
        fallback="sol",
    ),
    "archive_qa": AgentPolicy(
        key="archive_qa",
        label="历史推送检索 Agent",
        model="luna",
        reasoning="low",
        purpose="根据本地文章库回答历史案例问题，并明确区分发布和活动发生时间。",
        input_contract="用户问题、检索命中的文章摘录和来源链接",
        output_contract="简洁回答、依据文章、资料不足提示",
        human_gate="涉及对外复用时人工确认原文和事实",
        fallback="sol",
    ),
    "message_integrator": AgentPolicy(
        key="message_integrator",
        label="消息整合 Agent",
        model="luna",
        reasoning="low",
        purpose="整理录音、群聊、图片 OCR 结果和补充说明，建立事实清单。",
        input_contract="原始文字、图片描述、补充信息",
        output_contract="结构化活动事实；未知字段写 [待确认]；附证据来源",
        human_gate="策划前确认时间、地点、对象、人数、链接和审核人",
        fallback="sol",
    ),
    "planning_agent": AgentPolicy(
        key="planning_agent",
        label="策划案 Agent",
        model="sol",
        reasoning="high",
        purpose="基于已确认事实和历史案例生成目标、主题、流程、执行方案和传播口径。",
        input_contract="事实清单、策划要求、历史案例检索结果",
        output_contract="结构化策划案；区分事实、建议和待确认项",
        human_gate="确认事实、活动要求、口径和执行可行性",
        fallback="luna",
    ),
    "push_router": AgentPolicy(
        key="push_router",
        label="推送 Router",
        model="luna",
        reasoning="none",
        purpose="根据审核后的策划案和用户选择，把任务分配给专业内容 Agent。",
        input_contract="审核后的策划案、自然语言任务、素材权限",
        output_contract="push、poster、survey、ppt 或组合任务的路由结果",
        human_gate="路由前确认任务类型和对外发布范围",
        fallback="sol",
    ),
    "push_agent": AgentPolicy(
        key="push_agent",
        label="推送 Agent",
        model="sol",
        reasoning="high",
        purpose="根据人工确认的策划案生成公众号推送文案、可编辑 HTML 和浏览器预览。",
        input_contract="审核后的策划案、推送类型、历史案例、排版规则和图片素材",
        output_contract="标题、导语、正文结构、活动信息、审核项、秀米兼容 HTML、预览地址",
        human_gate="检查事实、图片顺序、链接、署名和秀米导入效果",
        fallback="luna",
    ),
    "poster_agent": AgentPolicy(
        key="poster_agent",
        label="海报 Agent",
        model="luna",
        reasoning="medium",
        purpose="选择海报模板、填充字段、整理视觉提示词和可编辑布局参数。",
        input_contract="策划案、素材库、模板库、品牌规范",
        output_contract="可编辑 SVG/HTML 模板数据；图片清单和生成提示词",
        human_gate="检查校徽、文字、时间、二维码和图片版权",
        fallback="sol",
    ),
    "survey_agent": AgentPolicy(
        key="survey_agent",
        label="问卷 Agent",
        model="luna",
        reasoning="low",
        purpose="生成报名表、调研问卷、字段说明和回收提示。",
        input_contract="活动目标、对象、报名限制、隐私要求",
        output_contract="结构化问卷字段、选项、必填规则和导出格式",
        human_gate="确认隐私、敏感字段、截止时间和收集范围",
        fallback="sol",
    ),
    "ppt_agent": AgentPolicy(
        key="ppt_agent",
        label="PPT Agent",
        model="sol",
        reasoning="high",
        purpose="把策划案转成汇报、宣讲或复盘所需的叙事结构和页级内容。",
        input_contract="策划案、数据、图片素材、受众和时长",
        output_contract="页级大纲、讲稿、图表数据和素材占位符",
        human_gate="检查数据、页数、演讲时长和对外口径",
        fallback="luna",
    ),
    "summary_integrator": AgentPolicy(
        key="summary_integrator",
        label="总结消息整合 Agent",
        model="luna",
        reasoning="medium",
        purpose="整理茶话会录音、细节补充和活动照片，形成实际活动记录。",
        input_contract="现场录音转写、补充文字、活动图片和基础元数据",
        output_contract="实际活动事实清单；标注图片和文字证据；未知项待确认",
        human_gate="确认人员、照片、数据和活动实际发生情况",
        fallback="sol",
    ),
    "summary_agent": AgentPolicy(
        key="summary_agent",
        label="总结推送 Agent",
        model="sol",
        reasoning="high",
        purpose="对照原策划案与实际记录，生成活动回顾、成果和可复用经验。",
        input_contract="实际活动记录、之前的策划案、历史总结推送",
        output_contract="原计划/实际对照、回顾推送初稿、复盘要点和待核对项",
        human_gate="发布前核对人名、照片、数据和总结表述",
        fallback="luna",
    ),
    "final_qa": AgentPolicy(
        key="final_qa",
        label="发布前复核 Agent",
        model="sol",
        reasoning="medium",
        purpose="检查事实、排版字段、敏感信息、素材权限和导出完整性。",
        input_contract="最终文案、海报/HTML/PPT、事实清单和审核规则",
        output_contract="阻断项、建议项、通过状态和逐项依据",
        human_gate="人工最终发布决定",
        fallback="luna",
    ),
}


FLOW_DEFINITIONS = {
    "planning": {
        "label": "活动策划与内容生产",
        "stages": [
            "message_integrator",
            "planning_agent",
            "human_review_planning",
            "push_router",
            "push_agent|poster_agent|survey_agent|ppt_agent",
            "final_qa",
            "human_publish_review",
        ],
    },
    "summary": {
        "label": "茶话会结束后的总结工作流",
        "stages": [
            "summary_integrator",
            "summary_agent",
            "human_review_summary",
            "final_qa",
            "human_publish_review",
        ],
    },
}


def get_policy(agent_key: str) -> AgentPolicy:
    """Return a policy or raise a clear error for a misspelled stage."""
    try:
        return AGENT_POLICIES[agent_key]
    except KeyError as exc:
        raise ValueError(f"未知 Agent：{agent_key}") from exc


def manifest() -> dict:
    """JSON-safe description for an admin UI or a future workflow builder."""
    return {
        "agents": {key: asdict(policy) for key, policy in AGENT_POLICIES.items()},
        "flows": FLOW_DEFINITIONS,
        "model_roles": {
            "luna": "高频资料整理、抽取、格式化和常规生成",
            "sol": "复杂规划、跨资料对照、长文叙事和发布前复核",
        },
    }
