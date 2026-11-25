import { Card, Space, Tabs } from 'antd'

import ProjectBaselineSnapshots from './ProjectBaselineSnapshots'
import ProjectBaselineTree from './ProjectBaselineTree'
import ProjectProcessBaselineTab from './ProjectProcessBaselineTab'

interface Props {
  projectId: number
  /** 写入口限项目管理员（后端 403 NOT_PROJECT_ADMIN）。 */
  canManage: boolean
}

/**
 * 「基线管理」Tab 的**二级子菜单**外壳。
 *
 * PRD 2.4.2 里「功能基线」与「流程基线」是基线管理下的**并列子菜单**，
 * 所以这里用二级 `Tabs` 而不是纵向堆叠。
 *
 * **`defaultActiveKey="function"`**：现有用户路径不变——
 * 进来还是先看到功能基线。
 *
 * **功能基线面板的渲染逻辑一个字节都不改**：照抄原来
 * `ProjectDetailPage.tsx` 里的 `<Space direction="vertical">` +
 * `<Card title="功能基线结构">` + `ProjectBaselineTree` +
 * `ProjectBaselineSnapshots`——e2e 的
 * `TAB_ANCHORS["基线管理"] = "baseline-keyword"` 依赖它。
 *
 * **顶层 Tab 是 8 个**（11 期 T124 起由 10 个收敛为 8 个）：antd `Tabs` 的
 * 非活动面板是**懒渲染**，内层二级 Tabs 在 e2e 计数时**尚未挂载**，
 * 所以顶层计数要限定 `get_by_role("tablist").first`（AC-212）。
 */
export default function ProjectBaselineManagementTab({ projectId, canManage }: Props) {
  return (
    <Tabs
      defaultActiveKey="function"
      data-testid="process-baseline-subtab"
      items={[
        {
          key: 'function',
          label: (
            <span data-testid="process-baseline-subtab-function">功能基线</span>
          ),
          children: (
            <Space direction="vertical" size={16} style={{ width: '100%' }}>
              <Card title="功能基线结构" size="small">
                <ProjectBaselineTree projectId={projectId} canWrite={canManage} />
              </Card>
              <ProjectBaselineSnapshots projectId={projectId} canWrite={canManage} />
            </Space>
          ),
        },
        {
          key: 'process',
          label: (
            <span data-testid="process-baseline-subtab-process">流程基线</span>
          ),
          children: (
            <ProjectProcessBaselineTab projectId={projectId} canManage={canManage} />
          ),
        },
      ]}
    />
  )
}
