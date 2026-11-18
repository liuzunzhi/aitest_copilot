import { Result, Tabs, Typography } from 'antd'

import { useAuth } from '../auth/AuthProvider'
import LlmProviderPanel from './settings/LlmProviderPanel'
import PromptTemplatePanel from './settings/PromptTemplatePanel'

export default function AdminSettingsPage() {
  const { user } = useAuth()

  if (user?.global_role !== 'system_admin') {
    return <Result status="403" title="无权访问" subTitle="仅系统管理员可进入系统设置" />
  }

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        系统设置
      </Typography.Title>
      <div data-testid="admin-settings-tabs">
        <Tabs
          defaultActiveKey="llm"
          items={[
            {
              key: 'llm',
              label: '大模型配置',
              children: <LlmProviderPanel />,
            },
            {
              key: 'prompt',
              label: '提示词模板',
              children: <PromptTemplatePanel />,
            },
          ]}
        />
      </div>
    </div>
  )
}
