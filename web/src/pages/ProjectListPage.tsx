import { useCallback, useEffect, useState } from 'react'
import {
  App as AntdApp,
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { Link, useNavigate } from 'react-router-dom'

import {
  archiveProject,
  createProject,
  listMyProjects,
  updateProject,
} from '../api'
import type { Project } from '../api'
import { errorMessage } from '../api/client'
import { useAuth } from '../auth/AuthProvider'

const ROLE_LABELS: Record<string, string> = {
  project_admin: '项目管理员',
  member: '成员',
  guest: '访客',
}

const STATUS_LABELS: Record<string, string> = {
  active: '进行中',
  archived: '已归档',
}

interface ProjectForm {
  name: string
  description?: string
}

export default function ProjectListPage() {
  const { user } = useAuth()
  const { message } = AntdApp.useApp()
  const navigate = useNavigate()

  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(false)
  const [editing, setEditing] = useState<Project | null>(null)
  const [creating, setCreating] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm<ProjectForm>()

  const isSystemAdmin = user?.global_role === 'system_admin'

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      setProjects(await listMyProjects())
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [message])

  useEffect(() => {
    void reload()
  }, [reload])

  function openCreate() {
    form.resetFields()
    setCreating(true)
  }

  function openEdit(project: Project) {
    form.setFieldsValue({ name: project.name, description: project.description ?? undefined })
    setEditing(project)
  }

  async function submitForm() {
    const values = await form.validateFields()
    const description = values.description?.trim() ? values.description.trim() : null
    setSaving(true)
    try {
      if (editing) {
        await updateProject(editing.id, { name: values.name, description })
        message.success('项目已更新')
      } else {
        await createProject(values.name, description)
        message.success('项目已创建')
      }
      setCreating(false)
      setEditing(null)
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  async function handleArchive(project: Project) {
    try {
      await archiveProject(project.id)
      message.success('项目已归档')
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  const columns: ColumnsType<Project> = [
    {
      title: '项目名称',
      dataIndex: 'name',
      render: (name: string, project) => (
        <Link to={`/projects/${project.id}`} state={{ name, role: project.role }}>
          {name}
        </Link>
      ),
    },
    {
      title: '简介',
      dataIndex: 'description',
      render: (description: string | null) => description || '—',
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (status: string) => (
        <Tag color={status === 'active' ? 'green' : 'default'}>
          {STATUS_LABELS[status] ?? status}
        </Tag>
      ),
    },
    {
      title: '我的角色',
      dataIndex: 'role',
      width: 120,
      render: (role: string | undefined) => ROLE_LABELS[role ?? ''] ?? role ?? '—',
    },
    {
      title: '操作',
      key: 'actions',
      width: 220,
      render: (_, project) => (
        <Space>
          <Button
            size="small"
            onClick={() =>
              navigate(`/projects/${project.id}`, {
                state: { name: project.name, role: project.role },
              })
            }
          >
            详情
          </Button>
          {project.role === 'project_admin' && project.status === 'active' ? (
            <Button size="small" onClick={() => openEdit(project)}>
              编辑
            </Button>
          ) : null}
          {isSystemAdmin && project.status === 'active' ? (
            <Popconfirm
              title="归档后项目不可编辑，且不再出现在可申请列表"
              okText="归档"
              cancelText="取消"
              onConfirm={() => handleArchive(project)}
            >
              <Button size="small" danger data-testid={`archive-${project.id}`}>
                归档
              </Button>
            </Popconfirm>
          ) : null}
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          我的项目
        </Typography.Title>
        {isSystemAdmin ? (
          <Button type="primary" onClick={openCreate} data-testid="create-project">
            创建项目
          </Button>
        ) : null}
      </Space>

      <Table<Project>
        rowKey="id"
        columns={columns}
        dataSource={projects}
        loading={loading}
        pagination={false}
        data-testid="project-table"
      />

      <Modal
        open={creating || editing !== null}
        title={editing ? '编辑项目' : '创建项目'}
        onCancel={() => {
          setCreating(false)
          setEditing(null)
        }}
        onOk={submitForm}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        destroyOnHidden
      >
        <Form<ProjectForm> form={form} layout="vertical" requiredMark={false}>
          <Form.Item
            name="name"
            label="项目名称"
            rules={[{ required: true, message: '请输入项目名称' }]}
          >
            <Input maxLength={64} data-testid="project-name" />
          </Form.Item>
          <Form.Item name="description" label="项目简介">
            <Input.TextArea rows={3} maxLength={500} data-testid="project-description" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
