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
  UNSUPPORTED_DOC_TYPE: '只支持 .md / .docx / .txt 文档',
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
}

/**
 * 这些错误码以后端返回的 message 为准——静态文案说不出「被什么引用」。
 * 快照被引用时后端会区分「标签引用」与「增量分析引用」，用户要按提示去处理。
 */
const BACKEND_MESSAGE_CODES = new Set(['SNAPSHOT_REFERENCED'])

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
