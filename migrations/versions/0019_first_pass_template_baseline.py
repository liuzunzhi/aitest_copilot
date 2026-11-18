"""第一遍模板补「基线目标清单」说明

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-18

06 期真实模型联调（L2）暴露的问题：种子模板的 system prompt 里
示例写的是 `"target_id": 1`，真实模型**照抄了这个示例值**，
而项目里真实的基线目标 id 根本不是 1 —— 于是所有结论都被
AC-79 判成越界丢弃，整次分析跑完一条结论都没有。

同时补一句「target_id 必须取自下方清单」，让模型知道 id 从哪来。

模板正文变了 → `version_no` +1（与 T85「正文变化才升版本」同一口径）。
迁移 0013 播种的原文保留不动，这里只做增量升级——
改老迁移会让已部署的库与新库分叉。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TEMPLATE_NAME = "增量分析·第一遍·章节局部"

OLD_SYSTEM_PROMPT = (
    "[INCREMENTAL_SYSTEM] 你是需求变更分析助手。\n"
    "根据章节正文，判断基线中哪些功能或功能点发生了变更。\n"
    "只输出 JSON：{\"conclusions\": [{\"target_type\": \"function|feature_point\", "
    "\"target_id\": 1, \"label_type\": \"changed|affected|unchanged\", "
    "\"confidence\": 0.8, \"rationale\": \"理由\"}]}。\n"
    "不要输出 JSON 之外的任何内容；不要使用 new 标签。"
)

NEW_SYSTEM_PROMPT = (
    "[INCREMENTAL_SYSTEM] 你是需求变更分析助手。\n"
    "根据章节正文，判断基线中哪些功能或功能点发生了变更。\n"
    "只输出 JSON：{\"conclusions\": [{\"target_type\": \"function|feature_point\", "
    "\"target_id\": 123, \"label_type\": \"changed|affected|unchanged\", "
    "\"confidence\": 0.8, \"rationale\": \"理由\"}]}。\n"
    "target_type 只能是 function 或 feature_point；"
    "target_id 必须取自用户提示词里「可对照的基线目标」清单中的编号，"
    "不要臆造编号，也不要输出清单之外的目标。\n"
    "不要输出 JSON 之外的任何内容；不要使用 new 标签。"
)


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE prompt_templates "
            "SET system_prompt = :new, version_no = version_no + 1 "
            "WHERE name = :name AND system_prompt = :old"
        ).bindparams(new=NEW_SYSTEM_PROMPT, old=OLD_SYSTEM_PROMPT, name=TEMPLATE_NAME)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE prompt_templates "
            "SET system_prompt = :old, version_no = version_no - 1 "
            "WHERE name = :name AND system_prompt = :new"
        ).bindparams(new=NEW_SYSTEM_PROMPT, old=OLD_SYSTEM_PROMPT, name=TEMPLATE_NAME)
    )
