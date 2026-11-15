import { useCallback, useEffect, useState } from 'react'
import {
  App as AntdApp,
  Button,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  Result,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'

import { approveApplication, listAllApplications, rejectApplication } from '../api'
import type { Application } from '../api'
import { errorMessage } from '../api/client'
import { useAuth } from '../auth/AuthProvider'

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

const ROLE_LABELS: Record<string, string> = {
  project_admin: '项目管理员',
  member: '成员',
  guest: '访客',
}

export default function AdminApplicationsPage() {
  const { user } = useAuth()
  const { message } = AntdApp.useApp()
  const [items, setItems] = useState<Application[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [status, setStatus] = useState<string | undefined>('pending')
  const [rejecting, setRejecting] = useState<Application | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [loading, setLoading] = useState(false)

  const reload = useCallback(async () => {
    if (user?.global_role !== 'system_admin') return
    setLoading(true)
    try {
      const result = await listAllApplications({ status, page, page_size: pageSize })
      setItems(result.items)
      setTotal(result.total)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [status, page, pageSize, message, user])

  useEffect(() => {
    void reload()
  }, [reload])

  async function handleApprove(application: Application) {
    if (!application.project) return
    try {
      await approveApplication(application.project.id, application.id, application.desired_role)
      message.success('已通过')
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  async function submitReject() {
    if (!rejecting?.project) return
    try {
      await rejectApplication(rejecting.project.id, rejecting.id, rejectReason)
      message.success('已驳回')
      setRejecting(null)
      setRejectReason('')
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  if (user?.global_role !== 'system_admin') {
    return <Result status="403" title="无权访问" subTitle="仅系统管理员可查看全局申请记录" />
  }

  const columns: ColumnsType<Application> = [
    {
      title: '项目',
      dataIndex: 'project',
      render: (project: Application['project']) => project?.name ?? '—',
    },
    {
      title: '申请人',
      dataIndex: 'applicant',
      render: (applicant: Application['applicant']) => applicant?.username ?? '—',
    },
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
      title: '操作',
      key: 'actions',
      width: 160,
      render: (_, application) =>
        application.status === 'pending' ? (
          <Space>
            <Button size="small" type="primary" onClick={() => handleApprove(application)}>
              通过
            </Button>
            <Button size="small" danger onClick={() => setRejecting(application)}>
              驳回
            </Button>
          </Space>
        ) : (
          '—'
        ),
    },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          全局申请记录
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
        data-testid="admin-application-table"
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

      <Modal
        open={rejecting !== null}
        title="驳回申请"
        okText="确认驳回"
        cancelText="取消"
        okButtonProps={{ 'data-testid': 'modal-ok' }}
        onCancel={() => setRejecting(null)}
        onOk={submitReject}
      >
        <Input.TextArea
          rows={3}
          value={rejectReason}
          placeholder="驳回原因"
          onChange={(event) => setRejectReason(event.target.value)}
        />
      </Modal>
    </div>
  )
}
