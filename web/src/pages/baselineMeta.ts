/** 基线树用到的展示元数据：文案、颜色与下拉选项。 */

import type { BaselineStatusFilter, ClearReason, LabelType } from '../api'

/** 标签类型 → 中文与颜色（功能级 / 功能点级通用，互不汇总）。 */
export const LABEL_TYPE_META: Record<LabelType, { label: string; color: string }> = {
  new: { label: '新增', color: 'green' },
  changed: { label: '变更', color: 'orange' },
  affected: { label: '受影响', color: 'gold' },
  unchanged: { label: '无变化', color: 'default' },
}

/** 标签类型下拉选项（筛选用）。 */
export const LABEL_TYPE_OPTIONS = (Object.keys(LABEL_TYPE_META) as LabelType[]).map((type) => ({
  value: type,
  label: LABEL_TYPE_META[type].label,
}))

/** 清除原因 → 中文说明（6 类枚举，后端强校验）。 */
export const CLEAR_REASON_META: Record<ClearReason, string> = {
  requirement_done: '需求已实现',
  requirement_cancelled: '需求已取消',
  misjudged: '之前判断有误',
  priority_changed: '优先级变化',
  duplicate_label: '标签重复',
  other: '其他',
}

/** 清除原因下拉选项。 */
export const CLEAR_REASON_OPTIONS = (Object.keys(CLEAR_REASON_META) as ClearReason[]).map(
  (reason) => ({ value: reason, label: CLEAR_REASON_META[reason] }),
)

/** 功能 / 功能点来源下拉选项（AC-63：来源只展示，不可编辑）。 */
export const SOURCE_TYPE_OPTIONS = [
  { value: 'manual', label: '手工添加' },
  { value: 'document', label: '文档解析' },
]

/** 模块状态筛选选项（归档模块默认不参与展示，spec §2.3 第 5 条）。 */
export const STATUS_FILTER_OPTIONS: Array<{ value: BaselineStatusFilter; label: string }> = [
  { value: 'active', label: '在用' },
  { value: 'archived', label: '归档' },
  { value: 'all', label: '全部' },
]
