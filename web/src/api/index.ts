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
