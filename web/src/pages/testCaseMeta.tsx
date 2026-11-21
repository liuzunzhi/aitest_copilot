import { Tag } from 'antd'

import type {
  TestCaseAnalysisStatus,
  TestCasePriority,
  TestCaseStatus,
  TestCaseType,
} from '../api'

/**
 * 测试用例的展示常量。
 *
 * **与后端 `app/test_cases/labels.py` 同源**：两边都断言同一组中文，
 * 防止「后端导出写「待评审」、前端列表写「待审核」」这种漂移。
 */
export const CASE_PRIORITY_META: Record<TestCasePriority, { label: string; color: string }> = {
  high: { label: '高', color: 'red' },
  medium: { label: '中', color: 'orange' },
  low: { label: '低', color: 'default' },
}

export const CASE_STATUS_META: Record<TestCaseStatus, { label: string; color: string }> = {
  pending: { label: '待评审', color: 'processing' },
  approved: { label: '已通过', color: 'success' },
  rejected: { label: '已驳回', color: 'error' },
}

export const CASE_TYPE_META: Record<TestCaseType, { label: string; color: string }> = {
  functional: { label: '功能', color: 'blue' },
  api: { label: '接口', color: 'purple' },
  ui: { label: 'UI', color: 'cyan' },
}

export const CASE_ANALYSIS_STATUS_META: Record<
  TestCaseAnalysisStatus,
  { label: string; color: string }
> = {
  pending: { label: '排队中', color: 'default' },
  running: { label: '执行中', color: 'processing' },
  succeeded: { label: '成功', color: 'success' },
  failed: { label: '失败', color: 'error' },
}

export const CASE_SOURCE_LABELS: Record<string, string> = {
  llm: 'AI 生成',
  manual: '手工新增',
}

/** 待复核原因 → 中文（后端给的是稳定枚举，不是自由文本）。 */
export const NEEDS_REVIEW_REASON_LABELS: Record<string, string> = {
  source_point_changed: '所属测试点已变更',
  source_point_deleted: '所属测试点已删除',
}

export const CASE_PRIORITY_OPTIONS = (
  Object.keys(CASE_PRIORITY_META) as TestCasePriority[]
).map((value) => ({ value, label: CASE_PRIORITY_META[value].label }))

export const CASE_STATUS_OPTIONS = (
  Object.keys(CASE_STATUS_META) as TestCaseStatus[]
).map((value) => ({ value, label: CASE_STATUS_META[value].label }))

export const CASE_TYPE_OPTIONS = (Object.keys(CASE_TYPE_META) as TestCaseType[]).map(
  (value) => ({ value, label: CASE_TYPE_META[value].label }),
)

export function casePriorityTag(priority: string) {
  const meta = CASE_PRIORITY_META[priority as TestCasePriority] ?? { label: priority, color: 'default' }
  return <Tag color={meta.color}>{meta.label}</Tag>
}

export function caseStatusTag(status: string) {
  const meta = CASE_STATUS_META[status as TestCaseStatus] ?? { label: status, color: 'default' }
  return <Tag color={meta.color}>{meta.label}</Tag>
}

export function caseTypeTag(type: string) {
  const meta = CASE_TYPE_META[type as TestCaseType] ?? { label: type, color: 'default' }
  return <Tag color={meta.color}>{meta.label}</Tag>
}

export function caseAnalysisStatusTag(status: string) {
  const meta =
    CASE_ANALYSIS_STATUS_META[status as TestCaseAnalysisStatus] ??
    { label: status, color: 'default' }
  return <Tag color={meta.color}>{meta.label}</Tag>
}

/** 来源测试点展示：`#101 · 扫码登录连续失败 5 次锁定`。 */
export function testPointText(pointId: number, pointName: string): string {
  return `#${pointId} · ${pointName}`
}
