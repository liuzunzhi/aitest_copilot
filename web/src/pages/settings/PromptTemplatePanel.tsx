import { useCallback, useEffect, useState } from 'react'
import {
  App as AntdApp,
  Button,
  Form,
  Input,
  Modal,
  Select,
  Table,
  Tag,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'

import {
  fetchPromptTemplate,
  listPromptTemplates,
  updatePromptTemplate,
} from '../../api'
import type {
  PromptTemplateBrief,
  PromptTemplateDetail,
  PromptTemplateUpdatePayload,
} from '../../api'
import { errorMessage } from '../../api/client'

interface FormValues {
  name: string
  description: string
  status: 'active' | 'disabled'
  system_prompt: string
  user_prompt: string
}

const TASK_TYPE_LABELS: Record<string, string> = {
  incremental: '增量分析',
}

const STATUS_LABELS: Record<string, string> = {
  active: '启用',
  disabled: '已停用',
}

export default function PromptTemplatePanel() {
  const { message } = AntdApp.useApp()
  const [form] = Form.useForm<FormValues>()

  const [rows, setRows] = useState<PromptTemplateBrief[]>([])
  const [loading, setLoading] = useState(false)
  const [editing, setEditing] = useState<PromptTemplateDetail | null>(null)
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const page = await listPromptTemplates({ page_size: 100 })
      setRows(page.items)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [message])

  useEffect(() => {
    void reload()
  }, [reload])

  async function openEdit(row: PromptTemplateBrief) {
    try {
      const detail = await fetchPromptTemplate(row.id)
      setEditing(detail)
      form.setFieldsValue({
        name: detail.name,
        description: detail.description ?? '',
        status: detail.status,
        system_prompt: detail.system_prompt,
        user_prompt: detail.user_prompt,
      })
      setOpen(true)
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  async function submit() {
    if (!editing) return
    let values: FormValues
    try {
      values = await form.validateFields()
    } catch {
      return
    }

    // 只提交表单里的字段；task_type 不可改，后端也不收
    const payload: PromptTemplateUpdatePayload = {
      name: values.name,
      description: values.description,
      status: values.status,
      system_prompt: values.system_prompt,
      user_prompt: values.user_prompt,
    }

    setSaving(true)
    try {
      const result = await updatePromptTemplate(editing.id, payload)
      setEditing(result)
      message.success(`已保存，当前版本 v${result.version_no}`)
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  const columns: ColumnsType<PromptTemplateBrief> = [
    {
      title: '模板名',
      dataIndex: 'name',
      render: (name: string, row) => (
        <Typography.Text data-testid={`prompt-template-name-${row.id}`}>{name}</Typography.Text>
      ),
    },
    {
      title: '任务类型',
      dataIndex: 'task_type',
      width: 110,
      render: (taskType: string) => TASK_TYPE_LABELS[taskType] ?? taskType,
    },
    {
      title: '版本',
      dataIndex: 'version_no',
      width: 90,
      render: (value: number, row) => (
        <span data-testid={`prompt-template-version-${row.id}`}>v{value}</span>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (status: string) => (
        <Tag color={status === 'active' ? 'success' : 'default'}>
          {STATUS_LABELS[status] ?? status}
        </Tag>
      ),
    },
    {
      title: '描述',
      dataIndex: 'description',
      render: (value: string | null) => value ?? '—',
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 180,
      render: (value: string) => new Date(value).toLocaleString(),
    },
    {
      title: '操作',
      key: 'actions',
      width: 100,
      render: (_: unknown, row) => (
        <Button
          size="small"
          data-testid={`prompt-template-edit-${row.id}`}
          onClick={() => openEdit(row)}
        >
          编辑
        </Button>
      ),
    },
  ]

  return (
    <div>
      <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
        模板只允许编辑，不支持新建与删除。只有正文（System / User Prompt）变化时版本号才 +1，
        只改描述或状态不升版本。
      </Typography.Text>

      <Table<PromptTemplateBrief>
        rowKey="id"
        columns={columns}
        dataSource={rows}
        loading={loading}
        pagination={false}
        locale={{ emptyText: '还没有提示词模板' }}
        data-testid="prompt-template-table"
      />

      <Modal
        title={editing ? `编辑模板 · v${editing.version_no}` : '编辑模板'}
        open={open}
        onCancel={() => setOpen(false)}
        // 表单常驻挂载，openEdit 的 setFieldsValue 才能生效
        forceRender
        width={880}
        footer={[
          <Button key="cancel" onClick={() => setOpen(false)}>
            取消
          </Button>,
          <Button
            key="ok"
            type="primary"
            loading={saving}
            data-testid="prompt-template-save"
            onClick={submit}
          >
            保存
          </Button>,
        ]}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label="模板名"
            rules={[{ required: true, message: '请填写模板名' }]}
          >
            <Input data-testid="prompt-template-form-name" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea
              rows={2}
              maxLength={500}
              data-testid="prompt-template-form-description"
            />
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Select
              options={[
                { value: 'active', label: '启用' },
                { value: 'disabled', label: '停用' },
              ]}
              data-testid="prompt-template-form-status"
            />
          </Form.Item>
          <Form.Item
            name="system_prompt"
            label="System Prompt"
            rules={[{ required: true, message: 'System Prompt 不能为空' }]}
          >
            <Input.TextArea
              rows={8}
              data-testid="prompt-template-form-system"
            />
          </Form.Item>
          <Form.Item
            name="user_prompt"
            label="User Prompt"
            rules={[{ required: true, message: 'User Prompt 不能为空' }]}
          >
            <Input.TextArea
              rows={8}
              data-testid="prompt-template-form-user"
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
