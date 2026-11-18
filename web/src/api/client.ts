import axios from 'axios'

const TOKEN_KEY = 'aitest.token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

export const client = axios.create({ baseURL: '/api' })

client.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

client.interceptors.response.use(
  (response) => response,
  (error) => {
    // 401 只在「拿着令牌被拒」时清场；登录接口自身的 401 交给页面提示。
    if (error.response?.status === 401 && getToken()) {
      clearToken()
      if (window.location.pathname !== '/login') {
        window.location.assign('/login')
      }
    }
    return Promise.reject(error)
  },
)

/** 后端错误体固定为 `{code, message}`，这里统一取人话。 */
const CODE_TEXT: Record<string, string> = {
  PROJECT_ARCHIVED: '项目已归档，不能再修改',
  NOT_PROJECT_MEMBER: '你不是该项目成员',
  NOT_PROJECT_ADMIN: '只有项目管理员可以操作',
  LAST_PROJECT_ADMIN: '项目至少保留一名项目管理员',
  CANNOT_REMOVE_SELF: '不能移除自己',
  INVALID_APPLICATION_STATUS: '该申请已处理，不能重复操作',
  INVALID_GLOBAL_ROLE: '角色不合法',
  FORBIDDEN: '没有权限执行该操作',
  UNSUPPORTED_DOC_TYPE: '只支持 .md / .docx / .txt / .pdf 文档',
  DOC_TOO_LARGE: '文档超过 10MB 上限',
  EMPTY_DOCUMENT: '文档没有可解析的内容',
  DOCUMENT_PARSE_FAILED: '文档解析失败，请检查文件是否损坏',
  DOCUMENT_NAME_TAKEN: '同名文档已存在，请改名后重新上传',
  DOCUMENT_NOT_FOUND: '文档不存在',
  DOCUMENT_VERSION_NOT_FOUND: '文档版本不存在',
  INVALID_VERSION_STATUS: '当前版本状态不允许该操作',
  /* 功能基线（04） */
  DUPLICATE_MODULE_NAME: '同项目已存在同名模块',
  DUPLICATE_FUNCTION_NAME: '同模块已存在同名功能',
  DUPLICATE_FEATURE_POINT_NAME: '同功能已存在同名功能点',
  MODULE_NOT_EMPTY: '模块下还有功能，请先迁移或删除功能',
  MODULE_NOT_FOUND: '模块不存在',
  FUNCTION_NOT_FOUND: '功能不存在',
  FEATURE_POINT_NOT_FOUND: '功能点不存在',
  INVALID_MIGRATE_TARGET: '目标模块不合法，请选择同项目的其他模块',
  DUPLICATE_LABEL: '该对象在同一基线版本下已有同类型生效标签',
  INVALID_LABEL_TYPE: '标签类型不合法',
  LABEL_NOT_FOUND: '标签不存在',
  LABEL_ALREADY_CLEARED: '该标签已清除，不能重复清除',
  CLEAR_REASON_REQUIRED: '请选择清除原因',
  INVALID_CLEAR_REASON: '清除原因不合法',
  CLEAR_NOTE_REQUIRED: '清除原因为「其他」时必须填写备注',
  REVIEW_NOT_FOUND: '基线审核记录不存在',
  INVALID_REVIEW_STATUS: '当前审核状态不允许该操作',
  REVIEW_COMMENT_REQUIRED: '驳回必须填写意见',
  SELF_APPROVAL_FORBIDDEN: '不能审核自己提交的基线',
  SNAPSHOT_NOT_FOUND: '基线快照不存在',
  SNAPSHOT_REFERENCED: '该快照仍被引用，请先解除引用',
  TRACE_FIELDS_READONLY: '来源追溯字段只读，不能手工修改',
  /* 从文档推导基线 */
  BASELINE_DERIVE_NOT_FOUND: '推导记录不存在',
  BASELINE_DERIVE_STATUS_INVALID: '推导未成功或已决策，当前状态不允许该操作',
  ADOPT_TARGET_INVALID: '复用目标不合法，请选择同层级的同类实体',
  ADOPT_ALREADY_DECIDED: '该候选已采纳或已跳过，不能重复操作',
  ADOPT_CANDIDATE_NOT_FOUND: '候选不存在',
  /* 分点审核 */
  INVALID_REVIEW_ITEM: '审核条目的实体类型不合法',
  INVALID_REVIEW_DECISION: '审核结论不合法',
  REVIEW_ITEM_NOT_FOUND: '审核对象不存在或不属于该项目',
  REVIEW_ITEM_COMMENT_REQUIRED: '驳回条目必须填写意见',
  EMPTY_REVIEW_APPROVAL: '至少通过一条才能生成快照',
  /* 增量分析（05） */
  INCREMENTAL_ANALYSIS_NOT_FOUND: '分析记录不存在',
  BASELINE_REVISION_REQUIRED: '请选择审核通过的基线快照',
  NO_ACTIVE_DOCUMENT_VERSION: '文档版本不存在或不属于该项目',
  DOCUMENT_VERSION_NOT_ANALYZABLE: '只有生效版本可参与分析',
  TEMPLATE_NOT_FOUND: '提示词模板不存在',
  TEMPLATE_DISABLED: '提示词模板已停用',
  INVALID_SPLIT_GRANULARITY: '本期只支持按章节切分',
  LLM_CALL_FAILED: '模型调用失败，分析已终止',
  LLM_OUTPUT_INVALID: '模型输出不合法，分析已终止',
  /* 增量分析第二期（第二遍 + 引用图） */
  INVALID_CHAPTER_LINK: '引用关系不合法：目标章节与实体名必须二选一',
  DUPLICATE_CHAPTER_LINK: '相同的引用关系已存在',
  SECOND_PASS_NOT_READY: '第一遍分析尚未成功，不能执行第二遍',
  SECOND_PASS_TEMPLATE_MISSING: '第二遍提示词模板缺失或已停用',
  SECOND_PASS_CONFLICTS_PENDING: '仍有待裁决的冲突，请先完成裁决再重跑',
  CONFLICT_NOT_FOUND: '冲突记录不存在',
  CONFLICT_ALREADY_RESOLVED: '该冲突已完成裁决，不能重复处理',
  INVALID_CONFLICT_RESOLUTION: '裁决参数不合法：确认需选择标签，驳回不带标签',
  /* 增量分析第三期（产出段） */
  APPLY_NOT_READY: '第二遍尚未成功，不能应用产出',
  APPLY_CONFLICTS_PENDING: '仍有待裁决的冲突，请先完成裁决再应用产出',
  APPLY_NO_LABELABLE_TARGET: '没有可落标签的变更 / 受影响目标',
  /* 系统设置：大模型与提示词模板（06） */
  LLM_PROVIDER_NOT_FOUND: '大模型配置不存在',
  LLM_PROVIDER_NAME_TAKEN: '配置名已存在',
  LLM_PROVIDER_INVALID: '大模型配置不合法',
  LLM_CONFIG_INVALID: 'API Key 解密失败，请重新填写密钥',
  PROMPT_TEMPLATE_NOT_FOUND: '提示词模板不存在',
  PROMPT_TEMPLATE_INVALID: '提示词模板不合法',
  PROMPT_TEMPLATE_NAME_TAKEN: '同一任务类型下模板名已存在',
}

/**
 * 这些错误码以后端返回的 message 为准——静态文案说不出「被什么引用」。
 * 快照被引用时后端会区分「标签引用」与「增量分析引用」，用户要按提示去处理。
 */
const BACKEND_MESSAGE_CODES = new Set([
  'SNAPSHOT_REFERENCED',
  // 校验类错误码的静态文案说不出「超时必须在 1~300 秒之间」这类具体原因
  'LLM_PROVIDER_INVALID',
  'PROMPT_TEMPLATE_INVALID',
])

export function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data as { code?: string; message?: string } | undefined
    if (data?.code && CODE_TEXT[data.code] && !BACKEND_MESSAGE_CODES.has(data.code)) {
      return CODE_TEXT[data.code]
    }
    if (data?.message && data.message !== data.code) {
      return data.message
    }
    return '请求失败'
  }
  return error instanceof Error ? error.message : '请求失败'
}

/** 读后端错误码，用于「项目已归档」这类特定提示。 */
export function errorCode(error: unknown): string | undefined {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data as { code?: string } | undefined
    return data?.code
  }
  return undefined
}
