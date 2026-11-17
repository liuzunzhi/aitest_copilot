import { useCallback, useEffect, useState } from 'react'
import { App as AntdApp, Alert, Button, Form, Modal, Radio, Space, Table, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'

import {
  listIncrementalConflicts,
  listIncrementalDecisions,
  resolveIncrementalConflict,
  runIncrementalSecondPass,
} from '../api'
import type {
  DecisionType,
  IncrementalAnalysis,
  IncrementalConflict,
  IncrementalDecision,
} from '../api'
import { errorMessage } from '../api/client'
import {
  TARGET_LABELS,
  conflictStatusTag,
  conflictTypeTag,
  labelTag,
  secondPassStatusTag,
} from './incrementalMeta'

interface Props {
  projectId: number
  analysis: IncrementalAnalysis
  /** 触发第二遍与裁决限项目管理员（后端 403 NOT_PROJECT_ADMIN）。 */
  canWrite: boolean
  /** 父组件刷新分析详情用。 */
  onChanged: () => void
}

const LABEL_OPTIONS = [
  { value: 'changed', label: '变更' },
  { value: 'affected', label: '受影响' },
  { value: 'unchanged', label: '未变更' },
]

/** 第二遍区块：状态 + 触发 + 裁决表 + 冲突队列（确认 / 驳回）。 */
export default function IncrementalSecondPass({ projectId, analysis, canWrite, onChanged }: Props) {
  const { message } = AntdApp.useApp()
  const [decisions, setDecisions] = useState<IncrementalDecision[]>([])
  const [conflicts, setConflicts] = useState<IncrementalConflict[]>([])
  const [loading, setLoading] = useState(false)
  const [running, setRunning] = useState(false)
  const [resolving, setResolving] = useState(false)
  const [resolveTarget, setResolveTarget] = useState<IncrementalConflict | null>(null)
  const [resolveForm] = Form.useForm<{ label_type: DecisionType }>()

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const [decisionPage, conflictPage] = await Promise.all([
        listIncrementalDecisions(projectId, analysis.id, { page_size: 200 }),
        listIncrementalConflicts(projectId, analysis.id, { page_size: 200 }),
      ])
      setDecisions(decisionPage.items)
      setConflicts(conflictPage.items)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [projectId, analysis.id, message])

  useEffect(() => {
    void reload()
  }, [reload])

  const stats = analysis.second_pass_stats
  const pendingCount = conflicts.filter((item) => item.status === 'pending').length
  // 有待裁决冲突时禁止重跑（后端也会 409）
  const blocked = pendingCount > 0
  const canTrigger = canWrite && analysis.status === 'succeeded'

  async function trigger() {
    setRunning(true)
    try {
      const fresh = await runIncrementalSecondPass(projectId, analysis.id)
      message.success(
        fresh.second_pass_status === 'succeeded'
          ? `第二遍完成：${fresh.second_pass_stats?.decision_count ?? 0} 条裁决、${fresh.second_pass_stats?.conflict_count ?? 0} 条冲突`
          : '第二遍未成功，请查看失败原因',
      )
      await reload()
      onChanged()
    } catch (error) {
      message.error(errorMessage(error))
      onChanged()
    } finally {
      setRunning(false)
    }
  }

  function openResolve(conflict: IncrementalConflict) {
    setResolveTarget(conflict)
    resolveForm.resetFields()
  }

  async function submitResolve(values: { label_type: DecisionType }) {
    if (!resolveTarget) return
    setResolving(true)
    try {
      await resolveIncrementalConflict(projectId, analysis.id, resolveTarget.id, {
        decision: 'confirmed',
        label_type: values.label_type,
      })
      message.success('已确认该冲突')
      setResolveTarget(null)
      await reload()
      onChanged()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setResolving(false)
    }
  }

  async function rejectResolve(conflict: IncrementalConflict) {
    setResolving(true)
    try {
      await resolveIncrementalConflict(projectId, analysis.id, conflict.id, {
        decision: 'rejected',
      })
      message.success('已驳回该冲突')
      await reload()
      onChanged()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setResolving(false)
    }
  }

  const decisionColumns: ColumnsType<IncrementalDecision> = [
    {
      title: '目标',
      key: 'target',
      render: (_: unknown, row) => (
        <span>
          {row.target_name}
          <Typography.Text type="secondary">
            {' '}
            {TARGET_LABELS[row.target_type] ?? row.target_type} #{row.target_id}
          </Typography.Text>
        </span>
      ),
    },
    {
      title: '裁决',
      dataIndex: 'decision',
      width: 100,
      render: (value: string) => labelTag(value),
    },
    {
      title: '置信度',
      dataIndex: 'confidence',
      width: 90,
      render: (value: number | null) => (value === null ? '—' : value.toFixed(2)),
    },
    { title: '依据', dataIndex: 'rationale', render: (value: string | null) => value ?? '—' },
  ]

  const conflictColumns: ColumnsType<IncrementalConflict> = [
    {
      title: '目标',
      key: 'target',
      render: (_: unknown, row) => (
        <span>
          {row.target_name}
          <Typography.Text type="secondary">
            {' '}
            {TARGET_LABELS[row.target_type] ?? row.target_type}
            {row.target_id === null ? '' : ` #${row.target_id}`}
          </Typography.Text>
        </span>
      ),
    },
    {
      title: '类型',
      dataIndex: 'conflict_type',
      width: 110,
      render: (value: string) => conflictTypeTag(value),
    },
    {
      title: '候选',
      key: 'candidates',
      render: (_: unknown, row) => (
        <Space size={4} wrap>
          {row.candidates.map((candidate, index) => (
            <span key={`${candidate.source}-${index}`} data-testid="incremental-conflict-candidate">
              {labelTag(candidate.label_type)}
              <Typography.Text type="secondary"> {candidate.source}</Typography.Text>
            </span>
          ))}
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (value: string) => conflictStatusTag(value),
    },
    {
      title: '操作',
      key: 'actions',
      width: 140,
      render: (_: unknown, row) =>
        row.status !== 'pending' || !canWrite ? (
          <Typography.Text type="secondary">—</Typography.Text>
        ) : (
          <Space size={4}>
            <Button
              size="small"
              type="primary"
              data-testid={`incremental-conflict-resolve-btn-${row.id}`}
              onClick={() => openResolve(row)}
            >
              确认
            </Button>
            <Button
              size="small"
              danger
              data-testid={`incremental-conflict-reject-btn-${row.id}`}
              onClick={() => rejectResolve(row)}
            >
              驳回
            </Button>
          </Space>
        ),
    },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <div>
        <Space size={12} wrap>
          <Typography.Text strong>第二遍（全局裁决）</Typography.Text>
          {secondPassStatusTag(analysis.second_pass_status)}
          {canTrigger ? (
            <Button
              type="primary"
              size="small"
              loading={running}
              disabled={blocked}
              data-testid="incremental-second-pass-btn"
              onClick={trigger}
            >
              {analysis.second_pass_status ? '重跑第二遍' : '触发第二遍'}
            </Button>
          ) : null}
        </Space>
        {blocked ? (
          <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
            有 {pendingCount} 条冲突待裁决，请先完成裁决再重跑第二遍。
          </Typography.Paragraph>
        ) : null}
        {!canWrite ? (
          <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
            只有项目管理员可以触发第二遍与裁决冲突，你可以查看裁决与冲突。
          </Typography.Paragraph>
        ) : null}
      </div>

      {analysis.second_pass_status === 'failed' ? (
        <Alert
          type="error"
          showIcon
          data-testid="incremental-second-pass-failure-alert"
          message={analysis.second_pass_error_message ?? analysis.second_pass_error_code ?? '第二遍失败'}
          description="第一遍结论已保留，可先排查模板或模型返回后重跑。"
        />
      ) : null}

      {stats ? (
        <Typography.Text type="secondary" data-testid="incremental-second-pass-stats">
          参与目标 {stats.point_count} · 裁决 {stats.decision_count} · 新增 {stats.new_count} ·
          冲突 {stats.conflict_count} · 传播 {stats.propagated_count} · 引用边 {stats.chapter_link_count} ·
          供应商 {stats.provider}
        </Typography.Text>
      ) : null}

      <div>
        <Typography.Title level={5} style={{ marginTop: 0 }}>
          裁决结果
        </Typography.Title>
        <Table<IncrementalDecision>
          size="small"
          rowKey="id"
          columns={decisionColumns}
          dataSource={decisions}
          pagination={false}
          loading={loading}
          locale={{ emptyText: '本次第二遍没有无争议裁决' }}
          data-testid="incremental-decision-table"
        />
      </div>

      <div>
        <Typography.Title level={5} style={{ marginTop: 0 }}>
          待人工裁决
        </Typography.Title>
        <Table<IncrementalConflict>
          size="small"
          rowKey="id"
          columns={conflictColumns}
          dataSource={conflicts}
          pagination={false}
          loading={loading}
          locale={{ emptyText: '没有待裁决的冲突' }}
          data-testid="incremental-conflict-table"
        />
      </div>

      <Modal
        open={resolveTarget !== null}
        title="确认冲突"
        okText="确认"
        cancelText="取消"
        confirmLoading={resolving}
        okButtonProps={{ 'data-testid': 'incremental-conflict-confirm-submit' }}
        onCancel={() => setResolveTarget(null)}
        onOk={() => resolveForm.submit()}
      >
        <Typography.Paragraph type="secondary">
          {resolveTarget ? `${resolveTarget.target_name}：请选择最终标签` : ''}
        </Typography.Paragraph>
        <Form form={resolveForm} layout="vertical" onFinish={submitResolve}>
          <Form.Item
            name="label_type"
            label="最终标签"
            rules={[{ required: true, message: '请选择最终标签' }]}
          >
            <Radio.Group data-testid="incremental-conflict-label-group">
              {LABEL_OPTIONS.map((option) => (
                <Radio key={option.value} value={option.value}>
                  {option.label}
                </Radio>
              ))}
            </Radio.Group>
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  )
}
