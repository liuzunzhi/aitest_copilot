import { Layout, Menu, Space, Tag, Typography, Button } from 'antd'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/AuthProvider'

const { Header, Sider, Content } = Layout

const ROLE_LABELS: Record<string, string> = {
  system_admin: '系统管理员',
  project_admin: '项目管理员',
  member: '成员',
  guest: '访客',
  user: '普通用户',
}

export default function AppLayout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const items = [
    { key: '/projects', label: <Link to="/projects">我的项目</Link> },
    {
      key: '/projects/available',
      label: <Link to="/projects/available">可申请项目</Link>,
    },
    { key: '/applications/mine', label: <Link to="/applications/mine">我的申请</Link> },
  ]
  if (user?.global_role === 'system_admin') {
    items.push(
      {
        key: '/admin/applications',
        label: <Link to="/admin/applications">全局申请</Link>,
      },
      {
        key: '/admin/users',
        label: <Link to="/admin/users">用户管理</Link>,
      },
    )
  }

  // `/projects/available` 也以 `/projects` 开头，取匹配最长的那一项。
  const matched = items.filter((item) => location.pathname.startsWith(item.key))
  const selected = matched.length
    ? [matched.reduce((longest, item) => (item.key.length > longest.key.length ? item : longest)).key]
    : []

  async function handleLogout() {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider theme="light" width={200}>
        <div style={{ padding: '20px 16px', fontWeight: 600, fontSize: 16 }}>
          AI 辅助测试平台
        </div>
        <Menu mode="inline" selectedKeys={selected} items={items} />
      </Sider>
      <Layout>
        <Header
          style={{
            background: '#fff',
            display: 'flex',
            justifyContent: 'flex-end',
            alignItems: 'center',
            paddingInline: 24,
          }}
        >
          <Space>
            <Typography.Text data-testid="current-username">{user?.username}</Typography.Text>
            <Tag color={user?.global_role === 'system_admin' ? 'gold' : 'blue'}>
              {ROLE_LABELS[user?.global_role ?? ''] ?? user?.global_role}
            </Tag>
            <Button onClick={handleLogout}>退出登录</Button>
          </Space>
        </Header>
        <Content style={{ padding: 24 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
