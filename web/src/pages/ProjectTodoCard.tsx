import { Card, Space, Typography } from 'antd'

import type { Todos } from '../api'

/** 待办项 → 跳转的目标 Tab key（与 ProjectDetailPage 的 Tabs items 对齐）。 */
export type TodoTabKey = 'baseline-management' | 'test-points' | 'test-cases'

interface TodoCountProps {
  label: string
  value: number
  color: string
  onClick: () => void
  testId: string
}

function TodoCount({ label, value, color, onClick, testId }: TodoCountProps) {
  return (
    <div
      onClick={onClick}
      style={{ cursor: 'pointer', minWidth: 96 }}
      data-testid={testId}
      role="button"
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onClick()
        }
      }}
    >
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {label}
      </Typography.Text>
      <div style={{ fontSize: 24, fontWeight: 600, color }}>{value}</div>
    </div>
  )
}

/**
 * 工作台待办卡片（PRD 2.3.1）。
 *
 * 三项构成「基线产出 → 评审 → 用例」的待评审队列；点击数字跳到对应 Tab。
 * 计数为 0 时同样可点——用户可能要去那个 Tab 看看「确实没有待办」。
 */
export default function ProjectTodoCard({
  todos,
  onNavigate,
}: {
  todos: Todos | null
  onNavigate: (tab: TodoTabKey) => void
}) {
  const items: Array<{
    label: string
    value: number
    color: string
    tab: TodoTabKey
    testId: string
  }> = [
    {
      label: '待审核基线',
      value: todos?.pending_baseline_reviews ?? 0,
      color: '#d46b08',
      tab: 'baseline-management',
      testId: 'todo-baseline-reviews',
    },
    {
      label: '待评审测试点',
      value: todos?.pending_test_point_reviews ?? 0,
      color: '#d48806',
      tab: 'test-points',
      testId: 'todo-test-point-reviews',
    },
    {
      label: '待评审用例',
      value: todos?.pending_test_case_reviews ?? 0,
      color: '#1677ff',
      tab: 'test-cases',
      testId: 'todo-test-case-reviews',
    },
  ]

  return (
    <Card title="我的待办" size="small" style={{ marginTop: 16 }} data-testid="todos-card">
      <Space size={40} wrap>
        {items.map((item) => (
          <TodoCount
            key={item.tab}
            label={item.label}
            value={item.value}
            color={item.color}
            testId={item.testId}
            onClick={() => onNavigate(item.tab)}
          />
        ))}
      </Space>
    </Card>
  )
}
