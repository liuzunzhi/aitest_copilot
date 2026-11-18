import { client } from './client'

export interface Project {
  id: number
  name: string
  description: string | null
  status: string
  role?: string
}

export interface Member {
  user_id: number
  username: string
  role: string
  joined_at: string
}

export interface Overview {
  member_count: number
  document_count: number
  baseline_count: number
  latest_execution: unknown | null
}

export interface Application {
  id: number
  project?: { id: number; name: string }
  applicant?: { id: number; username: string }
  reason: string
  desired_role: string
  status: string
  created_at: string
  reviewer?: { id: number; username: string } | null
  reviewed_at: string | null
  reject_reason: string | null
  closed_reason: string | null
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface Me {
  id: number
  username: string
  global_role: string
  must_change_password: boolean
}

export interface AdminUser {
  id: number
  username: string
  email: string | null
  phone: string | null
  status: string
  global_role: string
  created_at: string
}

export async function login(username: string, password: string): Promise<string> {
  const { data } = await client.post<{ access_token: string }>('/auth/login', {
    username,
    password,
  })
  return data.access_token
}

export async function logout(): Promise<void> {
  await client.post('/auth/logout')
}

export async function fetchMe(): Promise<Me> {
  const { data } = await client.get<Me>('/auth/me')
  return data
}

export async function listMyProjects(): Promise<Project[]> {
  const { data } = await client.get<Project[]>('/projects')
  return data
}

export async function listAvailableProjects(): Promise<Project[]> {
  const { data } = await client.get<Project[]>('/projects/available')
  return data
}

export async function createProject(name: string, description: string | null): Promise<Project> {
  const { data } = await client.post<Project>('/projects', { name, description })
  return data
}

export async function updateProject(
  projectId: number,
  changes: { name?: string; description?: string | null },
): Promise<Project> {
  const { data } = await client.patch<Project>(`/projects/${projectId}`, changes)
  return data
}

export async function archiveProject(projectId: number): Promise<void> {
  await client.post(`/projects/${projectId}/archive`)
}

export async function fetchOverview(projectId: number): Promise<Overview> {
  const { data } = await client.get<Overview>(`/projects/${projectId}/overview`)
  return data
}

export async function listMembers(projectId: number): Promise<Member[]> {
  const { data } = await client.get<Member[]>(`/projects/${projectId}/members`)
  return data
}

export async function addMember(projectId: number, userId: number, role: string): Promise<Member> {
  const { data } = await client.post<Member>(`/projects/${projectId}/members`, {
    user_id: userId,
    role,
  })
  return data
}

export async function updateMemberRole(
  projectId: number,
  userId: number,
  role: string,
): Promise<Member> {
  const { data } = await client.patch<Member>(`/projects/${projectId}/members/${userId}`, { role })
  return data
}

export async function removeMember(projectId: number, userId: number): Promise<void> {
  await client.delete(`/projects/${projectId}/members/${userId}`)
}

export async function listProjectApplications(
  projectId: number,
  params: { status?: string; page?: number; page_size?: number },
): Promise<Page<Application>> {
  const { data } = await client.get<Page<Application>>(`/projects/${projectId}/applications`, {
    params,
  })
  return data
}

export async function listMyApplications(
  params: { status?: string; page?: number; page_size?: number },
): Promise<Page<Application>> {
  const { data } = await client.get<Page<Application>>('/applications/mine', { params })
  return data
}

export async function listAllApplications(params: {
  project_id?: number
  status?: string
  applicant_id?: number
  page?: number
  page_size?: number
}): Promise<Page<Application>> {
  const { data } = await client.get<Page<Application>>('/admin/applications', { params })
  return data
}

export async function approveApplication(
  projectId: number,
  applicationId: number,
  role?: string,
): Promise<void> {
  await client.post(`/projects/${projectId}/applications/${applicationId}/approve`, { role })
}

export async function rejectApplication(
  projectId: number,
  applicationId: number,
  reason: string,
): Promise<void> {
  await client.post(`/projects/${projectId}/applications/${applicationId}/reject`, { reason })
}

export async function submitApplication(
  projectId: number,
  reason: string,
  desiredRole: string,
): Promise<void> {
  await client.post(`/projects/${projectId}/applications`, {
    reason,
    desired_role: desiredRole,
  })
}

export interface DocVersion {
  id: number
  version_no: number
  status: string
  chapter_count: number
  file_name: string
  file_size: number
  created_at: string
}

export interface DocumentItem {
  id: number
  name: string
  created_at: string
  version_count: number
  pending_count: number
  active_version: DocVersion | null
}

export interface Chapter {
  id: number
  seq: number
  level: number
  title: string
  content: string
  char_count: number
  children: Chapter[]
}

export interface Baseline {
  id: number
  version_no: number
  chapter_count: number
  created_at: string
  document_id: number
  document_name: string
  document_version_no: number
}

export async function listDocuments(projectId: number): Promise<DocumentItem[]> {
  const { data } = await client.get<DocumentItem[]>(`/projects/${projectId}/documents`)
  return data
}

export async function uploadDocument(
  projectId: number,
  file: File,
  documentId?: number,
): Promise<{ document: { id: number; name: string; version_count: number }; version: DocVersion }> {
  const body = new FormData()
  body.append('file', file)
  // 带 documentId 表示给已有文档追加版本，否则新建文档
  if (documentId !== undefined) body.append('document_id', String(documentId))
  const { data } = await client.post(`/projects/${projectId}/documents`, body)
  return data
}

export async function listVersions(projectId: number, documentId: number): Promise<DocVersion[]> {
  const { data } = await client.get<DocVersion[]>(
    `/projects/${projectId}/documents/${documentId}/versions`,
  )
  return data
}

export async function listChapters(
  projectId: number,
  documentId: number,
  versionId: number,
): Promise<Chapter[]> {
  const { data } = await client.get<Chapter[]>(
    `/projects/${projectId}/documents/${documentId}/versions/${versionId}/chapters`,
  )
  return data
}

export async function activateVersion(
  projectId: number,
  documentId: number,
  versionId: number,
): Promise<{ version: DocVersion; baseline: Baseline }> {
  const { data } = await client.post(
    `/projects/${projectId}/documents/${documentId}/versions/${versionId}/activate`,
  )
  return data
}

export async function voidVersion(
  projectId: number,
  documentId: number,
  versionId: number,
): Promise<DocVersion> {
  const { data } = await client.post<DocVersion>(
    `/projects/${projectId}/documents/${documentId}/versions/${versionId}/void`,
  )
  return data
}

export async function listBaselines(projectId: number): Promise<Baseline[]> {
  const { data } = await client.get<Baseline[]>(`/projects/${projectId}/baselines`)
  return data
}

/** 下载要带 Bearer 头，只能走 XHR 取 blob，再用临时链接落盘。 */
export async function downloadVersion(
  projectId: number,
  documentId: number,
  versionId: number,
): Promise<{ blob: Blob; fileName: string }> {
  const response = await client.get(
    `/projects/${projectId}/documents/${documentId}/versions/${versionId}/download`,
    { responseType: 'blob' },
  )
  const disposition = String(response.headers['content-disposition'] ?? '')
  const encoded = disposition.match(/filename\*=utf-8''([^;]+)/i)?.[1]
  const plain = disposition.match(/filename="?([^";]+)"?/i)?.[1]
  return {
    blob: response.data as Blob,
    fileName: encoded ? decodeURIComponent(encoded) : (plain ?? '原文档'),
  }
}

