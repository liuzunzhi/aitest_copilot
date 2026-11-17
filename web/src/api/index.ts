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
