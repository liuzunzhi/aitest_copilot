import { Tag } from 'antd'

import type { IncrementalAnalysis } from '../api'

/** 本期后端不提供模板列表接口（spec §2.2：不做模板 CRUD）。 */
export const DEFAULT_TEMPLATE_ID = 1
export const TEMPLATE_LABEL = '增量分析·第一遍·章节局部'
export const GRANULARITY_LABEL = '按章节（chapter）'

export const STATUS_META: Record<string, { label: string; color: string }> = {
  pending: { label: '排队中', color: 'default' },
  running: { label: '执行中', color: 'processing' },
  succeeded: { label: '成功', color: 'success' },
  failed: { label: '失败', color: 'error' },
}

/** 第二遍状态：`null` 表示「未执行」，不是失败。 */
export const SECOND_PASS_STATUS_META: Record<string, { label: string; color: string }> = {
  running: { label: '执行中', color: 'processing' },
  succeeded: { label: '成功', color: 'success' },
  failed: { label: '失败', color: 'error' },
}

export const LABEL_META: Record<string, { label: string; color: string }> = {
  changed: { label: '变更', color: 'orange' },
  affected: { label: '受影响', color: 'blue' },
  unchanged: { label: '未变更', color: 'default' },
  new: { label: '新增', color: 'green' },
}

export const TARGET_LABELS: Record<string, string> = {
  function: '功能',
  feature_point: '功能点',
}

export const CONFLICT_TYPE_META: Record<string, { label: string; color: string }> = {
  conflict: { label: '证据冲突', color: 'orange' },
  possible_impact: { label: '可能连带', color: 'purple' },
  new: { label: '新增', color: 'green' },
}

export const CONFLICT_STATUS_META: Record<string, { label: string; color: string }> = {
  pending: { label: '待裁决', color: 'default' },
  confirmed: { label: '已确认', color: 'success' },
  rejected: { label: '已驳回', color: 'default' },
}

export const LINK_TYPE_META: Record<string, { label: string; color: string }> = {
  references: { label: '引用', color: 'blue' },
  depends_on: { label: '依赖', color: 'purple' },
  mentions_entity: { label: '提及实体', color: 'default' },
}

/** 丢弃标识 → 中文（只出现在 stats.discarded，不会作为 HTTP 错误码）。 */
export const DISCARD_LABELS: Record<string, string> = {
  INCREMENTAL_TARGET_OUT_OF_BASELINE: '目标不在基线内',
  INCREMENTAL_LABEL_NEW_DROPPED: '第一遍返回「新增」',
}

export function statusTag(status: IncrementalAnalysis['status'] | string) {
  const meta = STATUS_META[status] ?? { label: status, color: 'default' }
  return <Tag color={meta.color}>{meta.label}</Tag>
}

export function labelTag(labelType: string) {
  const meta = LABEL_META[labelType] ?? { label: labelType, color: 'default' }
  return <Tag color={meta.color}>{meta.label}</Tag>
}

export function secondPassStatusTag(status: string | null | undefined) {
  if (!status) return <Tag color="default">未执行</Tag>
  const meta = SECOND_PASS_STATUS_META[status] ?? { label: status, color: 'default' }
  return <Tag color={meta.color}>{meta.label}</Tag>
}

export function conflictTypeTag(conflictType: string) {
  const meta = CONFLICT_TYPE_META[conflictType] ?? { label: conflictType, color: 'default' }
  return <Tag color={meta.color}>{meta.label}</Tag>
}

export function conflictStatusTag(status: string) {
  const meta = CONFLICT_STATUS_META[status] ?? { label: status, color: 'default' }
  return <Tag color={meta.color}>{meta.label}</Tag>
}

export function linkTypeTag(linkType: string) {
  const meta = LINK_TYPE_META[linkType] ?? { label: linkType, color: 'default' }
  return <Tag color={meta.color}>{meta.label}</Tag>
}
