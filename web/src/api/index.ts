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