export async function listUsers(): Promise<AdminUser[]> {
  const { data } = await client.get<AdminUser[]>('/admin/users')
  return data
}

export async function updateUserRole(
  userId: number,
  globalRole: string,
): Promise<{ id: number; username: string; global_role: string }> {
  const { data } = await client.patch<{ id: number; username: string; global_role: string }>(
    `/admin/users/${userId}/role`,
    { global_role: globalRole },
  )
  return data
}

/* ---------------------------------------------------------- 功能基线（04） */

export type LabelType = 'new' | 'changed' | 'affected' | 'unchanged'

/** 模块/功能的状态筛选：在用 / 归档 / 全部（默认在用）。 */
export type BaselineStatusFilter = 'active' | 'archived' | 'all'

export type ClearReason =
  | 'requirement_done'
  | 'requirement_cancelled'
  | 'misjudged'
  | 'priority_changed'
  | 'duplicate_label'
  | 'other'

export interface BaselineModule {
  id: number
  name: string
  description: string | null
  sort_order: number
  source_type: string
  status: string
  function_count: number
  created_at: string
}

export interface BaselineFunction {
  id: number
  module_id: number
  module_name: string
  name: string
  description: string | null
  version_no: number
  source_type: string
  status: string
  moved_from_module_id: number | null
  source_document_id: number | null
  source_version_id: number | null
  source_chapter_id: number | null
  source_chapter_title: string | null
  source_method: string | null
  source_analysis_id: number | null
  label_types: LabelType[]
  feature_point_count: number
  feature_point_label_count: number
  created_at: string
}

export interface BaselineFeaturePoint {
  id: number
  function_id: number
  name: string
  description: string | null
  source_type: string
  status: string
  label_types: LabelType[]
  created_at: string
}

