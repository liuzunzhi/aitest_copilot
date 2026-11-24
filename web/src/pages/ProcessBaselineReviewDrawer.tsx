import { useCallback, useEffect, useState } from 'react'
import {
  App as AntdApp,
  Button,
  Drawer,
  Input,
  Popconfirm,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'

import {
  approveProcessReview,
  fetchProcessRevision,
  listProcessRevisions,
  rejectProcessReview,
  submitProcessReview,
} from '../api'
import type { ProcessRevision, ProcessRevisionDetail } from '../api'
import { errorMessage } from '../api/client'
import { formatProcessVersion, revisionStatusText } from './processBaselineMeta'

interface Props {
  open: boolean
  projectId: number
  /** 写操作限项目管理员（后端 403 NOT_PROJECT_ADMIN）。 */
  canManage: boolean
  onClose: () => void
  /** 快照变化后回传（父级据此刷新场景表的审核期锁定状态）。 */
  onChanged: () => void
}

/** 快照内容里的一个场景（`draft_snapshot` / `structure_json` 的 JSON 结构）。 */
interface SnapshotScenario {
  id: number
  name: string
  description: string | null
  precondition: string | null
  source_type: string
  status: string
  version_no: number
  steps: Array<{ step_no: number; action: string; expected: string }>
  links: Array<{ target_type: string; target_id: number; target_name: string }>
}

/**
 * 流程基线快照抽屉：快照列表 + 提交 / 通过 / 驳回 + 快照内容。
 *
 * **「提交即冻结」**是本期设计的核心：
 * 提交的那一刻把当前全部在用场景冻结进 `draft_snapshot`，
 * 审核通过时**原样转正**为 `structure_json`——审核人看到的与最终冻结的
 * **逐字节相同**。所以这里展示的快照内容就是冻结的那一份。
 *
 * 驳回**意见必填**（后端 400 `REVIEW_COMMENT_REQUIRED`），
 * 前端用 `required` 提前拦一道。
 */
export default function ProcessBaselineReviewDrawer({
  open,
  projectId,
  canManage,
  onClose,
  onChanged,
}: Props) {
  const { message } = AntdApp.useApp()
  const [revisions, setRevisions] = useState<ProcessRevision[]>([])
  const [comment, setComment] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [detail, setDetail] = useState<ProcessRevisionDetail | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [loading, setLoading] = useState(false)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const page = await listProcessRevisions(projectId, { status: 'all', page_size: 200 })
      setRevisions(page.items)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [projectId, message])

  useEffect(() => {
    if (!open) return
    setComment('')
    void reload()
  }, [open, reload])

  async function submit() {
    setSubmitting(true)
    try {
      await submitProcessReview(projectId, comment.trim() || null)
      message.success('已提交审核，内容已冻结')
      setComment('')
      await reload()
      onChanged()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setSubmitting(false)
    }
  }

  async function approve(revision: ProcessRevision) {
    setSubmitting(true)
    try {
      await approveProcessReview(projectId, revision.id, comment.trim() || null)
      message.success('审核通过，已生成新快照')
      setComment('')
      await reload()
      onChanged()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setSubmitting(false)
    }
  }

  async function reject(revision: ProcessRevision) {
    const text = comment.trim()
    if (!text) {
      message.warning('驳回必须填写意见')
      return
    }
    setSubmitting(true)
    try {
      await rejectProcessReview(projectId, revision.id, text)
      message.success('已驳回')
      setComment('')
      await reload()
      onChanged()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setSubmitting(false)
    }
  }

  async function openSnapshot(revision: ProcessRevision) {
    try {
      setDetail(await fetchProcessRevision(projectId, revision.id))
      setDetailOpen(true)
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  const columns: ColumnsType<ProcessRevision> = [
    {
      title: '版本',
      dataIndex: 'version_no',
      width: 100,
      render: (value: number | null) => (
        <span data-testid={`process-baseline-review-version-${value ?? 'none'}`}>
          {formatProcessVersion(value)}
        </span>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (status: string, revision) => {
        const meta = revisionStatusText(status)
        return (
          <span data-testid={`process-baseline-review-status-${revision.id}`}>
            <Tag color={meta.color}>{meta.label}</Tag>
          </span>
        )
      },
    },
    {
      title: '场景',
      dataIndex: 'scenario_count',
      width: 80,
    },
    {
      title: '步骤',
      dataIndex: 'step_count',
      width: 80,
    },
    {
      title: '关联',
      dataIndex: 'link_count',
      width: 80,
    },
    {
      title: '提交时间',
      dataIndex: 'submitted_at',
      width: 180,
      render: (value: string | null) =>
        value ? new Date(value).toLocaleString() : '—',
    },
    {
      title: '审核时间',
      dataIndex: 'reviewed_at',
      width: 180,
      render: (value: string | null) =>
        value ? new Date(value).toLocaleString() : '—',
    },
    {
      title: '意见',
      dataIndex: 'review_comment',
      render: (value: string | null) => value || '—',
    },
    {
      title: '操作',
      key: 'actions',
      width: 190,
      render: (_: unknown, revision) => (
        <Space size={4}>
          <Button
            size="small"
            onClick={() => void openSnapshot(revision)}
            data-testid={`process-baseline-review-view-btn-${revision.id}`}
          >
            查看快照
          </Button>
          {canManage && revision.status === 'submitted' ? (
            <>
              <Button
                size="small"
                type="primary"
                onClick={() => void approve(revision)}
                data-testid={`process-baseline-review-approve-btn-${revision.id}`}
              >
                通过
              </Button>
              <Popconfirm
                title="驳回该快照？"
                description="驳回必须填写意见，驳回后场景编辑解锁。"
                okText="驳回"
                cancelText="取消"
                onConfirm={() => void reject(revision)}
              >
                <Button
                  size="small"
                  danger
                  data-testid={`process-baseline-review-reject-btn-${revision.id}`}
                >
                  驳回
                </Button>
              </Popconfirm>
            </>
          ) : null}
        </Space>
      ),
    },
  ]

  return (
    <Drawer
      title="流程基线审核快照"
      width={1000}
      open={open}
      onClose={onClose}
    >
      <Space
        direction="vertical"
        size={16}
        style={{ width: '100%' }}
        data-testid="process-baseline-review-drawer"
      >
        {canManage ? (
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            <Input.TextArea
              rows={2}
              maxLength={500}
              showCount
              placeholder="审核意见（驳回时必填）"
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              data-testid="process-baseline-review-comment-input"
            />
            <Button
              type="primary"
              loading={submitting}
              onClick={() => void submit()}
              data-testid="process-baseline-review-submit-btn"
            >
              提交审核
            </Button>
          </Space>
        ) : (
          <Typography.Text type="secondary">
            只有项目管理员可以提交审核与审核结论，你可以查看快照。
          </Typography.Text>
        )}

        <Table<ProcessRevision>
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={revisions}
          loading={loading}
          pagination={false}
          scroll={{ x: 1000 }}
          locale={{ emptyText: '还没有流程基线快照' }}
          data-testid="process-baseline-review-table"
        />
      </Space>

      <Drawer
        title={
          detail && detail.version_no !== null
            ? `流程基线快照 ${formatProcessVersion(detail.version_no)}`
            : '流程基线快照'
        }
        width={720}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        data-testid="process-baseline-snapshot-drawer"
      >
        {detail ? (
          <Space
            direction="vertical"
            size={12}
            style={{ width: '100%' }}
            data-testid="process-baseline-snapshot-content"
          >
            {(() => {
              // **两份原文逐字节相同**——展示的是提交时冻结的那一份。
              const raw = detail.structure_json ?? detail.draft_snapshot ?? '{}'
              let scenarios: SnapshotScenario[] = []
              try {
                const parsed = JSON.parse(raw) as { scenarios?: SnapshotScenario[] }
                scenarios = parsed.scenarios ?? []
              } catch {
                scenarios = []
              }
              return scenarios.map((scenario, index) => (
                <div
                  key={scenario.id ?? index}
                  data-testid={`process-baseline-snapshot-scenario-${index}`}
                >
                  <Typography.Title level={5} style={{ marginTop: 0 }}>
                    {scenario.name}
                  </Typography.Title>
                  <Typography.Paragraph type="secondary">
                    {scenario.description || '—'}
                  </Typography.Paragraph>
                  <Space wrap>
                    <Tag>来源：{scenario.source_type === 'manual' ? '手工添加' : '文档解析'}</Tag>
                    <Tag>步骤 {scenario.steps.length}</Tag>
                    <Tag>关联 {scenario.links.length}</Tag>
                  </Space>
                  <Table
                    rowKey="step_no"
                    size="small"
                    pagination={false}
                    columns={[
                      { title: '序号', dataIndex: 'step_no', width: 64 },
                      { title: '操作步骤', dataIndex: 'action' },
                      { title: '预期结果', dataIndex: 'expected' },
                    ]}
                    dataSource={scenario.steps}
                  />
                  {scenario.links.length ? (
                    <Space wrap style={{ marginTop: 8 }}>
                      {scenario.links.map((link) => (
                        <Tag key={`${link.target_type}-${link.target_id}`}>
                          {link.target_type === 'function' ? '功能' : '功能点'} ·{' '}
                          {link.target_name}
                        </Tag>
                      ))}
                    </Space>
                  ) : null}
                </div>
              ))
            })()}
          </Space>
        ) : null}
      </Drawer>
    </Drawer>
  )
}
