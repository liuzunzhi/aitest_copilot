import { useCallback, useEffect, useState } from 'react'
import {
  App as AntdApp,
  Button,
  Card,
  Descriptions,
  Form,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useLocation, useParams } from 'react-router-dom'

import {
  addMember,
  fetchOverview,
  listMembers,
  listProjectApplications,
  removeMember,
  updateMemberRole,
} from '../api'
import type { Application, Member, Overview } from '../api'
import { errorMessage } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import ProjectBaselineSnapshots from './ProjectBaselineSnapshots'
import ProjectBaselineTree from './ProjectBaselineTree'
import ProjectBaselinesTab from './ProjectBaselinesTab'
import ProjectDocumentsTab from './ProjectDocumentsTab'
import ProjectIncrementalTab from './ProjectIncrementalTab'

const PROJECT_ROLE_LABELS: Record<string, string> = {
  project_admin: '项目管理员',
  member: '成员',
  guest: '访客',
}

const APPLICATION_STATUS_LABELS: Record<string, string> = {
  pending: '待审批',
  approved: '已通过',
  rejected: '已驳回',
  withdrawn: '已撤回',
  closed: '已关闭',
}

const STATUS_COLORS: Record<string, string> = {
  pending: 'orange',
  approved: 'green',
  rejected: 'red',
  withdrawn: 'default',
  closed: 'default',
}

export default function ProjectDetailPage() {
  const { id } = useParams()
  const projectId = Number(id)
  const location = useLocation()
  const { user } = useAuth()
  const { message } = AntdApp.useApp()

  const routeState = location.state as { name?: string; role?: string } | null
  const projectName = routeState?.name

  const [overview, setOverview] = useState<Overview | null>(null)
  // 文档变更后自增，驱动基线 Tab 重载（Tabs 切走不卸载）
  const [baselineKey, setBaselineKey] = useState(0)
  const [members, setMembers] = useState<Member[]>([])
  const [applications, setApplications] = useState<Application[]>([])
  const [loading, setLoading] = useState(false)
  const [adding, setAdding] = useState(false)
  const [form] = Form.useForm<{ user_id: number; role: string }>()

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
    void reloadMembers()
    void reloadApplications()
  }, [reloadOverview, reloadMembers, reloadApplications])

  async function submitAddMember() {
    const values = await form.validateFields()
    try {
      await addMember(projectId, values.user_id, values.role)
      message.success('成员已添加')
      setAdding(false)
      form.resetFields()
      await reloadMembers()
      await reloadOverview()
    } catch (error) {
      message.error(errorMessage(error))
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

  const memberColumns: ColumnsType<Member> = [
    { title: '用户名', dataIndex: 'username' },
    {
      title: '角色',
      dataIndex: 'role',
      width: 200,
      render: (role: string, member) =>
        canManage ? (
          <Select
            size="small"
            value={role}
            style={{ width: 140 }}
            onChange={(value) => changeRole(member, value)}
            options={Object.entries(PROJECT_ROLE_LABELS).map(([value, label]) => ({
              value,
              label,
            }))}
          />
        ) : (
          (PROJECT_ROLE_LABELS[role] ?? role)
        ),
    },
    {
      title: '加入时间',
      dataIndex: 'joined_at',
      width: 200,
      render: (value: string) => new Date(value).toLocaleString(),
    },
    ...(canManage
      ? [
          {
            title: '操作',
            key: 'actions',
            width: 100,
            render: (_: unknown, member: Member) => (
              <Popconfirm
                title="确认移除该成员？"
                okText="移除"
                cancelText="取消"
                onConfirm={() => handleRemove(member)}
              >
                <Button size="small" danger>
                  移除
                </Button>
              </Popconfirm>
            ),
          },
        ]
      : []),
  ]

  const applicationColumns: ColumnsType<Application> = [
    {
      title: '申请人',
      dataIndex: 'applicant',
      render: (applicant: Application['applicant']) => applicant?.username ?? '—',
    },
    { title: '申请理由', dataIndex: 'reason' },
    {
      title: '期望角色',
      dataIndex: 'desired_role',
      width: 120,
      render: (role: string) => PROJECT_ROLE_LABELS[role] ?? role,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (status: string) => (
        <Tag color={STATUS_COLORS[status] ?? 'default'}>
          {APPLICATION_STATUS_LABELS[status] ?? status}
        </Tag>
      ),
    },
  ]

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        {projectName ?? `项目 #${projectId}`}
      </Typography.Title>

      <Tabs
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
              </Card>
            ),
          },
          {
            key: 'members',
            label: '成员',
            children: (
              <div>
                {canManage ? (
                  <Space style={{ marginBottom: 16 }}>
                    <Button type="primary" onClick={() => setAdding(true)}>
                      添加成员
                    </Button>
                  </Space>
                ) : null}
                <Table<Member>
                  rowKey="user_id"
                  columns={memberColumns}
                  dataSource={members}
                  pagination={false}
                  data-testid="member-table"
                />
              </div>
            ),
          },
          {
            key: 'documents',
            label: '文档',
            children: (
              <ProjectDocumentsTab
                projectId={projectId}
                canWrite={canWrite}
                onChanged={reloadOverview}
              />
            ),
          },
          {
            key: 'baselines',
            label: '版本快照',
            children: <ProjectBaselinesTab projectId={projectId} refreshKey={baselineKey} />,
          },
          {
            key: 'baseline-management',
            label: '基线管理',
            children: (
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
                <Card title="功能基线结构" size="small">
                  <ProjectBaselineTree projectId={projectId} canWrite={canManage} />
                </Card>
                <ProjectBaselineSnapshots projectId={projectId} canWrite={canManage} />
              </Space>
            ),
          },
          {
            key: 'applications',
            label: '申请',
            children: (
              <Table<Application>
                rowKey="id"
                columns={applicationColumns}
                dataSource={applications}
                pagination={false}
              />
            ),
          },
          {
            key: 'incremental',
            label: '增量分析',
            children: <ProjectIncrementalTab projectId={projectId} canWrite={canManage} />,
          },
        ]}
      />

      <Modal
        open={adding}
        title="添加成员"
        onCancel={() => setAdding(false)}
        onOk={submitAddMember}
        okText="添加"
        cancelText="取消"
        okButtonProps={{ 'data-testid': 'modal-ok' }}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" initialValues={{ role: 'member' }} requiredMark={false}>
          <Form.Item
            name="user_id"
            label="用户 ID"
            rules={[{ required: true, message: '请输入用户 ID' }]}
          >
            <InputNumber min={1} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="role" label="角色" rules={[{ required: true }]}>
            <Select
              options={Object.entries(PROJECT_ROLE_LABELS).map(([value, label]) => ({
                value,
                label,
              }))}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