export interface BaselineLabel {
  id: number
  revision_id: number
  target_type: 'function' | 'feature_point'
  target_id: number
  label_type: LabelType
  status: 'active' | 'cleared'
  confirmed_by: number
  confirmed_at: string
  cleared_by: number | null
  cleared_at: string | null
  clear_reason: ClearReason | null
  clear_note: string | null
}

export interface BaselineRevision {
  id: number
  version_no: number | null
  status: 'draft' | 'submitted' | 'approved' | 'rejected'
  module_count: number
  function_count: number
  feature_point_count: number
  label_count: number
  submitted_by: number | null
  submitted_at: string | null
  reviewed_by: number | null
  reviewed_at: string | null
  review_comment: string | null
  created_at: string
}

export interface BaselineRevisionDetail extends BaselineRevision {
  structure: Array<{
    id: number
    name: string
    functions: Array<{
      id: number
      name: string
      feature_points: Array<{ id: number; name: string }>
    }>
  }> | null
}

export interface RetentionCandidate {
  id: number
  version_no: number
  referenced_count: number
  refs: Array<{
    target_id: number
    target_name?: string
    source_type: string
    label_type?: string
    source_analysis_id?: number
  }>
  created_at: string
}

export interface Retention {
  max_count: number | null
  enabled: boolean
  snapshot_count: number
  keep_count: number | null
  candidates: RetentionCandidate[]
  warnings: string[]
}

export interface DeleteResult {
  deleted: boolean
  warning: string | null
  cleared_label_count: number
}

const BASELINES = (projectId: number) => `/projects/${projectId}/baselines`

export async function listBaselineModules(
  projectId: number,
  params?: { status?: BaselineStatusFilter; page?: number; page_size?: number },
): Promise<Page<BaselineModule>> {
  const { data } = await client.get<Page<BaselineModule>>(
    `${BASELINES(projectId)}/modules`,
    { params },
  )
  return data
}

export async function createBaselineModule(
  projectId: number,
  body: { name: string; description?: string | null; sort_order?: number },
): Promise<BaselineModule> {
  const { data } = await client.post<BaselineModule>(
    `${BASELINES(projectId)}/modules`,
    body,
  )
  return data
}

export async function updateBaselineModule(
  projectId: number,
  moduleId: number,
  body: {
    name?: string
    description?: string | null
    sort_order?: number
    status?: 'active' | 'archived'
  },
): Promise<BaselineModule> {
  const { data } = await client.patch<BaselineModule>(
    `${BASELINES(projectId)}/modules/${moduleId}`,
    body,
  )
  return data
}

export async function deleteBaselineModule(
  projectId: number,
  moduleId: number,
): Promise<DeleteResult> {
  const { data } = await client.delete<DeleteResult>(
    `${BASELINES(projectId)}/modules/${moduleId}`,
  )
  return data
}

export async function migrateBaselineFunctions(
  projectId: number,
  moduleId: number,
  targetModuleId: number,
  functionIds: number[],
): Promise<BaselineFunction[]> {
  const { data } = await client.post<BaselineFunction[]>(
    `${BASELINES(projectId)}/modules/${moduleId}/migrate`,
    { target_module_id: targetModuleId, function_ids: functionIds },
  )
  return data
}

export async function listBaselineFunctions(
  projectId: number,
  params?: {
    module_id?: number
    source_type?: string
    label_type?: string
    keyword?: string
    revision_id?: number
    status?: BaselineStatusFilter
    page?: number
    page_size?: number
  },
): Promise<Page<BaselineFunction>> {
  const { data } = await client.get<Page<BaselineFunction>>(
    `${BASELINES(projectId)}/functions`,
    { params },
  )
  return data
}

export async function createBaselineFunction(
  projectId: number,
  body: { module_id: number; name: string; description?: string | null },
): Promise<BaselineFunction> {
  const { data } = await client.post<BaselineFunction>(
    `${BASELINES(projectId)}/functions`,
    body,
  )
  return data
}

export async function updateBaselineFunction(
  projectId: number,
  functionId: number,
  body: { name?: string; description?: string | null; status?: string },
): Promise<BaselineFunction> {
  const { data } = await client.patch<BaselineFunction>(
    `${BASELINES(projectId)}/functions/${functionId}`,
    body,
  )
  return data
}

export async function deleteBaselineFunction(
  projectId: number,
  functionId: number,
): Promise<DeleteResult> {
  const { data } = await client.delete<DeleteResult>(
    `${BASELINES(projectId)}/functions/${functionId}`,
  )
  return data
}

export async function listBaselineFeaturePoints(
  projectId: number,
  functionId: number,
): Promise<BaselineFeaturePoint[]> {
  const { data } = await client.get<BaselineFeaturePoint[]>(
    `${BASELINES(projectId)}/functions/${functionId}/feature-points`,
  )
  return data
}

