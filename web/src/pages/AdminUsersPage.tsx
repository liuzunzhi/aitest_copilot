import { useCallback, useEffect, useState } from 'react'
import { App as AntdApp, Button, Input, Result, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'

import { listUsers, updateUserRole } from '../api'
import type { AdminUser } from '../api'
import { errorMessage } from '../api/client'
import { useAuth } from '../auth/AuthProvider'

const ROLE_LABELS: Record<string, string> = {
  system_admin: '系统管理员',
  user: '普通用户',
}

const STATUS_LABELS: Record<string, string> = {
  active: '启用',
  disabled: '已禁用',
}

export default function AdminUsersPage() {
  const { user } = useAuth()
  const { message } = AntdApp.useApp()
  const [users, setUsers] = useState<AdminUser[]>([])
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(false)
  const [busyId, setBusyId] = useState<number | null>(null)

  const reload = useCallback(async () => {
    if (user?.global_role !== 'system_admin') return
    setLoading(true)
    try {
      setUsers(await listUsers())
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [message, user])

  useEffect(() => {
    void reload()
  }, [reload])

  async function changeRole(target: AdminUser, globalRole: string) {
    setBusyId(target.id)
    try {
      await updateUserRole(target.id, globalRole)
      message.success(
        globalRole === 'system_admin' ? '已提升为系统管理员' : '已降为普通用户',
      )
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setBusyId(null)
    }
  }

  if (user?.global_role !== 'system_admin') {
    return <Result status="403" title="无权访问" subTitle="仅系统管理员可管理用户" />
  }

  const columns: ColumnsType<AdminUser> = [
    {
      title: '用户名',
      dataIndex: 'username',
      render: (username: string) => (
        <Typography.Text data-testid={`user-${username}`}>{username}</Typography.Text>
      ),
    },
    {
      title: '全局角色',
      dataIndex: 'global_role',
      width: 140,
      render: (role: string) => (
        <Tag color={role === 'system_admin' ? 'gold' : 'blue'}>
          {ROLE_LABELS[role] ?? role}
        </Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (status: string) => STATUS_LABELS[status] ?? status,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 200,
      render: (value: string) => new Date(value).toLocaleString(),
    },
    {
      title: '操作',
      key: 'actions',
      width: 160,
      render: (_, target) => {
        if (target.id === user?.id) {
          return (
            <Typography.Text type="secondary">当前账号</Typography.Text>
          )
        }
        return target.global_role === 'system_admin' ? (
          <Button
            size="small"
            danger
            loading={busyId === target.id}
            data-testid={`demote-${target.username}`}
            onClick={() => changeRole(target, 'user')}
          >
            降为普通用户
          </Button>
        ) : (
          <Button
            size="small"
            loading={busyId === target.id}
            data-testid={`promote-${target.username}`}
            onClick={() => changeRole(target, 'system_admin')}
          >
            设为系统管理员
          </Button>
        )
      },
    },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          用户管理
        </Typography.Title>
        <Input
          allowClear
          placeholder="按用户名搜索"
          style={{ width: 240 }}
          value={keyword}
          data-testid="user-search"
          onChange={(event) => setKeyword(event.target.value)}
        />
      </Space>

      <Table<AdminUser>
        rowKey="id"
        columns={columns}
        dataSource={[...users]
          .filter((item) => item.username.toLowerCase().includes(keyword.trim().toLowerCase()))
          .sort((a, b) => b.id - a.id)}
        loading={loading}
        data-testid="user-table"
        pagination={{ pageSize: 20, showSizeChanger: false }}
      />
    </div>
  )
}
