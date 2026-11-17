import { useCallback, useEffect, useState } from 'react'
import { App as AntdApp, Alert, Button, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'

import { listAppliedLabels, runIncrementalApply } from '../api'
import type { AppliedLabel, ApplyResult, ClearReason, IncrementalAnalysis } from '../api'
import { errorMessage } from '../api/client'
import { CLEAR_REASON_META } from './baselineMeta'
import { TARGET_LABELS, labelTag } from './incrementalMeta'

interface Props {
  projectId: number
  analysis: IncrementalAnalysis
  /** 触发产出限项目管理员（后端 403 NOT_PROJECT_ADMIN）。 */
  canWrite: boolean
  /** 产出后刷新父级持有的分析详情。 */
  onChanged: () => void
}

const APPLY_STATUS_META: Record<string, { label: string; color: string }> = {
  running: { label: '执行中', color: 'processing' },
  succeeded: { label: '成功', color: 'success' },
  failed: { label: '失败', color: 'error' },
}

function applyStatusTag(status: ApplyResult['apply_status']) {
  if (!status) return <Tag color="default">未应用</Tag>
  const meta = APPLY_STATUS_META[status] ?? { label: status, color: 'default' }
  return <Tag color={meta.color}>{meta.label}</Tag>
}

/** 产出区块：状态 + 触发 + 产出标签表 + 「结论已全部撤销」提示。 */
export default function IncrementalApply({ projectId, analysis, canWrite, onChanged }: Props) {
  const { message } = AntdApp.useApp()
  const [result, setResult] = useState<ApplyResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [applying, setApplying] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      setResult(await listAppliedLabels(projectId, analysis.id))
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [projectId, analysis.id, message])

  useEffect(() => {
    void reload()
  }, [reload])

  const stats = result?.apply_stats
  const canTrigger = canWrite && analysis.second_pass_status === 'succeeded'

  async function trigger() {
    setApplying(true)
    setFailure(null)
    try {
      const fresh = await runIncrementalApply(projectId, analysis.id)
      setResult(fresh)
      message.success(`产出完成：写入 ${fresh.apply_stats?.label_count ?? 0} 条标签`)
      onChanged()
    } catch (error) {
      setFailure(errorMessage(error))
      message.error(errorMessage(error))
      // 后端失败时已把 apply_status 置 failed，刷新让状态可见
      await reload()
      onChanged()
    } finally {
      setApplying(false)
    }
  }

  const columns: ColumnsType<AppliedLabel> = [
    {
      title: '目标',
      key: 'target',
      render: (_: unknown, row) => (
        <span>
          {row.target_name ?? '—'}
          <Typography.Text type="secondary">
            {' '}
            {TARGET_LABELS[row.target_type] ?? row.target_type} #{row.target_id}
          </Typography.Text>
        </span>
      ),
    },
    {
      title: '标签',
      dataIndex: 'label_type',
      width: 90,
      render: (value: string) => labelTag(value),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 170,
      render: (value: string, row) =>
        value === 'active' ? (
          <Tag color="success">生效</Tag>
        ) : (
          <Tag>
            已清除 · {CLEAR_REASON_META[(row.clear_reason ?? 'other') as ClearReason] ?? row.clear_reason}
          </Tag>
        ),
    },
    {
      title: '清除记录',
      key: 'cleared',
      width: 220,
      render: (_: unknown, row) =>
        row.cleared_at ? (
          <Typography.Text type="secondary">
            {row.cleared_by === null ? '—' : `用户 #${row.cleared_by}`} ·{' '}
            {new Date(row.cleared_at).toLocaleString()}
          </Typography.Text>
        ) : (
          '—'
        ),
    },
    {
      title: '快照',
      dataIndex: 'revision_id',
      width: 90,
      render: (value: number) => `#${value}`,
    },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <div>
        <Space size={12} wrap>
          <Typography.Text strong>应用产出</Typography.Text>
          {applyStatusTag(result?.apply_status ?? null)}
          {canTrigger ? (
            <Button
              type="primary"
              size="small"
              loading={applying}
              data-testid="incremental-apply-btn"
              onClick={trigger}
            >
              {result?.apply_status ? '重跑产出' : '应用产出'}
            </Button>
          ) : null}
        </Space>
        <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
          把第二遍的变更 / 受影响结论落成基线标签，并准备一份待审核快照；审核通过仍走基线管理流程。
        </Typography.Paragraph>
        {!canWrite ? (
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            只有项目管理员可以应用产出，你可以查看产出标签。
          </Typography.Paragraph>
        ) : null}
        {canWrite && analysis.second_pass_status !== 'succeeded' ? (
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            第二遍成功后才能应用产出。
          </Typography.Paragraph>
        ) : null}
      </div>

      {failure ? (
        <Alert
          type="error"
          showIcon
          data-testid="incremental-apply-failure-alert"
          message="产出失败"
          description={failure}
        />
      ) : null}

      {result?.revoked ? (
        <Alert
          type="warning"
          showIcon
          data-testid="incremental-apply-revoked"
          message="结论已全部撤销"
          description="本次产出的标签已全部被人工清除，记录保留可追溯。"
        />
      ) : null}

      {stats ? (
        <Typography.Text type="secondary" data-testid="incremental-apply-stats">
          产出 {stats.label_count} 条（变更 {stats.changed_count} / 受影响{' '}
          {stats.affected_count}）· 跳过目标缺失 {stats.skipped_missing_count} · 新增跳过{' '}
          {stats.skipped_new_count} · 未变更 {stats.unchanged_count} · 冲突落标{' '}
          {stats.conflict_label_count} · 快照 #{stats.revision_id}（{stats.revision_status}）
        </Typography.Text>
      ) : null}

      <Table<AppliedLabel>
        size="small"
        rowKey="id"
        columns={columns}
        dataSource={result?.labels ?? []}
        pagination={false}
        loading={loading}
        locale={{ emptyText: '还没有产出标签' }}
        data-testid="incremental-applied-label-table"
      />
    </Space>
  )
}