export async function createBaselineFeaturePoint(
  projectId: number,
  functionId: number,
  body: { name: string; description?: string | null },
): Promise<BaselineFeaturePoint> {
  const { data } = await client.post<BaselineFeaturePoint>(
    `${BASELINES(projectId)}/functions/${functionId}/feature-points`,
    body,
  )
  return data
}

export async function updateBaselineFeaturePoint(
  projectId: number,
  pointId: number,
  body: { name?: string; description?: string | null; status?: string },
): Promise<BaselineFeaturePoint> {
  const { data } = await client.patch<BaselineFeaturePoint>(
    `${BASELINES(projectId)}/feature-points/${pointId}`,
    body,
  )
  return data
}

export async function deleteBaselineFeaturePoint(
  projectId: number,
  pointId: number,
): Promise<DeleteResult> {
  const { data } = await client.delete<DeleteResult>(
    `${BASELINES(projectId)}/feature-points/${pointId}`,
  )
  return data
}

export async function listBaselineLabels(
  projectId: number,
  params?: {
    target_type?: string
    target_id?: number
    revision_id?: number
    status?: 'active' | 'cleared' | 'all'
    page?: number
    page_size?: number
  },
): Promise<Page<BaselineLabel>> {
  const { data } = await client.get<Page<BaselineLabel>>(`${BASELINES(projectId)}/labels`, {
    params,
  })
  return data
}

export async function createBaselineLabel(
  projectId: number,
  body: {
    revision_id?: number | null
    target_type: 'function' | 'feature_point'
    target_id: number
    label_type: LabelType
  },
): Promise<BaselineLabel> {
  const { data } = await client.post<BaselineLabel>(`${BASELINES(projectId)}/labels`, body)
  return data
}

export async function clearBaselineLabel(
  projectId: number,
  labelId: number,
  body: { clear_reason: ClearReason; clear_note?: string | null },
): Promise<BaselineLabel> {
  const { data } = await client.post<BaselineLabel>(
    `${BASELINES(projectId)}/labels/${labelId}/clear`,
    body,
  )
  return data
}

export async function listBaselineRevisions(
  projectId: number,
  params?: { status?: string; page?: number; page_size?: number },
): Promise<Page<BaselineRevision>> {
  const { data } = await client.get<Page<BaselineRevision>>(
    `${BASELINES(projectId)}/revisions`,
    { params },
  )
  return data
}

export async function fetchBaselineRevision(
  projectId: number,
  revisionId: number,
): Promise<BaselineRevisionDetail> {
  const { data } = await client.get<BaselineRevisionDetail>(
    `${BASELINES(projectId)}/revisions/${revisionId}`,
  )
  return data
}

export async function deleteBaselineRevision(
  projectId: number,
  revisionId: number,
): Promise<DeleteResult> {
  const { data } = await client.delete<DeleteResult>(
    `${BASELINES(projectId)}/revisions/${revisionId}`,
  )
  return data
}

export async function submitBaselineReview(
  projectId: number,
  comment?: string | null,
): Promise<BaselineRevision> {
  const { data } = await client.post<BaselineRevision>(
    `${BASELINES(projectId)}/reviews/submit`,
    { comment },
  )
  return data
}

export async function approveBaselineReview(
  projectId: number,
  revisionId: number,
  comment?: string | null,
): Promise<BaselineRevision> {
  const { data } = await client.post<BaselineRevision>(
    `${BASELINES(projectId)}/reviews/${revisionId}/approve`,
    { comment },
  )
  return data
}

export async function rejectBaselineReview(
  projectId: number,
  revisionId: number,
  comment: string,
): Promise<BaselineRevision> {
  const { data } = await client.post<BaselineRevision>(
    `${BASELINES(projectId)}/reviews/${revisionId}/reject`,
    { comment },
  )
  return data
}

export async function fetchRetention(projectId: number): Promise<Retention> {
  const { data } = await client.get<Retention>(`${BASELINES(projectId)}/retention`)
  return data
}

export async function updateRetention(
  projectId: number,
  maxCount: number | null,
): Promise<Retention> {
  const { data } = await client.patch<Retention>(`${BASELINES(projectId)}/retention`, {
    max_count: maxCount,
  })
  return data
}

/* ------------------------------------------------ 从文档推导基线（04 补期） */

export type DeriveStatus = 'running' | 'succeeded' | 'failed'
export type DeriveCandidateStatus = 'pending' | 'adopted' | 'skipped'
export type DeriveCandidateType = 'module' | 'function' | 'feature_point'

export interface BaselineDeriveStats {
  chapter_count: number
  processed_count: number
  candidate_count: number
  module_count: number
  function_count: number
  feature_point_count: number
  skipped_chapters: Array<{ chapter_id: number; reason: string }>
}

