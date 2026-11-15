import { useCallback, useEffect, useState } from 'react'
import {
  App as AntdApp,
  Button,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'

import { listAvailableProjects, submitApplication } from '../api'
import type { Project } from '../api'
import { errorMessage } from '../api/client'

const ROLE_LABELS: Record<string, string> = {
  member: '成员',
  guest: '访客',
}

interface ApplyForm {
  reason: string
  desired_role: string
}

export default function AvailableProjectsPage() {
  const { message } = AntdApp.useApp()
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(false)
  const [applying, setApplying] = useState<Project | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm<ApplyForm>()

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      setProjects(await listAvailableProjects())
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [message])

  useEffect(() => {
    void reload()
  }, [reload])

  function openApply(project: Project) {
    form.resetFields()
    form.setFieldsValue({ desired_role: 'member' })
    setApplying(project)
  }

  async function submitForm() {
    if (!applying) return
    const values = await form.validateFields()
    setSaving(true)
    try {
      await submitApplication(applying.id, values.reason.trim(), values.desired_role)
      message.success('申请已提交，等待项目管理员审批')
      setApplying(null)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  const columns: ColumnsType<Project> = [
    {
      title: '项目名称',
      dataIndex: 'name',
      render: (name: string) => <span data-testid={`available-${name}`}>{name}</span>,
    },
    {
      title: '简介',
      dataIndex: 'description',
      render: (description: string | null) => description || '—',
    },
    {
      title: '操作',
      key: 'actions',
      width: 140,
      render: (_, project) => (
        <Button
          size="small"
          data-testid={`apply-${project.id}`}
          onClick={() => openApply(project)}
        >
          申请加入
        </Button>
      ),
    },
  ]

  return (
    <div>
      <Space direction="vertical" style={{ marginBottom: 16 }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          可申请项目
        </Typography.Title>
        <Typography.Text type="secondary">
          这里列出你尚未加入的项目；提交申请后可在「我的申请」查看审批进度。
        </Typography.Text>
      </Space>

      <Table<Project>
        rowKey="id"
        columns={columns}
        dataSource={projects}
        loading={loading}
        pagination={false}
        data-testid="available-table"
      />

      <Modal
        open={applying !== null}
        title={`申请加入「${applying?.name ?? ''}」`}
        onCancel={() => setApplying(null)}
        onOk={submitForm}
        confirmLoading={saving}
        okText="提交申请"
        cancelText="取消"
        okButtonProps={{ 'data-testid': 'modal-ok' }}
        destroyOnHidden
      >
        <Form<ApplyForm> form={form} layout="vertical" requiredMark={false}>
          <Form.Item
            name="reason"
            label="申请理由"
            rules={[{ required: true, message: '请输入申请理由' }]}
          >
            <Input.TextArea rows={3} maxLength={500} data-testid="apply-reason" />
          </Form.Item>
          <Form.Item name="desired_role" label="期望角色">
            <Select
              data-testid="apply-role"
              options={Object.entries(ROLE_LABELS).map(([value, label]) => ({ value, label }))}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
