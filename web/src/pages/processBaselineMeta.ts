/** 流程基线用到的展示元数据：文案、颜色与下拉选项。 */

import type {
  ProcessRevisionStatus,
  ProcessSourceType,
  ProcessStatus,
  ProcessTargetType,
} from '../api'

/**
 * 场景来源 → 中文与颜色。
 *
 * **值与后端 `source_type` 枚举一致**（spec §5.1）：
 * `manual` = 手工添加、`document_derived` = 文档解析。
 * 写成别的值会让筛选永远命中 0 条。
 */
export const SOURCE_TYPE_META: Record<
  ProcessSourceType,
  { label: string; color: string }
> = {
  manual: { label: '手工添加', color: 'default' },
  document_derived: { label: '文档解析', color: 'blue' },
}

/** 场景状态 → 中文与颜色。 */
export const STATUS_META: Record<ProcessStatus, { label: string; color: string }> = {
  active: { label: '在用', color: 'success' },
  archived: { label: '已归档', color: 'default' },
}

/** 关联目标层级 → 中文。 */
export const TARGET_TYPE_LABELS: Record<ProcessTargetType, string> = {
  function: '功能',
  feature_point: '功能点',
}

/** 快照状态 → 中文与颜色（与 04 的 `REVISION_STATUS_META` 同构）。 */
export const REVISION_STATUS_META: Record<
  ProcessRevisionStatus,
  { label: string; color: string }
> = {
  submitted: { label: '审核中', color: 'processing' },
  approved: { label: '已通过', color: 'success' },
  rejected: { label: '已驳回', color: 'error' },
}

/** 来源类型筛选选项。 */
export const SOURCE_TYPE_OPTIONS = (
  Object.keys(SOURCE_TYPE_META) as ProcessSourceType[]
).map((value) => ({ value, label: SOURCE_TYPE_META[value].label }))

/**
 * 状态筛选选项：默认在用。
 *
 * **归档场景默认不展示**（与 04 的「归档模块默认不展示」同一口径）。
 */
export const STATUS_FILTER_OPTIONS: Array<{
  value: ProcessStatus | 'all'
  label: string
}> = [
  { value: 'active', label: '在用' },
  { value: 'archived', label: '已归档' },
  { value: 'all', label: '全部' },
]

/** 来源类型的兜底展示（未知值原样透出，不吞掉）。 */
export function sourceTypeText(sourceType: string): { label: string; color: string } {
  return (
    SOURCE_TYPE_META[sourceType as ProcessSourceType] ?? {
      label: sourceType,
      color: 'default',
    }
  )
}

/** 状态的兜底展示。 */
export function statusText(status: string): { label: string; color: string } {
  return STATUS_META[status as ProcessStatus] ?? { label: status, color: 'default' }
}

/** 快照状态的兜底展示。 */
export function revisionStatusText(status: string): { label: string; color: string } {
  return (
    REVISION_STATUS_META[status as ProcessRevisionStatus] ?? {
      label: status,
      color: 'default',
    }
  )
}

/**
 * 快照版本号展示：`v1.{n}`（n 从 0 递增）。
 *
 * 审核中 / 已驳回的记录**还没分配版本号** → 显示占位。
 */
export function formatProcessVersion(versionNo: number | null | undefined): string {
  if (versionNo === null || versionNo === undefined) return '待分配'
  return `v1.${versionNo}`
}

/** 审核期锁定时的提示文案（前端禁用写入口时展示）。 */
export const IN_REVIEW_TIP = '审核中，暂不可编辑'