export interface BaselineDeriveCandidate {
  id: number
  parent_id: number | null
  entity_type: DeriveCandidateType
  name: string
  description: string | null
  source_chapter_title: string | null
  confidence: number | null
  rationale: string | null
  status: DeriveCandidateStatus
  children?: BaselineDeriveCandidate[] | null
}

export interface BaselineDerive {
  id: number
  provider: string
  status: DeriveStatus
  document_id: number
  document_version_id: number
  template_id: number
  stats: BaselineDeriveStats | null
  error_code: string | null
  error_message: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
}

export interface BaselineDeriveDetail extends BaselineDerive {
  document_name: string | null
  candidates: BaselineDeriveCandidate[]
}

export interface DeriveAdoptItem {
  candidate_id: number
  action: 'reuse' | 'create' | 'skip'
  name?: string | null
  existing_entity_id?: number | null
}

export interface DeriveAdoptCounts {
  modules: number
  functions: number
  feature_points: number
}

export interface DeriveAdoptResult {
  derive_id: number
  adopted_count: number
  created: DeriveAdoptCounts
  reused: DeriveAdoptCounts
  skipped: DeriveAdoptCounts
  items: Array<{
    candidate_id: number
    entity_type: string
    entity_id: number | null
    name: string
    action: string
  }>
}

const DERIVES = (projectId: number) => `${BASELINES(projectId)}/derive`

export async function runBaselineDerive(
  projectId: number,
  payload: { document_id: number; document_version_id: number; template_id: number },
): Promise<BaselineDeriveDetail> {
  const { data } = await client.post<BaselineDeriveDetail>(DERIVES(projectId), payload)
  return data
}

export async function listBaselineDerives(
  projectId: number,
  params?: { page?: number; page_size?: number },
): Promise<Page<BaselineDerive>> {
  const { data } = await client.get<Page<BaselineDerive>>(DERIVES(projectId), { params })
  return data
}

export async function getBaselineDerive(
  projectId: number,
  deriveId: number,
): Promise<BaselineDeriveDetail> {
  const { data } = await client.get<BaselineDeriveDetail>(
    `${DERIVES(projectId)}/${deriveId}`,
  )
  return data
}

export async function adoptBaselineDerive(
  projectId: number,
  deriveId: number,
  candidates: DeriveAdoptItem[],
): Promise<DeriveAdoptResult> {
  const { data } = await client.post<DeriveAdoptResult>(
    `${DERIVES(projectId)}/${deriveId}/adopt`,
    { candidates },
  )
  return data
}

export async function deleteBaselineDeriveCandidate(
  projectId: number,
  deriveId: number,
  candidateId: number,
): Promise<DeleteResult> {
  const { data } = await client.delete<DeleteResult>(
    `${DERIVES(projectId)}/${deriveId}/candidates/${candidateId}`,
  )
  return data
}

/* ---------------------------------------------------------- 增量分析（05） */

export type IncrementalAnalysisStatus = 'pending' | 'running' | 'succeeded' | 'failed'

/** 第一遍结论只允许 changed / affected / unchanged（`new` 由后端丢弃）。 */
export type IncrementalLabelType = 'changed' | 'affected' | 'unchanged'

export interface DiscardedConclusion {
  chapter_id: number
  chapter_title: string
  target_type: 'function' | 'feature_point'
  target_id: number
  label_type: string
  code: string
}

export interface AnalysisStats {
  chapter_count: number
  conclusion_count: number
  discarded_count: number
  dropped_new_count: number
  discarded: DiscardedConclusion[]
  /** 失败时记录卡住的那一章（spec §4.2.1） */
  failed_chapter_id?: number
  failed_chapter_title?: string | null
}

export interface IncrementalAnalysis {
  id: number
  project_id: number
  template_id: number
  template_name: string | null
  template_version: number
  provider: string
  baseline_revision_id: number
  /** 形如 v1.0，由后端拼好 */
  baseline_revision_version: string | null
  document_id: number
  document_name: string | null
  document_version_id: number
  document_version_no: number | null
  split_granularity: string
  status: IncrementalAnalysisStatus
  error_code: string | null
  error_message: string | null
  stats: AnalysisStats | null
  started_at: string | null
  finished_at: string | null
  // ---- 第二遍（第二期）。null 表示未执行，不是失败 ----
  second_pass_template_id: number | null
  second_pass_status: SecondPassStatus | null
  second_pass_stats: SecondPassStats | null
  second_pass_error_code: string | null
  second_pass_error_message: string | null
  second_pass_started_at: string | null
  second_pass_finished_at: string | null
  created_by: number
  created_at: string
}

