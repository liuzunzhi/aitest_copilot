import { useCallback, useEffect, useState } from 'react'
import {
  App as AntdApp,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'

import {
  createLlmProvider,
  listLlmProviders,
  testLlmProvider,
  updateLlmProvider,
} from '../../api'
import type { LlmProvider, LlmProviderPayload } from '../../api'
import { errorMessage } from '../../api/client'

interface FormValues {
  name: string
  base_url: string
  api_key?: string
  model: string
  timeout_seconds: number
  status: 'active' | 'disabled'
  is_default: boolean
}

const DEFAULT_VALUES: FormValues = {
  name: '',
  base_url: '',
  api_key: '',
  model: '',
  timeout_seconds: 60,
  status: 'active',
  is_default: false,
}

const STATUS_LABELS: Record<string, string> = {
  active: '启用',
  disabled: '已停用',
}

export default function LlmProviderPanel() {
  const { message } = AntdApp.useApp()
  const [form] = Form.useForm<FormValues>()

  const [rows, setRows] = useState<LlmProvider[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<LlmProvider | null>(null)
  const [saving, setSaving] = useState(false)
  const [testingId, setTestingId] = useState<number | null>(null)
  const [defaultingId, setDefaultingId] = useState<number | null>(null)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      setRows(await listLlmProviders())
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
    setEditing(null)
    form.setFieldsValue(DEFAULT_VALUES)
    setOpen(true)
  }

  function openEdit(row: LlmProvider) {
    setEditing(row)
    form.setFieldsValue({
      name: row.name,
      base_url: row.base_url,
      // Key 不回显：留空表示不修改
      api_key: '',
      model: row.model,
      timeout_seconds: row.timeout_seconds,
      status: row.status,
      is_default: row.is_default,
    })
    setOpen(true)
  }

  async function submit() {
    let values: FormValues
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    if (!editing && !values.api_key?.trim()) {
      message.error('API Key 不能为空')
      return
    }

    const payload: LlmProviderPayload = {
      name: values.name,
      base_url: values.base_url,
      model: values.model,
      timeout_seconds: values.timeout_seconds,
      status: values.status,
      is_default: values.is_default,
    }
    if (values.api_key?.trim()) {
      payload.api_key = values.api_key
    }

    setSaving(true)
    try {
      if (editing) {
        await updateLlmProvider(editing.id, payload)
        message.success('配置已更新')
      } else {
        await createLlmProvider(payload)
        message.success('配置已创建')
      }
      setOpen(false)
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  async function runTest(row: LlmProvider) {
    setTestingId(row.id)
    try {
      // 失败也是 200 + ok=false，这里按结果展示而不是当异常
      const result = await testLlmProvider(row.id)
      if (result.ok) {
        message.success(`连通正常（${result.latency_ms}ms）`)
      } else {
        message.warning(`连通失败：${result.message}`)
      }
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setTestingId(null)
    }
  }

  async function makeDefault(row: LlmProvider) {
    setDefaultingId(row.id)
    try {
      await updateLlmProvider(row.id, { is_default: true })
      message.success(`已把「${row.name}」设为默认配置`)
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setDefaultingId(null)
    }
  }

  const columns: ColumnsType<LlmProvider> = [
    {
      title: '名称',
      dataIndex: 'name',
      render: (name: string, row) => (
        <Space size={4}>
          <Typography.Text data-testid={`llm-provider-name-${row.id}`}>{name}</Typography.Text>
          {row.is_default ? <Tag color="gold">默认</Tag> : null}
        </Space>
      ),
    },
    {
      title: '接口地址 / 模型',
      key: 'endpoint',
      render: (_: unknown, row) => (
        <span>
          {row.base_url}
          <br />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {row.model}
          </Typography.Text>
        </span>
      ),
    },
    {
      title: 'API Key',
      dataIndex: 'api_key_masked',
      width: 150,
      render: (masked: string, row) => (
        <Typography.Text code data-testid={`llm-provider-masked-${row.id}`}>
          {masked}
        </Typography.Text>
      ),
    },
    {
      title: '超时',
      dataIndex: 'timeout_seconds',
      width: 90,
      render: (value: number) => `${value} 秒`,
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
      title: '最近测试',
      key: 'last_test',
      width: 170,
      render: (_: unknown, row) => {
        if (!row.last_test_status) {
          return <Typography.Text type="secondary">未测试</Typography.Text>
        }
        const failed = row.last_test_status === 'failed'
        return (
          <span data-testid={`llm-provider-last-test-${row.id}`}>
            <Tag color={failed ? 'error' : 'success'}>{failed ? '失败' : '正常'}</Tag>
            <Typography.Text type={failed ? 'danger' : 'secondary'} style={{ fontSize: 12 }}>
              {failed ? row.last_test_error ?? '—' : '—'}
            </Typography.Text>
          </span>
        )
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 260,
      render: (_: unknown, row) => (
        <Space size={4}>
          <Button
            size="small"
            data-testid={`llm-provider-edit-${row.id}`}
            onClick={() => openEdit(row)}
          >
            编辑
          </Button>
          <Button
            size="small"
            loading={testingId === row.id}
            data-testid={`llm-provider-test-${row.id}`}
            onClick={() => runTest(row)}
          >
            测试连通性
          </Button>
          {row.is_default ? null : (
            <Button
              size="small"
              type="link"
              loading={defaultingId === row.id}
              data-testid={`llm-provider-default-${row.id}`}
              onClick={() => makeDefault(row)}
            >
              设为默认
            </Button>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }}>
        <Typography.Text type="secondary">
          没有默认配置时，增量分析会退化成内置 Mock（零真实网络请求）。
        </Typography.Text>
        <Button
          type="primary"
          data-testid="llm-provider-create-btn"
          onClick={openCreate}
        >
          新建配置
        </Button>
      </Space>

      <Table<LlmProvider>
        rowKey="id"
        columns={columns}
        dataSource={rows}
        loading={loading}
        pagination={false}
        locale={{ emptyText: '还没有大模型配置' }}
        data-testid="llm-provider-table"
      />

      <Modal
        title={editing ? '编辑大模型配置' : '新建大模型配置'}
        open={open}
        onCancel={() => setOpen(false)}
        // 表单常驻挂载，openEdit / openCreate 的 setFieldsValue 才能生效
        forceRender
        footer={[
          <Button key="cancel" onClick={() => setOpen(false)}>
            取消
          </Button>,
          <Button
            key="ok"
            type="primary"
            loading={saving}
            data-testid="llm-provider-submit"
            onClick={submit}
          >
            保存
          </Button>,
        ]}
      >
        <Form form={form} layout="vertical" initialValues={DEFAULT_VALUES}>
          <Form.Item
            name="name"
            label="配置名"
            rules={[{ required: true, message: '请填写配置名' }]}
          >
            <Input placeholder="如：DeepSeek 生产" data-testid="llm-provider-form-name" />
          </Form.Item>
          <Form.Item
            name="base_url"
            label="Base URL"
            rules={[{ required: true, message: '请填写 Base URL' }]}
          >
            <Input
              placeholder="https://api.deepseek.com/v1"
              data-testid="llm-provider-form-base-url"
            />
          </Form.Item>
          <Form.Item
            name="api_key"
            label="API Key"
            extra={editing ? `当前：${editing.api_key_masked}，留空表示不修改` : '只以密文落库，页面上只显示掩码'}
          >
            <Input.Password
              placeholder={editing ? '留空表示不修改' : 'sk-...'}
              autoComplete="new-password"
              data-testid="llm-provider-form-api-key"
            />
          </Form.Item>
          <Form.Item
            name="model"
            label="模型名"
            rules={[{ required: true, message: '请填写模型名' }]}
          >
            <Input placeholder="deepseek-chat" data-testid="llm-provider-form-model" />
          </Form.Item>
          <Form.Item
            name="timeout_seconds"
            label="超时（秒）"
            rules={[{ required: true, message: '请填写超时' }]}
          >
            <InputNumber
              min={1}
              max={300}
              style={{ width: '100%' }}
              data-testid="llm-provider-form-timeout"
            />
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Select
              options={[
                { value: 'active', label: '启用' },
                { value: 'disabled', label: '停用' },
              ]}
              data-testid="llm-provider-form-status"
            />
          </Form.Item>
          <Form.Item
            name="is_default"
            label="设为默认"
            valuePropName="checked"
            extra="设为默认会自动取消其它配置的默认标记"
          >
            <Switch data-testid="llm-provider-form-default" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
