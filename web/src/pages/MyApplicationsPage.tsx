import { useCallback, useEffect, useState } from 'react'
import { App as AntdApp, Select, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'

import { listMyApplications } from '../api'
import type { Application } from '../api'
import { errorMessage } from '../api/client'

const ROLE_LABELS: Record<string, string> = {
  project_admin: '项目管理员',
  member: '成员',
  guest: '访客',
}

const STATUS_LABELS: Record<string, string> = {
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

export default function MyApplicationsPage() {
  const { message } = AntdApp.useApp()
  const [items, setItems] = useState<Application[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [status, setStatus] = useState<string | undefined>(undefined)
  const [loading, setLoading] = useState(false)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const result = await listMyApplications({ status, page, page_size: pageSize })
      setItems(result.items)
      setTotal(result.total)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [status, page, pageSize, message])

  useEffect(() => {
    void reload()
  }, [reload])

  const columns: ColumnsType<Application> = [
    {
      title: '项目',
      dataIndex: 'project',
      render: (project: Application['project']) => project?.name ?? '—',
    },
    { title: '申请理由', dataIndex: 'reason' },
    {
      title: '期望角色',
      dataIndex: 'desired_role',
      width: 120,
      render: (role: string) => ROLE_LABELS[role] ?? role,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (value: string) => (
        <Tag color={STATUS_COLORS[value] ?? 'default'}>{STATUS_LABELS[value] ?? value}</Tag>
      ),
    },
    {
      title: '申请时间',
      dataIndex: 'created_at',
      width: 200,
      render: (value: string) => new Date(value).toLocaleString(),
    },
    {
      title: '驳回原因',
      dataIndex: 'reject_reason',
      render: (value: string | null) => value || '—',
    },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          我的申请
        </Typography.Title>
        <Select
          allowClear
          placeholder="按状态筛选"
          style={{ width: 160 }}
          value={status}
          onChange={(value) => {
            setPage(1)
            setStatus(value)
          }}
          options={Object.entries(STATUS_LABELS).map(([value, label]) => ({ value, label }))}
        />
      </Space>

      <Table<Application>
        rowKey="id"
        columns={columns}
        dataSource={items}
        loading={loading}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          onChange: (nextPage, nextSize) => {
            setPage(nextPage)
            setPageSize(nextSize)
          },
        }}
      />
    </div>
  )
}
