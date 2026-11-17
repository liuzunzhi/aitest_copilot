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

export const LABEL_META: Record<string, { label: string; color: string }> = {
  changed: { label: '变更', color: 'orange' },
  affected: { label: '受影响', color: 'blue' },
  unchanged: { label: '未变更', color: 'default' },
}

export const TARGET_LABELS: Record<string, string> = {
  function: '功能',
  feature_point: '功能点',
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
