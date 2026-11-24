import { useState } from 'react'
import {
  Button,
  Form,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'

import type { Application, Member } from '../api'

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

interface Props {
  members: Member[]
  applications: Application[]
  /** 写入口限项目管理员（后端 403 NOT_PROJECT_ADMIN）。 */
  canManage: boolean
  /** 返回 true 表示添加成功——失败时弹窗保持打开（原行为）。 */
  onSubmitAddMember: (userId: number, role: string) => Promise<boolean>
  onChangeRole: (member: Member, role: string) => Promise<void>
  onRemoveMember: (member: Member) => Promise<void>
}

/**
 * 「成员」Tab 的**二级子菜单**外壳。
 *
 * 「申请」原先是第 6 个顶层 Tab，11 期把它合并进「成员」——
 * PRD 里「成员」与「申请」本来就是同一件事的两面（谁能进项目 / 谁想进项目），
 * 拆成两个顶层 Tab 反而割裂。
 *
 * **`defaultActiveKey="members"`**：现有用户路径不变——
 * 进来还是先看到成员列表（`member-table` 在 `test_smoke.py` /
 * `test_projects_ui.py` / `test_access_ui.py` 三处被直接断言可见）。
 *
 * **子 Tab label 用 `data-testid` 包裹**：antd 两层 `Tabs` 都用 `role="tab"`，
 * 且 Playwright 的 `get_by_role(name=)` 默认是**子串匹配**——
 * 顶层「成员」与内层「成员列表」名字互相包含，e2e 必须用
 * `get_by_test_id` 精确定位子 Tab（照抄 `process-baseline-subtab-*` 的做法）。
 *
 * **顶层 Tab 仍然是 8 个**：内层二级 Tabs 在 e2e 计数时**不计入顶层**——
 * 断言顶层要写 `get_by_role("tablist").first.get_by_role("tab")`。
 *
 * **受控组件**：`members` / `applications` 与所有写操作由父组件持有
 * （`canManage` 依赖 `myRole`，而 `myRole` 来自 `members`），
 * 这里只负责渲染与交互，避免重复请求成员列表。
 */
export default function ProjectMembersTab({
  members,
  applications,
  canManage,
  onSubmitAddMember,
  onChangeRole,
  onRemoveMember,
}: Props) {
  const [adding, setAdding] = useState(false)
  const [form] = Form.useForm<{ user_id: number; role: string }>()

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
            onChange={(value) => onChangeRole(member, value)}
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
                onConfirm={() => onRemoveMember(member)}
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

  async function submitAddMember() {
    const values = await form.validateFields()
    const ok = await onSubmitAddMember(values.user_id, values.role)
    // 失败时弹窗保持打开（用户能直接改值重试）——与原实现一致
    if (!ok) return
    setAdding(false)
    form.resetFields()
  }

  return (
    <div>
      <Tabs
        defaultActiveKey="members"
        data-testid="project-members-subtab"
        items={[
          {
            key: 'members',
            label: <span data-testid="project-members-subtab-members">成员列表</span>,
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
            key: 'applications',
            label: (
              <span data-testid="project-members-subtab-applications">加入申请</span>
            ),
            children: (
              <Table<Application>
                rowKey="id"
                columns={applicationColumns}
                dataSource={applications}
                pagination={false}
                data-testid="application-table"
              />
            ),
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