export interface IncrementalConclusion {
  id: number
  analysis_id: number
  chapter_id: number
  chapter_title: string
  target_type: 'function' | 'feature_point'
  target_id: number
  label_type: IncrementalLabelType
  confidence: number | null
  rationale: string | null
  created_at: string
}

const INCREMENTAL = (projectId: number) => `/projects/${projectId}/incremental`

export async function listIncrementalAnalyses(
  projectId: number,
  params?: { status?: string; page?: number; page_size?: number },
): Promise<Page<IncrementalAnalysis>> {
  const { data } = await client.get<Page<IncrementalAnalysis>>(
    `${INCREMENTAL(projectId)}/analyses`,
    { params },
  )
  return data
}

/**
 * 发起分析。本期后端同步跑完第一遍才返回，失败时抛 `LLM_CALL_FAILED` 等错误码；
 * 记录本身已落库为 `failed`，调用方刷新列表即可看到。
 */
export async function createIncrementalAnalysis(
  projectId: number,
  body: {
    template_id: number
    baseline_revision_id: number
    document_version_id: number
    split_granularity?: string
  },
): Promise<IncrementalAnalysis> {
  const { data } = await client.post<IncrementalAnalysis>(
    `${INCREMENTAL(projectId)}/analyses`,
    body,
  )
  return data
}

export async function fetchIncrementalAnalysis(
  projectId: number,
  analysisId: number,
): Promise<IncrementalAnalysis> {
  const { data } = await client.get<IncrementalAnalysis>(
    `${INCREMENTAL(projectId)}/analyses/${analysisId}`,
  )
  return data
}

export async function listIncrementalConclusions(
  projectId: number,
  analysisId: number,
  params?: {
    chapter_id?: number
    target_type?: 'function' | 'feature_point'
    page?: number
    page_size?: number
  },
): Promise<Page<IncrementalConclusion>> {
  const { data } = await client.get<Page<IncrementalConclusion>>(
    `${INCREMENTAL(projectId)}/analyses/${analysisId}/conclusions`,
    { params },
  )
  return data
}

/* ---------------------------------------------- 增量分析第二期（第二遍） */

/** 第二遍状态：NULL（未执行）/ running / succeeded / failed。 */
export type SecondPassStatus = 'running' | 'succeeded' | 'failed'

/** 裁决只有三值，`new` 不落裁决表，只进冲突队列。 */
export type DecisionType = 'changed' | 'affected' | 'unchanged'

export type ConflictType = 'conflict' | 'possible_impact' | 'new'

export type ConflictStatus = 'pending' | 'confirmed' | 'rejected'

export interface SecondPassStats {
  template_id: number
  template_version: number
  /** 恒为 mock（本期零真实网络请求）。 */
  provider: string
  chapter_link_count: number
  point_count: number
  decision_count: number
  new_count: number
  conflict_count: number
  propagated_count: number
  failed_target_type?: string | null
  failed_target_id?: number | null
}

export interface IncrementalDecision {
  id: number
  analysis_id: number
  target_type: 'function' | 'feature_point'
  target_id: number
  target_name: string
  decision: DecisionType
  confidence: number | null
  rationale: string | null
  evidence: {
    chapter_ids?: number[]
    conclusion_ids?: number[]
    propagated_from?: number[]
  } | null
  created_at: string
}

export interface ConflictCandidate {
  label_type: string
  confidence?: number | null
  rationale?: string | null
  /** `point_pass` 表示来自 2b-2；`chapter:{id}` 表示来自图传播。 */
  source: string
}

export interface IncrementalConflict {
  id: number
  analysis_id: number
  target_type: 'function' | 'feature_point'
  /** `new` 没有基线 id，为 NULL。 */
  target_id: number | null
  target_name: string
  conflict_type: ConflictType
  candidates: ConflictCandidate[]
  status: ConflictStatus
  resolved_label_type: DecisionType | null
  resolved_by: number | null
  resolved_at: string | null
  created_at: string
}

/** 章节引用图的一条边。 */
export interface ChapterLink {
  id: number
  version_id: number
  from_chapter_id: number
  from_chapter_title: string | null
  to_chapter_id: number | null
  to_chapter_title: string | null
  link_type: 'references' | 'depends_on' | 'mentions_entity'
  entity: string | null
  confidence: number | null
  source: 'rule' | 'manual'
  created_by: number
  created_at: string
}

/**
 * 触发第二遍。后端同步跑完才返回，失败时抛
 * `SECOND_PASS_NOT_READY` / `SECOND_PASS_TEMPLATE_MISSING` /
 * `SECOND_PASS_CONFLICTS_PENDING` / `LLM_OUTPUT_INVALID` 等错误码。
 */
