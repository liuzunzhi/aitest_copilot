/** 功能基线页两个组件共用的常量与工具。 */

/**
 * 快照版本号展示：`v1.{n}`（n 从 0 递增，见 spec §2.3.1）。
 * 审核中/驳回的记录还没分配版本号 → 显示占位。
 */
export function formatSnapshotVersion(versionNo: number | null | undefined): string {
  return versionNo === null || versionNo === undefined ? '待分配' : `v1.${versionNo}`
}

/**
 * 表单校验失败时 rc-field-form 抛的是 `{errorFields, ...}`，不是 Error。
 * 校验提示由表单就地渲染，这里只把它认出来——
 * 否则会弹一句没意义的「请求失败」。
 */
export function isValidationError(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    'errorFields' in error &&
    Array.isArray((error as { errorFields?: unknown[] }).errorFields)
  )
}

/** 打标对象：功能级 / 功能点级。 */
export interface LabelTarget {
  targetType: 'function' | 'feature_point'
  targetId: number
  name: string
}
