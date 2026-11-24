import { useCallback, useEffect, useState } from 'react'
import {
  App as AntdApp,
  Card,
  Descriptions,
  Space,
  Tabs,
  Typography,
} from 'antd'
import { useLocation, useParams } from 'react-router-dom'

import {
  addMember,
  fetchOverview,
  fetchTodos,
  listMembers,
  listProjectApplications,
  removeMember,
  updateMemberRole,
} from '../api'
import type { Application, Member, Overview, Todos } from '../api'
import { errorMessage } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import ProjectBaselineManagementTab from './ProjectBaselineManagementTab'
import ProjectBaselinesTab from './ProjectBaselinesTab'
import ProjectAutomationTab from './ProjectAutomationTab'
import ProjectDocumentsTab from './ProjectDocumentsTab'
import ProjectIncrementalTab from './ProjectIncrementalTab'
import ProjectMembersTab from './ProjectMembersTab'
import ProjectTestCasesTab from './ProjectTestCasesTab'
import ProjectTestPointsTab from './ProjectTestPointsTab'
import ProjectTodoCard from './ProjectTodoCard'

export default function ProjectDetailPage() {
  const { id } = useParams()
  const projectId = Number(id)
  const location = useLocation()
  const { user } = useAuth()
  const { message } = AntdApp.useApp()

  const routeState = location.state as { name?: string; role?: string } | null
  const projectName = routeState?.name

  const [overview, setOverview] = useState<Overview | null>(null)
  const [todos, setTodos] = useState<Todos | null>(null)
  // 文档变更后自增，驱动基线 Tab 重载（Tabs 切走不卸载）
  const [baselineKey, setBaselineKey] = useState(0)
  // Tabs 改为受控：待办卡片的数字要能跳到指定 Tab
  const [activeTab, setActiveTab] = useState('overview')
  const [members, setMembers] = useState<Member[]>([])
  const [applications, setApplications] = useState<Application[]>([])
  const [loading, setLoading] = useState(false)

  // 直接按 URL 进入项目时 routeState 为空，用成员列表里的真实角色兜底，
  // 否则功能基线页会误判成「不可写」。
  const myRole = members.find((member) => member.user_id === user?.id)?.role
  const isProjectAdmin =
    user?.global_role === 'system_admin' ||
    routeState?.role === 'project_admin' ||
    myRole === 'project_admin'
  const canManage = isProjectAdmin
  // 访客只能看；上传/确认/作废由后端再校验「成员只能动自己上传的版本」。
  const canWrite =
    canManage || routeState?.role === 'member' || myRole === 'member'

  const reloadOverview = useCallback(async () => {
    setLoading(true)
    try {
      setOverview(await fetchOverview(projectId))
      setBaselineKey((key) => key + 1)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [projectId, message])

  const reloadTodos = useCallback(async () => {
    try {
      setTodos(await fetchTodos(projectId))
    } catch {
      // 待办是辅助信息，取不到时静默降级为空计数，不打断页面
      setTodos(null)
    }
  }, [projectId])

  const reloadMembers = useCallback(async () => {
    try {
      setMembers(await listMembers(projectId))
    } catch (error) {
      message.error(errorMessage(error))
    }
  }, [projectId, message])

  const reloadApplications = useCallback(async () => {
    try {
      const page = await listProjectApplications(projectId, { page: 1, page_size: 20 })
      setApplications(page.items)
    } catch {
      // 非项目管理员看不到申请列表，静默降级为空
      setApplications([])
    }
  }, [projectId])

  useEffect(() => {
    void reloadOverview()
    void reloadTodos()
    void reloadMembers()
    void reloadApplications()
  }, [reloadOverview, reloadTodos, reloadMembers, reloadApplications])

  async function submitAddMember(userId: number, role: string) {
    try {
      await addMember(projectId, userId, role)
      message.success('成员已添加')
      await reloadMembers()
      await reloadOverview()
      return true
    } catch (error) {
      message.error(errorMessage(error))
      return false
    }
  }

  async function changeRole(member: Member, role: string) {
    try {
      await updateMemberRole(projectId, member.user_id, role)
      message.success('角色已更新')
      await reloadMembers()
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  async function handleRemove(member: Member) {
    try {
      await removeMember(projectId, member.user_id)
      message.success('成员已移除')
      await reloadMembers()
      await reloadOverview()
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        {projectName ?? `项目 #${projectId}`}
      </Typography.Title>

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'overview',
            label: '概览',
            children: (
              <Card loading={loading}>
                <Descriptions column={2} data-testid="project-overview">
                  <Descriptions.Item label="成员数">{overview?.member_count ?? 0}</Descriptions.Item>
                  <Descriptions.Item label="文档数">{overview?.document_count ?? 0}</Descriptions.Item>
                  <Descriptions.Item label="功能基线数">
                    {overview?.baseline_count ?? 0}
                  </Descriptions.Item>
                  <Descriptions.Item label="最近执行">
                    {overview?.latest_execution ? '已有执行记录' : '暂无'}
                  </Descriptions.Item>
                </Descriptions>
                <ProjectTodoCard todos={todos} onNavigate={setActiveTab} />
              </Card>
            ),
          },
          {
            key: 'documents',
            label: '文档',
            children: (
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
                <ProjectDocumentsTab
                  projectId={projectId}
                  canWrite={canWrite}
                  onChanged={reloadOverview}
                />
                {/* 「版本快照」原先是第 4 个顶层 Tab，11 期收敛进「文档」——
                    基线本来就是「文档版本确认生效」的产物，语义归属文档。
                    `ProjectBaselinesTab` 组件文件零改动，只是换了挂载点。 */}
                <Card title="版本快照" size="small">
                  <ProjectBaselinesTab projectId={projectId} refreshKey={baselineKey} />
                </Card>
              </Space>
            ),
          },
          {
            key: 'baseline-management',
            label: '基线管理',
            children: (
              <ProjectBaselineManagementTab projectId={projectId} canManage={canManage} />
            ),
          },
          {
            key: 'incremental',
            label: '增量分析',
            children: <ProjectIncrementalTab projectId={projectId} canWrite={canManage} />,
          },
          {
            key: 'test-points',
            label: '测试点',
            children: <ProjectTestPointsTab projectId={projectId} canWrite={canManage} />,
          },
          {
            key: 'test-cases',
            label: '测试用例',
            children: <ProjectTestCasesTab projectId={projectId} canWrite={canManage} />,
          },
          {
            key: 'automation',
            label: <span data-testid="automation-tab">自动化执行</span>,
            children: <ProjectAutomationTab projectId={projectId} canManage={canManage} />,
          },
          {
            key: 'members',
            label: '成员',
            children: (
              <ProjectMembersTab
                members={members}
                applications={applications}
                canManage={canManage}
                onSubmitAddMember={submitAddMember}
                onChangeRole={changeRole}
                onRemoveMember={handleRemove}
              />
            ),
          },
        ]}
      />
    </div>
  )
}
