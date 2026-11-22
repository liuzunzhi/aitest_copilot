import { Tag } from 'antd'

import type {
  AutomationAssetStatus,
  AutomationFramework,
  AutomationResult,
  AutomationRunStatus,
  AutomationScanStatus,
} from '../api'

/**
 * 自动化执行的展示常量（与 `testCaseMeta.tsx` 同构）。
 *
 * **两套状态文案必须分开**（09 期红线）：
 *
 * - `RUN_STATUS_META` 说的是**执行进程**的状态：
 *   `succeeded` = pytest 进程**正常跑完**（**哪怕退出码是 1**——
 *   那只是「有测试失败」，是业务结果）；`failed` = 跑不起来（超时 / 启动失败）。
 * - `RESULT_META` 说的是**明细里用例**的结果：通过 / 失败 / 跳过。
 *
 * 混成一套文案，用户会把「有测试失败」看成「系统执行失败」——
 * 这两件事的处置方式完全不同（前者改用例，后者改环境）。
 */
export const FRAMEWORK_META: Record<AutomationFramework, { label: string; color: string }> = {
  pytest: { label: 'Pytest', color: 'blue' },
  playwright: { label: 'Playwright', color: 'purple' },
}

export const ASSET_STATUS_META: Record<
  AutomationAssetStatus,
  { label: string; color: string }
> = {
  active: { label: '在用', color: 'success' },
  archived: { label: '已归档', color: 'default' },
}

/** 扫描清单里的一项的状态（不是资产本身的状态）。 */
export const SCAN_STATUS_META: Record<AutomationScanStatus, { label: string; color: string }> = {
  new: { label: '未入库', color: 'default' },
  existing: { label: '已入库', color: 'blue' },
}

/** 执行进程的状态。`succeeded` 的文案是「执行完成」而不是「成功」——避免与用例结果混淆。 */
export const RUN_STATUS_META: Record<AutomationRunStatus, { label: string; color: string }> = {
  running: { label: '执行中', color: 'processing' },
  succeeded: { label: '执行完成', color: 'success' },
  failed: { label: '执行失败', color: 'error' },
}

/** 明细里单个资产（用例）的执行结果。 */
export const RESULT_META: Record<AutomationResult, { label: string; color: string }> = {
  passed: { label: '通过', color: 'success' },
  failed: { label: '失败', color: 'error' },
  skipped: { label: '跳过', color: 'default' },
}

/** Playwright 资产的执行入口置灰时的提示（本期只执行 Pytest）。 */
export const PLAYWRIGHT_EXEC_TOOLTIP = 'Playwright 执行能力待后续期'

/** 归档资产的执行入口置灰时的提示（归档的资产不可执行）。 */
export const ARCHIVED_EXEC_TOOLTIP = '已归档的资产不可执行'

export const FRAMEWORK_OPTIONS = (
  Object.keys(FRAMEWORK_META) as AutomationFramework[]
).map((value) => ({ value, label: FRAMEWORK_META[value].label }))

export const ASSET_STATUS_OPTIONS = (
  Object.keys(ASSET_STATUS_META) as AutomationAssetStatus[]
).map((value) => ({ value, label: ASSET_STATUS_META[value].label }))

export function frameworkTag(framework: string) {
  const meta =
    FRAMEWORK_META[framework as AutomationFramework] ?? { label: framework, color: 'default' }
  return <Tag color={meta.color}>{meta.label}</Tag>
}

export function assetStatusTag(status: string) {
  const meta =
    ASSET_STATUS_META[status as AutomationAssetStatus] ?? { label: status, color: 'default' }
  return <Tag color={meta.color}>{meta.label}</Tag>
}

export function scanStatusTag(status: string) {
  const meta =
    SCAN_STATUS_META[status as AutomationScanStatus] ?? { label: status, color: 'default' }
  return <Tag color={meta.color}>{meta.label}</Tag>
}

export function runStatusTag(status: string) {
  const meta = RUN_STATUS_META[status as AutomationRunStatus] ?? { label: status, color: 'default' }
  return <Tag color={meta.color}>{meta.label}</Tag>
}

export function resultTag(result: string) {
  const meta = RESULT_META[result as AutomationResult] ?? { label: result, color: 'default' }
  return <Tag color={meta.color}>{meta.label}</Tag>
}

/** 耗时展示：`820 毫秒` / `1.24 秒`。 */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—'
  if (ms < 1000) return `${ms} 毫秒`
  return `${(ms / 1000).toFixed(2)} 秒`
}

/** 置信度展示：`0.95`；低置信度另加一个标记（由调用方决定）。 */
export function formatConfidence(confidence: number | null | undefined): string {
  if (confidence === null || confidence === undefined) return '—'
  return confidence.toFixed(2)
}