export async function runIncrementalSecondPass(
  projectId: number,
  analysisId: number,
): Promise<IncrementalAnalysis> {
  const { data } = await client.post<IncrementalAnalysis>(
    `${INCREMENTAL(projectId)}/analyses/${analysisId}/second-pass`,
  )
  return data
}

export async function listIncrementalDecisions(
  projectId: number,
  analysisId: number,
  params?: {
    target_type?: 'function' | 'feature_point'
    decision?: DecisionType
    page?: number
    page_size?: number
  },
): Promise<Page<IncrementalDecision>> {
  const { data } = await client.get<Page<IncrementalDecision>>(
    `${INCREMENTAL(projectId)}/analyses/${analysisId}/decisions`,
    { params },
  )
  return data
}

export async function listIncrementalConflicts(
  projectId: number,
  analysisId: number,
  params?: {
    status?: ConflictStatus
    conflict_type?: ConflictType
    page?: number
    page_size?: number
  },
): Promise<Page<IncrementalConflict>> {
  const { data } = await client.get<Page<IncrementalConflict>>(
    `${INCREMENTAL(projectId)}/analyses/${analysisId}/conflicts`,
    { params },
  )
  return data
}

/** 人工裁决。只改冲突行，不写基线标签（产出段是下一期的事）。 */
export async function resolveIncrementalConflict(
  projectId: number,
  analysisId: number,
  conflictId: number,
  body: { decision: 'confirmed' | 'rejected'; label_type?: DecisionType },
): Promise<IncrementalConflict> {
  const { data } = await client.post<IncrementalConflict>(
    `${INCREMENTAL(projectId)}/analyses/${analysisId}/conflicts/${conflictId}/resolve`,
    body,
  )
  return data
}

const CHAPTER_LINKS = (projectId: number, documentId: number, versionId: number) =>
  `/projects/${projectId}/documents/${documentId}/versions/${versionId}/links`

export async function listChapterLinks(
  projectId: number,
  documentId: number,
  versionId: number,
  params?: { link_type?: ChapterLink['link_type']; source?: ChapterLink['source'] },
): Promise<ChapterLink[]> {
  const { data } = await client.get<ChapterLink[]>(
    CHAPTER_LINKS(projectId, documentId, versionId),
    { params },
  )
  return data
}

/** 手动补一条引用边。目标二选一：`to_chapter_id` 或 `entity`。 */
export async function createChapterLink(
  projectId: number,
  documentId: number,
  versionId: number,
  body: {
    from_chapter_id: number
    link_type: ChapterLink['link_type']
    to_chapter_id?: number | null
    entity?: string | null
  },
): Promise<ChapterLink> {
  const { data } = await client.post<ChapterLink>(
    CHAPTER_LINKS(projectId, documentId, versionId),
    body,
  )
  return data
}

/** 按规则重抽引用图（幂等，人工边不受影响）。 */
export async function extractChapterLinks(
  projectId: number,
  documentId: number,
  versionId: number,
): Promise<ChapterLink[]> {
  const { data } = await client.post<ChapterLink[]>(
    `${CHAPTER_LINKS(projectId, documentId, versionId)}/extract`,
  )
  return data
}

/* ---------------------------------------------- 增量分析第三期（产出段） */

/** 产出一行映射：`id` 是映射行 id，`baseline_label_id` 指向基线标签。 */
export interface AppliedLabel {
  id: number
  baseline_label_id: number
  revision_id: number
  target_type: 'function' | 'feature_point'
  target_id: number
  target_name: string | null
  /** 产出段只写 changed / affected，不写 unchanged。 */
  label_type: 'changed' | 'affected'
  status: 'active' | 'cleared'
  cleared_by: number | null
  cleared_at: string | null
  clear_reason: string | null
}

/** 产出统计；`apply_stats` 为空表示还没跑过产出段。 */
export interface ApplyStats {
  revision_id: number
  revision_status: string
  label_count: number
  changed_count: number
  affected_count: number
  skipped_missing_count: number
  skipped_new_count: number
  unchanged_count: number
  conflict_label_count: number
}

/** `apply` 与 `applied-labels` 共用的响应形状。 */
export interface ApplyResult {
  analysis_id: number
  /** NULL = 从未应用；running / succeeded / failed。 */
  apply_status: 'running' | 'succeeded' | 'failed' | null
  apply_revision_id: number | null
  apply_stats: ApplyStats | null
  labels: AppliedLabel[]
  /** 本次产出的标签当前全部被清除时置真（记录本身不删除）。 */
  revoked: boolean
}

/**
 * 应用产出：把第二遍裁决落成基线标签 + 待审核快照，同步跑完返回。
 * 失败时抛 `APPLY_NOT_READY` / `APPLY_CONFLICTS_PENDING` /
 * `APPLY_NO_LABELABLE_TARGET` 等错误码。
 */
