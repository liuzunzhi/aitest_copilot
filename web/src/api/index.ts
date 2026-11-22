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

/** 工作台待办计数（PRD 2.3.1）。三项构成测试主链路的待评审队列。 */
export interface Todos {
  pending_baseline_reviews: number
  pending_test_point_reviews: number
  pending_test_case_reviews: number
  total: number
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

export async function fetchTodos(projectId: number): Promise<Todos> {
  const { data } = await client.get<Todos>(`/projects/${projectId}/todos`)
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
  | 'baseline_adjusted'
  | 'backtrace_override'
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
  items?: BaselineReviewItemDecision[] | null,
): Promise<BaselineRevision> {
  const { data } = await client.post<BaselineRevision>(
    `${BASELINES(projectId)}/reviews/${revisionId}/approve`,
    { comment, items: items ?? undefined },
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

// ------------------------------------------------------- 分点审核（T97）

export type ReviewEntityType = 'module' | 'function' | 'feature_point'
export type ReviewDecisionValue = 'pending' | 'approved' | 'rejected'

export interface BaselineReviewItemDecision {
  entity_type: ReviewEntityType
  entity_id: number
  decision: ReviewDecisionValue
  comment?: string | null
}

export interface BaselineReviewStats {
  total: number
  approved: number
  rejected: number
  pending: number
}

export interface BaselineReviewItem {
  id: number
  entity_type: ReviewEntityType
  entity_id: number
  entity_name: string
  decision: ReviewDecisionValue
  comment: string | null
  decided_by: number | null
  decided_at: string | null
}

export interface BaselineReviewItems {
  revision_id: number
  round_id: number
  round_no: number
  status: string
  items: BaselineReviewItem[]
  stats: BaselineReviewStats
}

export interface BaselineReviewTreeNode {
  entity_type: ReviewEntityType
  entity_id: number
  name: string
  description: string | null
  source_type: string | null
  version_no: number | null
  decision: ReviewDecisionValue
  comment: string | null
  children: BaselineReviewTreeNode[]
}

export interface BaselineReviewTree {
  revision_id: number
  round_id: number
  round_no: number
  status: string
  tree: BaselineReviewTreeNode[]
  stats: BaselineReviewStats
}

export interface BaselineReviewDecideResult {
  updated: number
  stats: BaselineReviewStats
}

export async function fetchBaselineReviewTree(
  projectId: number,
  revisionId: number,
): Promise<BaselineReviewTree> {
  const { data } = await client.get<BaselineReviewTree>(
    `${BASELINES(projectId)}/reviews/${revisionId}/tree`,
  )
  return data
}

export async function fetchBaselineReviewItems(
  projectId: number,
  revisionId: number,
): Promise<BaselineReviewItems> {
  const { data } = await client.get<BaselineReviewItems>(
    `${BASELINES(projectId)}/reviews/${revisionId}/items`,
  )
  return data
}

export async function decideBaselineReview(
  projectId: number,
  revisionId: number,
  items: BaselineReviewItemDecision[],
): Promise<BaselineReviewDecideResult> {
  const { data } = await client.post<BaselineReviewDecideResult>(
    `${BASELINES(projectId)}/reviews/${revisionId}/decide`,
    { items },
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

/* ------------------------------------------------------ 测试点分析（07） */

export type TestPointAnalysisStatus = 'pending' | 'running' | 'succeeded' | 'failed'
export type TestPointStatus = 'pending' | 'approved' | 'rejected'
export type TestPointPriority = 'high' | 'medium' | 'low'
export type TestPointTargetType = 'function' | 'feature_point'
export type TestPointSourceType = 'llm' | 'manual'

/** 丢弃明细：只留痕，不写业务表。 */
export interface TestPointDiscard {
  chapter_id: number
  chapter_title: string
  name: string
  target_type?: string
  target_id?: number
  code: string
}

export interface TestPointStats {
  chapter_count: number
  processed_count: number
  test_point_count: number
  discarded_count: number
  skipped_empty_count: number
  discarded: TestPointDiscard[]
}

export interface TestPointAnalysis {
  id: number
  project_id: number
  template_id: number
  template_name: string | null
  template_version: number
  provider: string
  /** 作为依据的增量分析记录；没有则为 null。 */
  analysis_id: number | null
  baseline_revision_id: number | null
  document_id: number | null
  document_name: string | null
  document_version_id: number | null
  status: TestPointAnalysisStatus
  error_code: string | null
  error_message: string | null
  stats: TestPointStats | null
  started_at: string | null
  finished_at: string | null
  created_by: number
  created_at: string
}

export interface TestPointAnalysisDetail extends TestPointAnalysis {
  points: TestPoint[]
}

export interface TestPoint {
  id: number
  project_id: number
  /** 来源生成记录；手工新增为 null。 */
  analysis_id: number | null
  name: string
  target_type: TestPointTargetType
  target_id: number
  /** 落库快照——目标后来改名、被删，历史测试点仍对得上原文。 */
  target_name: string
  priority: TestPointPriority
  precondition: string | null
  verification: string | null
  chapter_id: number | null
  chapter_title: string | null
  source_label_id: number | null
  source_conclusion_id: number | null
  status: TestPointStatus
  reviewed_by: number | null
  reviewed_at: string | null
  review_comment: string | null
  /** 依赖的基线标签被清除后置真，只提示复核，不改内容。 */
  needs_review: boolean
  needs_review_reason: string | null
  needs_review_at: string | null
  source_type: TestPointSourceType
  created_by: number
  created_at: string
  updated_at: string
}

export interface TestPointAnalysisPayload {
  template_id: number
  analysis_id?: number | null
  baseline_revision_id?: number | null
  document_id?: number | null
  document_version_id?: number | null
  chapter_ids?: number[] | null
}

export interface TestPointPayload {
  name: string
  target_type: TestPointTargetType
  target_id: number
  priority?: TestPointPriority
  precondition?: string | null
  verification?: string | null
  chapter_id?: number | null
}

/** 手工改：只接受这 4 个字段，传别的会 400 `TEST_POINT_INVALID`。 */
export interface TestPointUpdatePayload {
  name?: string
  priority?: TestPointPriority
  precondition?: string | null
  verification?: string | null
}

const TEST_POINTS = (projectId: number) => `/projects/${projectId}/test-points`

export async function listTestPointAnalyses(
  projectId: number,
  params?: { page?: number; page_size?: number },
): Promise<Page<TestPointAnalysis>> {
  const { data } = await client.get<Page<TestPointAnalysis>>(
    `${TEST_POINTS(projectId)}/analyses`,
    { params },
  )
  return data
}

/** 发起生成。后端同步跑完才返回，响应直接带上产出的测试点。 */
export async function createTestPointAnalysis(
  projectId: number,
  payload: TestPointAnalysisPayload,
): Promise<TestPointAnalysisDetail> {
  const { data } = await client.post<TestPointAnalysisDetail>(
    `${TEST_POINTS(projectId)}/analyses`,
    payload,
  )
  return data
}

export async function fetchTestPointAnalysis(
  projectId: number,
  analysisId: number,
): Promise<TestPointAnalysisDetail> {
  const { data } = await client.get<TestPointAnalysisDetail>(
    `${TEST_POINTS(projectId)}/analyses/${analysisId}`,
  )
  return data
}

export async function listTestPointAnalysisPoints(
  projectId: number,
  analysisId: number,
): Promise<TestPoint[]> {
  const { data } = await client.get<TestPoint[]>(
    `${TEST_POINTS(projectId)}/analyses/${analysisId}/points`,
  )
  return data
}

/** 删除生成记录，连带删除它产出的测试点；已有评审通过的点会 409。 */
export async function deleteTestPointAnalysis(
  projectId: number,
  analysisId: number,
): Promise<void> {
  await client.delete(`${TEST_POINTS(projectId)}/analyses/${analysisId}`)
}

export async function listTestPoints(
  projectId: number,
  params?: {
    status?: TestPointStatus
    target_type?: TestPointTargetType
    target_id?: number
    analysis_id?: number
    page?: number
    page_size?: number
  },
): Promise<Page<TestPoint>> {
  const { data } = await client.get<Page<TestPoint>>(`${TEST_POINTS(projectId)}/points`, {
    params,
  })
  return data
}

export async function createTestPoint(
  projectId: number,
  payload: TestPointPayload,
): Promise<TestPoint> {
  const { data } = await client.post<TestPoint>(`${TEST_POINTS(projectId)}/points`, payload)
  return data
}

export async function fetchTestPoint(projectId: number, pointId: number): Promise<TestPoint> {
  const { data } = await client.get<TestPoint>(`${TEST_POINTS(projectId)}/points/${pointId}`)
  return data
}

export async function updateTestPoint(
  projectId: number,
  pointId: number,
  payload: TestPointUpdatePayload,
): Promise<TestPoint> {
  const { data } = await client.patch<TestPoint>(
    `${TEST_POINTS(projectId)}/points/${pointId}`,
    payload,
  )
  return data
}

export async function deleteTestPoint(projectId: number, pointId: number): Promise<void> {
  await client.delete(`${TEST_POINTS(projectId)}/points/${pointId}`)
}

export async function reviewTestPoint(
  projectId: number,
  pointId: number,
  payload: { action: 'approve' | 'reject'; comment?: string | null },
): Promise<TestPoint> {
  const { data } = await client.post<TestPoint>(
    `${TEST_POINTS(projectId)}/points/${pointId}/review`,
    payload,
  )
  return data
}

/* ------------------------------------------------------ 测试用例分析（08） */

export type TestCaseAnalysisStatus = 'pending' | 'running' | 'succeeded' | 'failed'
export type TestCaseStatus = 'pending' | 'approved' | 'rejected'
export type TestCasePriority = 'high' | 'medium' | 'low'
export type TestCaseType = 'functional' | 'api' | 'ui'
export type TestCaseSourceType = 'llm' | 'manual'

/** 丢弃明细：只留痕，不写业务表。 */
export interface TestCaseDiscard {
  test_point_id: number
  test_point_name: string
  title: string
  code: string
}

export interface TestCaseStats {
  test_point_count: number
  case_count: number
  step_count: number
  discarded_count: number
  discarded: TestCaseDiscard[]
}

export interface TestCaseAnalysis {
  id: number
  project_id: number
  template_id: number
  template_name: string | null
  template_version: number
  provider: string
  /** 作为依据的测试点批次；没有则为 null。 */
  test_point_analysis_id: number | null
  chapter_ids: number[] | null
  status: TestCaseAnalysisStatus
  error_code: string | null
  error_message: string | null
  stats: TestCaseStats | null
  started_at: string | null
  finished_at: string | null
  created_by: number
  created_at: string
}

export interface TestCaseStep {
  step_no: number
  action: string
  expected: string
}

export interface TestCase {
  id: number
  project_id: number
  /** 来源生成记录；手工新增为 null。 */
  analysis_id: number | null
  test_point_id: number
  /** 落库快照——测试点后来改名、被删，历史用例仍对得上原文。 */
  test_point_name: string
  title: string
  case_type: TestCaseType
  priority: TestCasePriority
  precondition: string | null
  target_type: string
  target_id: number
  target_name: string
  chapter_id: number | null
  chapter_title: string | null
  status: TestCaseStatus
  reviewed_by: number | null
  reviewed_at: string | null
  review_comment: string | null
  source_type: TestCaseSourceType
  /** 源测试点变了或被删 → 待复核。读时派生，不落库。 */
  needs_review: boolean
  needs_review_reason: string | null
  needs_review_ack_at: string | null
  created_by: number
  created_at: string
  updated_at: string
  steps: TestCaseStep[]
}

export interface TestCaseAnalysisDetail extends TestCaseAnalysis {
  cases: TestCase[]
}

export interface TestCaseAnalysisPayload {
  template_id: number
  /** 显式指定测试点：严格模式，任一不满足就 400。 */
  test_point_ids?: number[] | null
  chapter_ids?: number[] | null
  target_type?: string | null
  target_id?: number | null
  test_point_analysis_id?: number | null
}

export interface TestCasePayload {
  test_point_id: number
  title: string
  case_type?: TestCaseType
  priority?: TestCasePriority
  precondition?: string | null
  steps?: Array<{ action: string; expected?: string | null }>
}

/** 手工改：只接受这 4 个字段，传别的会 400 `TEST_CASE_INVALID`。 */
export interface TestCaseUpdatePayload {
  title?: string
  case_type?: TestCaseType
  priority?: TestCasePriority
  precondition?: string | null
}

const TEST_CASES = (projectId: number) => `/projects/${projectId}/test-cases`

export async function listTestCaseAnalyses(
  projectId: number,
  params?: { page?: number; page_size?: number },
): Promise<Page<TestCaseAnalysis>> {
  const { data } = await client.get<Page<TestCaseAnalysis>>(
    `${TEST_CASES(projectId)}/analyses`,
    { params },
  )
  return data
}

/** 发起生成。后端同步跑完才返回，响应直接带上产出的用例。 */
export async function createTestCaseAnalysis(
  projectId: number,
  payload: TestCaseAnalysisPayload,
): Promise<TestCaseAnalysisDetail> {
  const { data } = await client.post<TestCaseAnalysisDetail>(
    `${TEST_CASES(projectId)}/analyses`,
    payload,
  )
  return data
}

export async function fetchTestCaseAnalysis(
  projectId: number,
  analysisId: number,
): Promise<TestCaseAnalysisDetail> {
  const { data } = await client.get<TestCaseAnalysisDetail>(
    `${TEST_CASES(projectId)}/analyses/${analysisId}`,
  )
  return data
}

/** 删除生成记录，连带删除它产出的用例；已有评审通过的用例会 409。 */
export async function deleteTestCaseAnalysis(
  projectId: number,
  analysisId: number,
): Promise<void> {
  await client.delete(`${TEST_CASES(projectId)}/analyses/${analysisId}`)
}

export async function listTestCases(
  projectId: number,
  params?: {
    status?: TestCaseStatus
    test_point_id?: number
    target_type?: string
    target_id?: number
    analysis_id?: number
    needs_review?: boolean
    page?: number
    page_size?: number
  },
): Promise<Page<TestCase>> {
  const { data } = await client.get<Page<TestCase>>(`${TEST_CASES(projectId)}/cases`, {
    params,
  })
  return data
}

export async function createTestCase(
  projectId: number,
  payload: TestCasePayload,
): Promise<TestCase> {
  const { data } = await client.post<TestCase>(`${TEST_CASES(projectId)}/cases`, payload)
  return data
}

export async function fetchTestCase(projectId: number, caseId: number): Promise<TestCase> {
  const { data } = await client.get<TestCase>(`${TEST_CASES(projectId)}/cases/${caseId}`)
  return data
}

export async function updateTestCase(
  projectId: number,
  caseId: number,
  payload: TestCaseUpdatePayload,
): Promise<TestCase> {
  const { data } = await client.patch<TestCase>(
    `${TEST_CASES(projectId)}/cases/${caseId}`,
    payload,
  )
  return data
}

export async function deleteTestCase(projectId: number, caseId: number): Promise<void> {
  await client.delete(`${TEST_CASES(projectId)}/cases/${caseId}`)
}

/** 整体覆盖步骤——序号由服务端按数组顺序重排。 */
export async function replaceTestCaseSteps(
  projectId: number,
  caseId: number,
  steps: Array<{ action: string; expected?: string | null }>,
): Promise<TestCase> {
  const { data } = await client.put<TestCase>(
    `${TEST_CASES(projectId)}/cases/${caseId}/steps`,
    { steps },
  )
  return data
}

export async function reviewTestCase(
  projectId: number,
  caseId: number,
  payload: { action: 'approve' | 'reject'; comment?: string | null },
): Promise<TestCase> {
  const { data } = await client.post<TestCase>(
    `${TEST_CASES(projectId)}/cases/${caseId}/review`,
    payload,
  )
  return data
}

/** 确认已复核：刷新源测试点快照，之后不再提示。 */
export async function ackTestCase(projectId: number, caseId: number): Promise<TestCase> {
  const { data } = await client.post<TestCase>(
    `${TEST_CASES(projectId)}/cases/${caseId}/ack`,
  )
  return data
}

/** 导出 Excel：下载要带 Bearer 头，走 XHR 取 blob。 */
export async function exportTestCases(
  projectId: number,
  params?: {
    status?: TestCaseStatus
    test_point_id?: number
    target_type?: string
    target_id?: number
    analysis_id?: number
  },
): Promise<{ blob: Blob; fileName: string }> {
  const response = await client.get(`${TEST_CASES(projectId)}/cases/export`, {
    params,
    responseType: 'blob',
  })
  const disposition = String(response.headers['content-disposition'] ?? '')
  const encoded = disposition.match(/filename\*=utf-8''([^;]+)/i)?.[1]
  const plain = disposition.match(/filename="?([^";]+)"?/i)?.[1]
  return {
    blob: response.data as Blob,
    fileName: encoded ? decodeURIComponent(encoded) : (plain ?? '测试用例.xlsx'),
  }
}

/* ------------------------------------------------------ 自动化执行（09） */

export type AutomationFramework = 'pytest' | 'playwright'
export type AutomationAssetStatus = 'active' | 'archived'
export type AutomationScanStatus = 'new' | 'existing'
export type AutomationRunStatus = 'running' | 'succeeded' | 'failed'
export type AutomationResult = 'passed' | 'failed' | 'skipped'

/** 扫描清单里的一项（还没入库）。 */
export interface ScannedAsset {
  file_path: string
  name: string
  framework: AutomationFramework
  parse_confidence: number
  detected_cases: number
  status: AutomationScanStatus
  existing_asset_id: number | null
  low_confidence: boolean
}

/** 扫描结果。`root` 只是**相对展示名**（后端绝不返回绝对路径）。 */
export interface ScanResult {
  root: string
  directory: string
  scanned_files: number
  matched: number
  skipped: number
  assets: ScannedAsset[]
}

/** 一个自动化资产。 */
export interface AutomationAsset {
  id: number
  project_id: number
  name: string
  file_path: string
  framework: AutomationFramework
  source: string
  parse_confidence: number | null
  detected_cases: number
  linked_case_id: number | null
  /** 关联用例的**当前**名称。 */
  linked_case_title: string | null
  /** 关联的用例已被 08 物理删除。 */
  linked_case_deleted: boolean
  status: AutomationAssetStatus
  created_by: number
  created_at: string
}

/** 入库结果里的一项。 */
export interface CreatedAssetItem {
  file_path: string
  asset_id: number | null
  skipped: boolean
  reason: string | null
}

export interface AssetsCreateResult {
  created: number
  skipped: number
  items: CreatedAssetItem[]
}

/** 一条明细的追溯链——全部来自 08 已落库的用例快照。 */
export interface AutomationTraceability {
  linked_case_id: number | null
  case_title: string | null
  test_point_name: string | null
  target_name: string | null
  chapter_title: string | null
  /** 关联的用例已被 08 物理删除 → 只显示执行时的快照。 */
  source_case_deleted: boolean
}

/** 一条执行明细（粒度是**资产**，不是 pytest 的测试函数）。 */
export interface AutomationRunItem {
  asset_id: number
  file_path: string | null
  framework: AutomationFramework | null
  result: AutomationResult
  duration_ms: number | null
  error: string | null
  traceability: AutomationTraceability
}

/** 统计按**资产**维度，与明细行数始终一致。 */
export interface AutomationRunStats {
  total: number
  passed: number
  failed: number
  skipped: number
}

/**
 * 一次执行记录。
 *
 * `status` 表达「系统是否正常完成执行」：
 * `succeeded` = pytest 进程**正常跑完**（**哪怕 exit_code 是 1**——
 * 那只是「有测试失败」，是业务结果）；`failed` = 跑不起来，此时 `error` 非空。
 * **用例结果看 `items[].result`，两者不能混。**
 */
export interface AutomationRun {
  id: number
  project_id: number
  framework: AutomationFramework
  status: AutomationRunStatus
  exit_code: number | null
  stats: AutomationRunStats | null
  error: string | null
  started_at: string | null
  finished_at: string | null
  duration_ms: number | null
  created_by: number
  created_at: string
  items: AutomationRunItem[]
}

/** 单次报告：比列表多一份 `log`（执行输出）。 */
export interface AutomationRunReport extends AutomationRun {
  log: string | null
}

const AUTOMATION = (projectId: number) => `/projects/${projectId}/automation`

/** 扫描目录。**只出清单，不入库**——入库是另一个动作（人工确认）。 */
export async function scanAutomationAssets(
  projectId: number,
  directory: string,
): Promise<ScanResult> {
  const { data } = await client.post<ScanResult>(`${AUTOMATION(projectId)}/scan`, {
    directory,
  })
  return data
}

export async function listAutomationAssets(
  projectId: number,
  params?: {
    framework?: AutomationFramework
    status?: AutomationAssetStatus
    linked_case_id?: number
    page?: number
    page_size?: number
  },
): Promise<Page<AutomationAsset>> {
  const { data } = await client.get<Page<AutomationAsset>>(`${AUTOMATION(projectId)}/assets`, {
    params,
  })
  return data
}

/** 人工确认后批量入库。置信度与用例数由服务端重扫重算，不采信前端传值。 */
export async function createAutomationAssets(
  projectId: number,
  assets: Array<{
    file_path: string
    name?: string | null
    framework: AutomationFramework
    parse_confidence?: number | null
    detected_cases?: number | null
    skip?: boolean
  }>,
): Promise<AssetsCreateResult> {
  const { data } = await client.post<AssetsCreateResult>(`${AUTOMATION(projectId)}/assets`, {
    assets,
  })
  return data
}

export async function fetchAutomationAsset(
  projectId: number,
  assetId: number,
): Promise<AutomationAsset> {
  const { data } = await client.get<AutomationAsset>(
    `${AUTOMATION(projectId)}/assets/${assetId}`,
  )
  return data
}

/** 改资产（项目管理员）：关联 / 解绑用例、归档 / 恢复、刷新用例数。 */
export async function updateAutomationAsset(
  projectId: number,
  assetId: number,
  payload: {
    linked_case_id?: number | null
    status?: AutomationAssetStatus
    detected_cases?: number | null
  },
): Promise<AutomationAsset> {
  const { data } = await client.patch<AutomationAsset>(
    `${AUTOMATION(projectId)}/assets/${assetId}`,
    payload,
  )
  return data
}

/** 触发执行（**项目管理员**）。后端同步跑完才返回。 */
export async function createAutomationRun(
  projectId: number,
  assetIds: number[],
): Promise<AutomationRun> {
  const { data } = await client.post<AutomationRun>(`${AUTOMATION(projectId)}/runs`, {
    asset_ids: assetIds,
  })
  return data
}

export async function listAutomationRuns(
  projectId: number,
  params?: { page?: number; page_size?: number },
): Promise<Page<AutomationRun>> {
  const { data } = await client.get<Page<AutomationRun>>(`${AUTOMATION(projectId)}/runs`, {
    params,
  })
  return data
}

/** 单次报告：明细 + 追溯链 + 统计 + 日志。 */
export async function fetchAutomationRunReport(
  projectId: number,
  runId: number,
): Promise<AutomationRunReport> {
  const { data } = await client.get<AutomationRunReport>(
    `${AUTOMATION(projectId)}/runs/${runId}`,
  )
  return data
}
