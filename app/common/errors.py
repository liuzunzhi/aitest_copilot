"""统一错误响应。

业务错误用 `AppError` 子类表达「HTTP 状态 + 稳定 code」，响应体固定
`{"code": ..., "message": ...}`，前端只按 `code` 分支。
FastAPI 默认的 `HTTPException` 会包成 `{"detail": ...}`，与 spec 的
`{"code": "USERNAME_TAKEN"}` 不一致，所以统一在这里转换。
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """业务错误基类：子类只需声明 status_code 与 code。"""

    status_code = 400
    code = "BAD_REQUEST"

    def __init__(self, message: str | None = None, **extra: object) -> None:
        self.message = message or self.code
        self.extra = extra
        super().__init__(self.message)


class CaptchaRequired(AppError):
    status_code = 400
    code = "CAPTCHA_REQUIRED"


class CaptchaInvalid(AppError):
    status_code = 400
    code = "CAPTCHA_INVALID"


class WeakPassword(AppError):
    status_code = 400
    code = "WEAK_PASSWORD"


class UsernameTaken(AppError):
    status_code = 409
    code = "USERNAME_TAKEN"


class ContactTaken(AppError):
    status_code = 409
    code = "CONTACT_TAKEN"


class InvalidCredentials(AppError):
    """AC-02：用户名不存在、密码错误、账号已删除共用这一个响应。"""

    status_code = 401
    code = "INVALID_CREDENTIALS"


class AccountDisabled(AppError):
    status_code = 403
    code = "ACCOUNT_DISABLED"


class AccountLocked(AppError):
    """AC-04：423 并带 unlock_at，前端据此显示剩余时间。"""

    status_code = 423
    code = "ACCOUNT_LOCKED"


class Unauthenticated(AppError):
    """AC-06：不带令牌或令牌无法识别。"""

    status_code = 401
    code = "UNAUTHENTICATED"


class TokenExpired(AppError):
    status_code = 401
    code = "TOKEN_EXPIRED"


class TokenRevoked(AppError):
    status_code = 401
    code = "TOKEN_REVOKED"


class InvalidResetCode(AppError):
    """联系人不存在、验证码错误或已过期，统一一个响应，不泄露账号是否存在。"""

    status_code = 400
    code = "INVALID_RESET_CODE"


class RateLimited(AppError):
    status_code = 429
    code = "RATE_LIMITED"


class Forbidden(AppError):
    """AC-27 / AC-23：已登录但没有该资源或该操作的权限。"""

    status_code = 403
    code = "FORBIDDEN"


class NotProjectMember(AppError):
    """AC-27：非项目成员访问项目内资源。"""

    status_code = 403
    code = "NOT_PROJECT_MEMBER"


class ProjectNotFound(AppError):
    """项目不存在或已归档——归档项目不再接受申请。"""

    status_code = 404
    code = "PROJECT_NOT_FOUND"


class ProjectNameRequired(AppError):
    """AC-31：项目名称必填。"""

    status_code = 400
    code = "PROJECT_NAME_REQUIRED"


class InvalidProjectName(AppError):
    """AC-31：项目名称超出 128 字符。"""

    status_code = 400
    code = "INVALID_PROJECT_NAME"


class InvalidProjectDescription(AppError):
    """AC-31：项目简介超出 500 字符。"""

    status_code = 400
    code = "INVALID_PROJECT_DESCRIPTION"


class ProjectArchived(AppError):
    """AC-32 / AC-34：归档项目只读，不允许再编辑或维护成员。"""

    status_code = 409
    code = "PROJECT_ARCHIVED"


class ReasonRequired(AppError):
    status_code = 400
    code = "REASON_REQUIRED"


class InvalidDesiredRole(AppError):
    status_code = 400
    code = "INVALID_DESIRED_ROLE"


class AlreadyProjectMember(AppError):
    status_code = 409
    code = "ALREADY_PROJECT_MEMBER"


class DuplicateApplication(AppError):
    status_code = 409
    code = "DUPLICATE_APPLICATION"


class ApplyDisabled(AppError):
    status_code = 403
    code = "APPLY_DISABLED"


class ApplicationNotFound(AppError):
    status_code = 404
    code = "APPLICATION_NOT_FOUND"


class NotApplicationOwner(AppError):
    status_code = 403
    code = "NOT_APPLICATION_OWNER"


class ApplicationNotPending(AppError):
    status_code = 409
    code = "APPLICATION_NOT_PENDING"


class InvalidRoleAssignment(AppError):
    """AC-21：审批通过时授予的角色只允许 project_admin / member / guest。"""

    status_code = 400
    code = "INVALID_ROLE_ASSIGNMENT"


class ApplyCooldown(AppError):
    """AC-22：驳回后的冷却期内再次申请，extra 带 next_available_at。"""

    status_code = 429
    code = "APPLY_COOLDOWN"


class UserNotFound(AppError):
    status_code = 404
    code = "USER_NOT_FOUND"


class InvalidStatus(AppError):
    status_code = 400
    code = "INVALID_STATUS"


class PasswordChangeRequired(AppError):
    """管理员重置密码后，改密前除改密接口外一律拒绝。"""

    status_code = 403
    code = "PASSWORD_CHANGE_REQUIRED"


class NotProjectAdmin(AppError):
    """AC-23：不是该项目管理员（系统管理员除外）。"""

    status_code = 403
    code = "NOT_PROJECT_ADMIN"


class MemberNotFound(AppError):
    """AC-37 / AC-38：目标用户不是该项目成员。"""

    status_code = 404
    code = "MEMBER_NOT_FOUND"


class LastProjectAdmin(AppError):
    """AC-37 / AC-38：项目至少保留一名项目管理员。"""

    status_code = 409
    code = "LAST_PROJECT_ADMIN"


class CannotRemoveSelf(AppError):
    """AC-38：成员不能通过成员管理移除自己。"""

    status_code = 400
    code = "CANNOT_REMOVE_SELF"


class InvalidApplicationStatus(AppError):
    """AC-41 / AC-43：申请列表的 status 筛选值不合法。"""

    status_code = 400
    code = "INVALID_APPLICATION_STATUS"


class InvalidGlobalRole(AppError):
    """AC-45：global_role 只允许 user / system_admin。"""

    status_code = 400
    code = "INVALID_GLOBAL_ROLE"


class CannotChangeOwnRole(AppError):
    """AC-45：系统管理员不能修改自己的全局角色。"""

    status_code = 400
    code = "CANNOT_CHANGE_OWN_ROLE"


class UnsupportedDocType(AppError):
    """AC-50：只接受 docx / md / txt，PDF 留待后续。"""

    status_code = 400
    code = "UNSUPPORTED_DOC_TYPE"


class DocumentTooLarge(AppError):
    """AC-50：单文件上限 10MB。"""

    status_code = 400
    code = "DOC_TOO_LARGE"


class EmptyDocument(AppError):
    """AC-50：0 字节或解析后没有任何正文。"""

    status_code = 400
    code = "EMPTY_DOCUMENT"


class DocumentParseFailed(AppError):
    """AC-52：docx 结构损坏、无法识别编码等解析失败。"""

    status_code = 400
    code = "DOCUMENT_PARSE_FAILED"


class DocumentNameTaken(AppError):
    """AC-50：同项目文档同名。"""

    status_code = 409
    code = "DOCUMENT_NAME_TAKEN"


class DocumentNotFound(AppError):
    """AC-51：文档不存在或不属于该项目。"""

    status_code = 404
    code = "DOCUMENT_NOT_FOUND"


class DocumentVersionNotFound(AppError):
    """AC-54：版本不存在或不属于该文档。"""

    status_code = 404
    code = "DOCUMENT_VERSION_NOT_FOUND"


class InvalidVersionStatus(AppError):
    """AC-54 / 55：重复确认、作废非 pending 版本。"""

    status_code = 409
    code = "INVALID_VERSION_STATUS"


class ModuleNotFound(AppError):
    """AC-62：模块不存在或不属于该项目。"""

    status_code = 404
    code = "MODULE_NOT_FOUND"


class ModuleNotEmpty(AppError):
    """AC-64：模块下还有功能，不能直接删。

    响应带 `available_actions`，前端据此弹出「迁移功能」「删除功能」两个入口。
    """

    status_code = 409
    code = "MODULE_NOT_EMPTY"


class DuplicateModuleName(AppError):
    """AC-62：同项目模块名重复。"""

    status_code = 409
    code = "DUPLICATE_MODULE_NAME"


class FunctionNotFound(AppError):
    """AC-62：功能不存在或不属于该项目。"""

    status_code = 404
    code = "FUNCTION_NOT_FOUND"


class DuplicateFunctionName(AppError):
    """AC-62：同模块功能名重复。"""

    status_code = 409
    code = "DUPLICATE_FUNCTION_NAME"


class FeaturePointNotFound(AppError):
    """AC-62：功能点不存在或不属于该项目。"""

    status_code = 404
    code = "FEATURE_POINT_NOT_FOUND"


class DuplicateFeaturePointName(AppError):
    """AC-62：同功能功能点名重复。"""

    status_code = 409
    code = "DUPLICATE_FEATURE_POINT_NAME"


class InvalidMigrateTarget(AppError):
    """AC-65：迁移目标不存在、跨项目或等于当前模块。"""

    status_code = 400
    code = "INVALID_MIGRATE_TARGET"


class TraceFieldsReadOnly(AppError):
    """AC-63：来源追溯字段只读，写接口不接受。"""

    status_code = 400
    code = "TRACE_FIELDS_READONLY"


class InvalidLabelType(AppError):
    """AC-66：标签类型不在 new/changed/affected/unchanged 之内。"""

    status_code = 400
    code = "INVALID_LABEL_TYPE"


class DuplicateLabel(AppError):
    """AC-66：同实体同快照同类型已有生效标签。"""

    status_code = 409
    code = "DUPLICATE_LABEL"


class LabelNotFound(AppError):
    """AC-67：标签不存在或不属于该项目。"""

    status_code = 404
    code = "LABEL_NOT_FOUND"


class LabelAlreadyCleared(AppError):
    """AC-67：标签已经被清除过，不能重复清除。"""

    status_code = 409
    code = "LABEL_ALREADY_CLEARED"


class ClearReasonRequired(AppError):
    """AC-67：清除标签必须给原因。"""

    status_code = 400
    code = "CLEAR_REASON_REQUIRED"


class InvalidClearReason(AppError):
    """AC-67：清除原因不在 6 类枚举之内。"""

    status_code = 400
    code = "INVALID_CLEAR_REASON"


class ClearNoteRequired(AppError):
    """AC-67：原因选「其他」时必须写备注。"""

    status_code = 400
    code = "CLEAR_NOTE_REQUIRED"


class ReviewNotFound(AppError):
    """AC-69：审核记录不存在。"""

    status_code = 404
    code = "REVIEW_NOT_FOUND"


class InvalidReviewStatus(AppError):
    """AC-69：重复审核 / 当前状态不允许该操作。"""

    status_code = 409
    code = "INVALID_REVIEW_STATUS"


class ReviewCommentRequired(AppError):
    """AC-69：驳回必须写意见。"""

    status_code = 400
    code = "REVIEW_COMMENT_REQUIRED"


class SelfApprovalForbidden(AppError):
    """AC-69：提交者不能审核自己的提交。"""

    status_code = 403
    code = "SELF_APPROVAL_FORBIDDEN"


class SnapshotNotFound(AppError):
    """AC-70：快照不存在或不属于该项目。"""

    status_code = 404
    code = "SNAPSHOT_NOT_FOUND"


class SnapshotReferenced(AppError):
    """AC-72：快照被引用，禁止删除。

    响应带 `refs`，前端据此提示「这份快照被 N 处引用，清理前请先解除引用」。
    `refs` 的来源不止标签——增量分析（以及后续的测试点、用例、报告）
    同样会引用快照，各来源由 `app/baselines/references.py` 分别解析。
    """

    status_code = 409
    code = "SNAPSHOT_REFERENCED"


class IncrementalAnalysisNotFound(AppError):
    """AC-81：分析记录不存在或不属于该项目。"""

    status_code = 404
    code = "INCREMENTAL_ANALYSIS_NOT_FOUND"


class BaselineRevisionRequired(AppError):
    """AC-78：发起分析必须指定一份审核通过的基线快照。"""

    status_code = 400
    code = "BASELINE_REVISION_REQUIRED"


class NoActiveDocumentVersion(AppError):
    """AC-78：文档版本不存在或不属于该项目。"""

    status_code = 400
    code = "NO_ACTIVE_DOCUMENT_VERSION"


class DocumentVersionNotAnalyzable(AppError):
    """AC-78：文档版本存在但不是生效版本，无法比对。"""

    status_code = 400
    code = "DOCUMENT_VERSION_NOT_ANALYZABLE"


class TemplateNotFound(AppError):
    """AC-78：提示词模板不存在。"""

    status_code = 404
    code = "TEMPLATE_NOT_FOUND"


class TemplateDisabled(AppError):
    """AC-78：提示词模板已停用。"""

    status_code = 409
    code = "TEMPLATE_DISABLED"


class InvalidSplitGranularity(AppError):
    """AC-78：本期只支持 `chapter` 切分粒度。"""

    status_code = 400
    code = "INVALID_SPLIT_GRANULARITY"


class LLMCallFailed(AppError):
    """AC-81：模型调用抛错，整次分析置为 failed。

    同步执行下立即返回 502，不让前端干等；第二期接后台队列后
    同一错误码仍可用于标记失败原因。
    """

    status_code = 502
    code = "LLM_CALL_FAILED"


class LLMOutputInvalid(AppError):
    """AC-81：模型返回不是合法 JSON，或缺少 `conclusions` 字段。"""

    status_code = 502
    code = "LLM_OUTPUT_INVALID"


class InvalidChapterLink(AppError):
    """AC-87：补链目标二选一不满足、章节不属该版本或引用自身。"""

    status_code = 400
    code = "INVALID_CHAPTER_LINK"


class DuplicateChapterLink(AppError):
    """AC-87：同一源章节同类型同目标的链接已存在。"""

    status_code = 409
    code = "DUPLICATE_CHAPTER_LINK"


def install_error_handlers(app: FastAPI) -> None:
    """把 AppError 统一渲染成 {"code","message",**extra}。"""

    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message, **exc.extra},
        )


__all__ = [
    "AccountDisabled",
    "AccountLocked",
    "AlreadyProjectMember",
    "AppError",
    "ApplicationNotFound",
    "ApplicationNotPending",
    "ApplyCooldown",
    "ApplyDisabled",
    "CaptchaInvalid",
    "CaptchaRequired",
    "BaselineRevisionRequired",
    "CannotChangeOwnRole",
    "CannotRemoveSelf",
    "ClearNoteRequired",
    "ClearReasonRequired",
    "ContactTaken",
    "DocumentParseFailed",
    "DocumentTooLarge",
    "DocumentVersionNotAnalyzable",
    "DuplicateApplication",
    "DuplicateChapterLink",
    "DuplicateFeaturePointName",
    "DuplicateFunctionName",
    "DuplicateLabel",
    "DuplicateModuleName",
    "EmptyDocument",
    "FeaturePointNotFound",
    "Forbidden",
    "FunctionNotFound",
    "IncrementalAnalysisNotFound",
    "InvalidApplicationStatus",
    "InvalidChapterLink",
    "InvalidClearReason",
    "InvalidCredentials",
    "InvalidDesiredRole",
    "InvalidGlobalRole",
    "InvalidLabelType",
    "InvalidMigrateTarget",
    "InvalidProjectDescription",
    "InvalidProjectName",
    "InvalidResetCode",
    "InvalidReviewStatus",
    "InvalidRoleAssignment",
    "InvalidSplitGranularity",
    "InvalidStatus",
    "InvalidVersionStatus",
    "LLMCallFailed",
    "LLMOutputInvalid",
    "LabelAlreadyCleared",
    "LabelNotFound",
    "LastProjectAdmin",
    "MemberNotFound",
    "ModuleNotEmpty",
    "ModuleNotFound",
    "NoActiveDocumentVersion",
    "NotApplicationOwner",
    "NotProjectAdmin",
    "NotProjectMember",
    "PasswordChangeRequired",
    "ProjectArchived",
    "ProjectNameRequired",
    "ProjectNotFound",
    "RateLimited",
    "ReasonRequired",
    "ReviewCommentRequired",
    "ReviewNotFound",
    "SelfApprovalForbidden",
    "SnapshotNotFound",
    "SnapshotReferenced",
    "TemplateDisabled",
    "TemplateNotFound",
    "TokenExpired",
    "TokenRevoked",
    "TraceFieldsReadOnly",
    "Unauthenticated",
    "UnsupportedDocType",
    "UserNotFound",
    "UsernameTaken",
    "WeakPassword",
    "install_error_handlers",
]