export async function runIncrementalApply(
  projectId: number,
  analysisId: number,
): Promise<ApplyResult> {
  const { data } = await client.post<ApplyResult>(
    `${INCREMENTAL(projectId)}/analyses/${analysisId}/apply`,
  )
  return data
}

export async function listAppliedLabels(
  projectId: number,
  analysisId: number,
): Promise<ApplyResult> {
  const { data } = await client.get<ApplyResult>(
    `${INCREMENTAL(projectId)}/analyses/${analysisId}/applied-labels`,
  )
  return data
}

/* -------------------------------------- 系统设置：大模型配置（06） */

export type LlmProviderStatus = 'active' | 'disabled'

export interface LlmProvider {
  id: number
  name: string
  provider_type: string
  base_url: string
  model: string
  /** 只有掩码（形如 `sk-****1234`），后端不返回明文也不返回密文。 */
  api_key_masked: string
  timeout_seconds: number
  status: LlmProviderStatus
  is_default: boolean
  last_test_status: 'succeeded' | 'failed' | null
  last_test_at: string | null
  last_test_error: string | null
  created_at: string
  updated_at: string
}

export interface LlmProviderPayload {
  name: string
  base_url: string
  /** 新建必填；编辑时留空表示「不修改现有 Key」。 */
  api_key?: string
  model: string
  timeout_seconds?: number
  status?: LlmProviderStatus
  is_default?: boolean
}

export interface LlmProviderTestResult {
  ok: boolean
  latency_ms: number
  model: string | null
  message: string
}

export async function listLlmProviders(): Promise<LlmProvider[]> {
  const { data } = await client.get<LlmProvider[]>('/admin/llm-providers')
  return data
}

export async function createLlmProvider(
  payload: LlmProviderPayload,
): Promise<LlmProvider> {
  const { data } = await client.post<LlmProvider>('/admin/llm-providers', payload)
  return data
}

export async function updateLlmProvider(
  providerId: number,
  payload: Partial<LlmProviderPayload>,
): Promise<LlmProvider> {
  const { data } = await client.put<LlmProvider>(
    `/admin/llm-providers/${providerId}`,
    payload,
  )
  return data
}

/** 连通性测试：失败也返回 200 + `ok=false`，不是异常。 */
export async function testLlmProvider(
  providerId: number,
): Promise<LlmProviderTestResult> {
  const { data } = await client.post<LlmProviderTestResult>(
    `/admin/llm-providers/${providerId}/test`,
  )
  return data
}

/* -------------------------------------- 系统设置：提示词模板（06） */

/** 模板列表项：不含 Prompt 正文。 */
export interface PromptTemplateBrief {
  id: number
  name: string
  task_type: string
  description: string | null
  version_no: number
  status: 'active' | 'disabled'
  updated_at: string
}

/** 模板详情：列表项 + 完整正文。 */
export interface PromptTemplateDetail extends PromptTemplateBrief {
  system_prompt: string
  user_prompt: string
  created_at: string
}

export interface PromptTemplateUpdatePayload {
  name?: string
  description?: string
  system_prompt?: string
  user_prompt?: string
  status?: 'active' | 'disabled'
}

/** 只读模板项：普通成员可见的元信息，没有正文。 */
export interface AvailablePromptTemplate {
  id: number
  name: string
  task_type: string
  version_no: number
  description: string | null
}

export async function listPromptTemplates(params?: {
  task_type?: string
  status?: string
  page?: number
  page_size?: number
}): Promise<Page<PromptTemplateBrief>> {
  const { data } = await client.get<Page<PromptTemplateBrief>>(
    '/admin/prompt-templates',
    { params },
  )
  return data
}

export async function fetchPromptTemplate(
  templateId: number,
): Promise<PromptTemplateDetail> {
  const { data } = await client.get<PromptTemplateDetail>(
    `/admin/prompt-templates/${templateId}`,
  )
  return data
}

/** 编辑模板。**只有正文变化时后端才会把版本号 +1。** */
export async function updatePromptTemplate(
  templateId: number,
  payload: PromptTemplateUpdatePayload,
): Promise<PromptTemplateDetail> {
  const { data } = await client.put<PromptTemplateDetail>(
    `/admin/prompt-templates/${templateId}`,
    payload,
  )
  return data
}

/** 可用模板列表（登录即可）：只返回 active，且不含正文。 */
export async function listAvailablePromptTemplates(
  taskType?: string,
): Promise<AvailablePromptTemplate[]> {
  const { data } = await client.get<{ items: AvailablePromptTemplate[] }>(
    '/prompt-templates',
    { params: taskType ? { task_type: taskType } : undefined },
  )
  return data.items
}
