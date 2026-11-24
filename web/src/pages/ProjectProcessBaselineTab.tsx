import { useCallback, useEffect, useState } from 'react'
import type React from 'react'
import {
  App as AntdApp,
  Button,
  Input,
  Select,
  Space,
  Table,
  Typography,
} from 'antd'

import {
  deleteProcessScenario,
  fetchProcessScenario,
  listProcessRevisions,
  listProcessScenarios,
} from '../api'
import type {
  ProcessScenario,
  ProcessSourceType,
  ProcessStatus,
} from '../api'
import { errorMessage } from '../api/client'
import ProcessBaselineDeriveModal from './ProcessBaselineDeriveModal'
import ProcessBaselineDrawer from './ProcessBaselineDrawer'
import ProcessBaselineReviewDrawer from './ProcessBaselineReviewDrawer'
import { buildProcessScenarioColumns } from './processBaselineColumns'
import {
  IN_REVIEW_TIP,
  SOURCE_TYPE_OPTIONS,
  STATUS_FILTER_OPTIONS,
} from './processBaselineMeta'

interface Props {
  projectId: number
  /** 写入口只有项目管理员能看到——不是「渲染了点了报 403」。 */
  canManage: boolean
}

/**
 * 「流程基线」子 Tab：场景列表 + 工具条。
 *
 * **写入口只有 `canManage` 才渲染**——成员与访客**一个写入口都看不到**
 * （不是「渲染了点了报 403」），只显示一句只读提示（与 09 期
 * `ProjectAutomationTab.tsx` 同一口径）。
 *
 * **审核期锁定**：项目内有 `status='submitted'` 的快照时，
 * 写入口禁用 + 提示「审核中，暂不可编辑」（后端会返 409）。
 *
 * **本文件只留状态与事件编排**，列定义在 `processBaselineColumns.tsx`
 * （验证约定 §4.3 的 400 行拆分阈值）。
 */
export default function ProjectProcessBaselineTab({ projectId, canManage }: Props) {
  const { message } = AntdApp.useApp()
  const [scenarios, setScenarios] = useState<ProcessScenario[]>([])
  const [loading, setLoading] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [sourceType, setSourceType] = useState<ProcessSourceType | undefined>()
  const [statusFilter, setStatusFilter] = useState<ProcessStatus | 'all'>('active')
  const [inReview, setInReview] = useState(false)

  const [deriveOpen, setDeriveOpen] = useState(false)
  const [reviewOpen, setReviewOpen] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [detail, setDetail] = useState<ProcessScenario | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const [page, revisions] = await Promise.all([
        listProcessScenarios(projectId, {
          keyword: keyword.trim() || undefined,
          source_type: sourceType,
          status: statusFilter,
          page_size: 200,
        }),
        listProcessRevisions(projectId, { status: 'submitted', page_size: 1 }),
      ])
      setScenarios(page.items)
      setInReview(revisions.items.length > 0)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [projectId, keyword, sourceType, statusFilter, message])

  useEffect(() => {
    void reload()
  }, [reload])

  async function openDetail(scenario: ProcessScenario) {
    try {
      // 列表页只给步骤 / 关联的**计数**，详情要按 id 再拉一次。
      setDetail(await fetchProcessScenario(projectId, scenario.id))
      setDetailOpen(true)
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  async function removeScenario(scenario: ProcessScenario) {
    try {
      await deleteProcessScenario(projectId, scenario.id)
      message.success('场景已删除')
      if (detail?.id === scenario.id) setDetailOpen(false)
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  const columns = buildProcessScenarioColumns({
    canManage,
    inReview,
    onOpen: (scenario) => void openDetail(scenario),
    onEdit: (scenario) => void openDetail(scenario),
    onDelete: (scenario) => void removeScenario(scenario),
  })

  return (
    <div>
      <Space wrap style={{ marginBottom: 12 }}>
        <Input
          allowClear
          placeholder="搜索场景名称"
          style={{ width: 200 }}
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          data-testid="process-baseline-keyword"
        />
        <Select
          allowClear
          placeholder="来源类型"
          style={{ width: 140 }}
          options={SOURCE_TYPE_OPTIONS}
          value={sourceType}
          onChange={(value) => setSourceType(value)}
          data-testid="process-baseline-source-filter"
        />
        <Select
          allowClear
          placeholder="状态"
          style={{ width: 140 }}
          options={STATUS_FILTER_OPTIONS}
          value={statusFilter}
          onChange={(value) => setStatusFilter(value)}
          data-testid="process-baseline-status-filter"
        />
        <Button onClick={() => void reload()} data-testid="process-baseline-refresh-btn">
          刷新
        </Button>
        {canManage ? (
          <>
            <Button
              type="primary"
              disabled={inReview}
              onClick={() => setCreateOpen(true)}
              data-testid="process-baseline-create-btn"
            >
              新建场景
            </Button>
            <Button
              disabled={inReview}
              onClick={() => setDeriveOpen(true)}
              data-testid="process-baseline-derive-btn"
            >
              从文档反推
            </Button>
          </>
        ) : null}
        <Button onClick={() => setReviewOpen(true)} data-testid="process-baseline-review-btn">
          审核快照
        </Button>
      </Space>

      {!canManage ? (
        <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
          只有项目管理员可以新建、反推与编辑流程基线，你可以查看场景与快照。
        </Typography.Text>
      ) : null}
      {canManage && inReview ? (
        <Typography.Text type="warning" style={{ display: 'block', marginBottom: 12 }}>
          {IN_REVIEW_TIP}
        </Typography.Text>
      ) : null}

      <Table<ProcessScenario>
        rowKey="id"
        columns={columns}
        dataSource={scenarios}
        loading={loading}
        pagination={false}
        scroll={{ x: 1200 }}
        locale={{ emptyText: '还没有流程基线场景' }}
        data-testid="process-baseline-table"
        // 行锚点：e2e 用 `process-baseline-row-{id}` 定位具体某一行。
        onRow={(scenario) =>
          ({
            'data-testid': `process-baseline-row-${scenario.id}`,
          }) as React.HTMLAttributes<HTMLElement>
        }
      />

      {/* 新建与详情/编辑共用同一个抽屉组件（差别只在 mode）。 */}
      <ProcessBaselineDrawer
        open={createOpen || detailOpen}
        mode={createOpen ? 'create' : 'detail'}
        projectId={projectId}
        scenario={detail}
        canManage={canManage}
        inReview={inReview}
        onClose={() => {
          setCreateOpen(false)
          setDetailOpen(false)
        }}
        onCreated={() => void reload()}
        onUpdated={(updated) => {
          // 抽屉里的内容要跟着更新——否则保存后只读表还显示旧顺序。
          setDetail(updated)
          void reload()
        }}
      />

      <ProcessBaselineDeriveModal
        open={deriveOpen}
        projectId={projectId}
        onClose={() => setDeriveOpen(false)}
        onAdopted={() => void reload()}
      />

      <ProcessBaselineReviewDrawer
        open={reviewOpen}
        projectId={projectId}
        canManage={canManage}
        onClose={() => setReviewOpen(false)}
        onChanged={() => void reload()}
      />
    </div>
  )
}

