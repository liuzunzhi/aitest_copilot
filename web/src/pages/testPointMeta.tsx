import { Tag } from 'antd'

import type { TestPointAnalysisStatus, TestPointPriority, TestPointStatus } from '../api'

export const PRIORITY_META: Record<TestPointPriority, { label: string; color: string }> = {
  high: { label: '高', color: 'red' },
  medium: { label: '中', color: 'orange' },
  low: { label: '低', color: 'default' },
}

export const POINT_STATUS_META: Record<TestPointStatus, { label: string; color: string }> = {
  pending: { label: '待评审', color: 'processing' },
  approved: { label: '已通过', color: 'success' },
  rejected: { label: '已驳回', color: 'error' },
}

export const ANALYSIS_STATUS_META: Record<
  TestPointAnalysisStatus,
  { label: string; color: string }
> = {
  pending: { label: '排队中', color: 'default' },
  running: { label: '执行中', color: 'processing' },
  succeeded: { label: '成功', color: 'success' },
  failed: { label: '失败', color: 'error' },
}

export const TARGET_LABELS: Record<string, string> = {
  function: '功能',
  feature_point: '功能点',
}

export const SOURCE_LABELS: Record<string, string> = {
  llm: '模型生成',
  manual: '手工新增',
}

/** 丢弃标识 → 中文（只出现在 `stats.discarded`，不是 HTTP 错误码）。 */
export const DISCARD_LABELS: Record<string, string> = {
  TEST_POINT_INVALID: '模型输出不合法',
  TEST_POINT_TARGET_OUT_OF_BASELINE: '目标不在依据清单内',
}

export const PRIORITY_OPTIONS = (Object.keys(PRIORITY_META) as TestPointPriority[]).map(
  (value) => ({ value, label: PRIORITY_META[value].label }),
)

export const POINT_STATUS_OPTIONS = (Object.keys(POINT_STATUS_META) as TestPointStatus[]).map(
  (value) => ({ value, label: POINT_STATUS_META[value].label }),
)

export const TARGET_TYPE_OPTIONS = Object.entries(TARGET_LABELS).map(([value, label]) => ({
  value,
  label,
}))

export function priorityTag(priority: string) {
  const meta = PRIORITY_META[priority as TestPointPriority] ?? { label: priority, color: 'default' }
  return <Tag color={meta.color}>{meta.label}</Tag>
}

export function pointStatusTag(status: string) {
  const meta = POINT_STATUS_META[status as TestPointStatus] ?? { label: status, color: 'default' }
  return <Tag color={meta.color}>{meta.label}</Tag>
}

export function analysisStatusTag(status: string) {
  const meta =
    ANALYSIS_STATUS_META[status as TestPointAnalysisStatus] ?? { label: status, color: 'default' }
  return <Tag color={meta.color}>{meta.label}</Tag>
}

/** 目标展示：`功能 #10096 · 用户扫码登录`（名称是落库快照）。 */
export function targetText(targetType: string, targetId: number, targetName: string): string {
  const label = TARGET_LABELS[targetType] ?? targetType
  return `${label} #${targetId} · ${targetName}`
}
