import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tag,
  Tree,
  Typography,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  approveBaselineReview,
  deleteBaselineRevision,
  fetchBaselineRevision,
  fetchRetention,
  listBaselineRevisions,
  rejectBaselineReview,
  submitBaselineReview,
  updateRetention,
} from '../api'
import type {
  BaselineRevision,
  BaselineRevisionDetail,
  Retention,
} from '../api'
import { errorMessage } from '../api/client'
import { formatSnapshotVersion, isValidationError } from './baselineShared'
import BaselineReviewDrawer from './BaselineReviewDrawer'

const REVISION_STATUS_META: Record<string, { label: string; color: string }> = {
  draft: { label: '草稿', color: 'default' },
  submitted: { label: '审核中', color: 'processing' },
  approved: { label: '已通过', color: 'success' },
  rejected: { label: '已驳回', color: 'error' },
}

/** 引用来源 → 中文（不暴露内部 ID，用户只关心「被什么引用」）。 */
const REF_SOURCE_LABELS: Record<string, string> = {
  baseline_function: '功能标签',
  baseline_feature_point: '功能点标签',
  incremental_analysis: '增量分析',
}

interface Props {
  projectId: number
  /** 写操作限项目管理员（后端 403 NOT_PROJECT_ADMIN）。 */
  canWrite: boolean
}

export default function ProjectBaselineSnapshots({ projectId, canWrite }: Props) {
  const [pending, setPending] = useState<BaselineRevision[]>([])
  const [approved, setApproved] = useState<BaselineRevision[]>([])
  const [retention, setRetention] = useState<Retention | null>(null)
  const [detail, setDetail] = useState<BaselineRevisionDetail | null>(null)
  const [submitOpen, setSubmitOpen] = useState(false)
  const [decision, setDecision] = useState<{
    open: boolean
    revision?: BaselineRevision
    mode: 'approve' | 'reject'
  }>({ open: false, mode: 'approve' })
  const [structureOpen, setStructureOpen] = useState(false)
  // 分点审核抽屉：独立的审核界面，不影响日常编辑树（spec §6.1）
  const [reviewRevision, setReviewRevision] = useState<BaselineRevision | null>(
    null,
  )

  const [submitForm] = Form.useForm()
  const [decisionForm] = Form.useForm()
  const [retentionForm] = Form.useForm()

  const reload = useCallback(async () => {
    const [pendingPage, approvedPage] = await Promise.all([
      listBaselineRevisions(projectId, { status: 'submitted', page_size: 200 }),
      listBaselineRevisions(projectId, { status: 'approved', page_size: 200 }),
    ])
    setPending(pendingPage.items)
    setApproved(approvedPage.items)
  }, [projectId])

  const reloadRetention = useCallback(async () => {
    setRetention(await fetchRetention(projectId))
  }, [projectId])

  useEffect(() => {
    reload().catch((error) => message.error(errorMessage(error)))
    reloadRetention().catch((error) => message.error(errorMessage(error)))
  }, [reload, reloadRetention])

  async function submitReview() {
    try {
      const values = await submitForm.validateFields()
      await submitBaselineReview(projectId, values.comment ?? null)
      message.success('已提交审核，等待他人审核')
      setSubmitOpen(false)
      submitForm.resetFields()
      await reload()
    } catch (error) {
      if (isValidationError(error)) return
      message.error(errorMessage(error))
    }
  }

  async function submitDecision() {
    if (!decision.revision) return
    try {
      const values = await decisionForm.validateFields()
      if (decision.mode === 'approve') {
        await approveBaselineReview(
          projectId,
          decision.revision.id,
          values.comment ?? null,
        )
        message.success('审核通过，生成新的基线快照')
      } else {
        await rejectBaselineReview(projectId, decision.revision.id, values.comment)
        message.success('已驳回')
      }
      setDecision({ open: false, mode: decision.mode })
      decisionForm.resetFields()
      await reload()
      await reloadRetention()
    } catch (error) {
      if (isValidationError(error)) return
      message.error(errorMessage(error))
    }
  }

  async function removeRevision(revision: BaselineRevision) {
    try {
      await deleteBaselineRevision(projectId, revision.id)
      message.success('快照已删除')
      await reload()
      await reloadRetention()
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  async function saveRetention() {
    try {
      const values = await retentionForm.validateFields()
      await updateRetention(projectId, values.max_count ?? null)
      message.success('保留策略已更新')
      await reloadRetention()
    } catch (error) {
      if (isValidationError(error)) return
      message.error(errorMessage(error))
    }
  }

  async function openStructure(revision: BaselineRevision) {
    try {
      setDetail(await fetchBaselineRevision(projectId, revision.id))
      setStructureOpen(true)
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  const pendingColumns: ColumnsType<BaselineRevision> = [
    {
      title: '提交时间',
      dataIndex: 'submitted_at',
      width: 180,
      render: (value: string | null) =>
        value ? new Date(value).toLocaleString() : '-',
    },
    { title: '模块', dataIndex: 'module_count', width: 80 },
    { title: '功能', dataIndex: 'function_count', width: 80 },
    { title: '功能点', dataIndex: 'feature_point_count', width: 90 },
    { title: '标签', dataIndex: 'label_count', width: 80 },
    {
      title: '操作',
      key: 'actions',
      width: 300,
      render: (_: unknown, revision) =>
        canWrite ? (
          <Space size={8}>
            <Button
              size="small"
              type="primary"
              data-testid={`review-items-${revision.id}`}
              onClick={() => setReviewRevision(revision)}
            >
              分点审核
            </Button>
            <Button
              size="small"
              data-testid={`approve-${revision.id}`}
              onClick={() => {
                decisionForm.resetFields()
                setDecision({ open: true, revision, mode: 'approve' })
              }}
            >
              整包通过
            </Button>
            <Button
              size="small"
              danger
              data-testid={`reject-${revision.id}`}
              onClick={() => {
                decisionForm.resetFields()
                setDecision({ open: true, revision, mode: 'reject' })
              }}
            >
              整包驳回
            </Button>
          </Space>
        ) : (
          <Typography.Text type="secondary">等待项目管理员审核</Typography.Text>
        ),
    },
  ]

  const approvedColumns: ColumnsType<BaselineRevision> = [
    {
      title: '版本',
      dataIndex: 'version_no',
      width: 90,
      render: (value: number | null) => formatSnapshotVersion(value),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (status: string) => (
        <Tag color={REVISION_STATUS_META[status]?.color ?? 'default'}>
          {REVISION_STATUS_META[status]?.label ?? status}
        </Tag>
      ),
    },
    { title: '模块', dataIndex: 'module_count', width: 80 },
    { title: '功能', dataIndex: 'function_count', width: 80 },
    { title: '功能点', dataIndex: 'feature_point_count', width: 90 },
    { title: '标签', dataIndex: 'label_count', width: 80 },
    {
      title: '审核时间',
      dataIndex: 'reviewed_at',
      width: 180,
      render: (value: string | null) =>
        value ? new Date(value).toLocaleString() : '-',
    },
    {
      title: '操作',
      key: 'actions',
      width: 160,
      render: (_: unknown, revision) => (
        <Space size={8}>
          <Button
            size="small"
            data-testid={`view-structure-${revision.id}`}
            onClick={() => openStructure(revision)}
          >
            查看结构
          </Button>
          {canWrite && (
            <Popconfirm
              title="删除该快照？"
              description="被标签引用的快照不能删除。"
              okText="删除"
              cancelText="取消"
              onConfirm={() => removeRevision(revision)}
            >
              <Button size="small" danger>
                删除
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div>
      {retention?.warnings?.map((warning) => (
        <Alert
          key={warning}
          type="warning"
          showIcon
          message={warning}
          style={{ marginBottom: 12 }}
        />
      ))}

      <Card
        title="基线快照"
        size="small"
        extra={
          canWrite && (
            <Button
              type="primary"
              data-testid="submit-review"
              onClick={() => {
                submitForm.resetFields()
                setSubmitOpen(true)
              }}
            >
              提交审核
            </Button>
          )
        }
      >
        {pending.length > 0 && (
          <>
            <Typography.Title level={5} style={{ marginTop: 0 }}>
              审核中
            </Typography.Title>
            <Table
              size="small"
              rowKey="id"
              columns={pendingColumns}
              dataSource={pending}
              pagination={false}
              style={{ marginBottom: 16 }}
            />
          </>
        )}

        <Typography.Title level={5} style={{ marginTop: 0 }}>
          审核通过
        </Typography.Title>
        <Table
          size="small"
          rowKey="id"
          columns={approvedColumns}
          dataSource={approved}
          pagination={false}
          locale={{ emptyText: '还没有审核通过的基线快照' }}
        />
      </Card>

      <Card title="保留策略" size="small" style={{ marginTop: 16 }}>
        {retention && (
          <Descriptions size="small" column={3} style={{ marginBottom: 12 }}>
            <Descriptions.Item label="当前快照数">{retention.snapshot_count}</Descriptions.Item>
            <Descriptions.Item label="保留上限">
              {retention.max_count ?? '未启用'}
            </Descriptions.Item>
            <Descriptions.Item label="待清理候选">
              {retention.candidates.length}
            </Descriptions.Item>
          </Descriptions>
        )}

        {canWrite && (
          <Form form={retentionForm} layout="inline" style={{ marginBottom: 12 }}>
            <Form.Item
              name="max_count"
              label="保留份数"
              tooltip="留空表示不限制；超过上限的最旧快照进入待清理候选，但不会自动删除"
            >
              <InputNumber min={1} max={100} placeholder="不限制" style={{ width: 140 }} />
            </Form.Item>
            <Form.Item>
              <Button type="primary" data-testid="save-retention" onClick={saveRetention}>
                保存
              </Button>
            </Form.Item>
          </Form>
        )}

        {retention && retention.candidates.length > 0 && (
          <Table
            size="small"
            rowKey="id"
            pagination={false}
            dataSource={retention.candidates}
            columns={[
              {
                title: '版本',
                dataIndex: 'version_no',
                width: 90,
                render: (value: number) => formatSnapshotVersion(value),
              },
              {
                title: '引用数',
                dataIndex: 'referenced_count',
                width: 90,
              },
              {
                title: '引用来源',
                dataIndex: 'refs',
                render: (refs: Array<{ target_id: number; target_name?: string; source_type: string }>) =>
                  refs.length ? (
                    <Space size={4} wrap>
                      {refs.map((ref) => (
                        <Tag key={`${ref.source_type}-${ref.target_id}`}>
                          {REF_SOURCE_LABELS[ref.source_type] ?? '功能基线标签'} ·{' '}
                          {ref.target_name ?? '已删除的对象'}
                        </Tag>
                      ))}
                    </Space>
                  ) : (
                    <Typography.Text type="secondary">无</Typography.Text>
                  ),
              },
            ]}
          />
        )}
      </Card>

      {/* 提交审核 */}
      <Modal
        title="提交基线审核"
        open={submitOpen}
        onCancel={() => setSubmitOpen(false)}
        onOk={submitReview}
        okText="提交"
        cancelText="取消"
        destroyOnHidden
      >
        <Typography.Paragraph type="secondary">
          提交后会冻结当前的结构与标签快照，需由另一位项目管理员审核通过才生效。
        </Typography.Paragraph>
        <Form form={submitForm} layout="vertical">
          <Form.Item name="comment" label="提交说明">
            <Input.TextArea rows={3} placeholder="选填" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 审核决定 */}
      <Modal
        title={decision.mode === 'approve' ? '审核通过' : '驳回'}
        open={decision.open}
        onCancel={() => setDecision({ open: false, mode: decision.mode })}
        onOk={submitDecision}
        okText={decision.mode === 'approve' ? '通过' : '驳回'}
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={decisionForm} layout="vertical">
          <Form.Item
            name="comment"
            label={decision.mode === 'approve' ? '审核意见' : '驳回意见'}
            rules={
              decision.mode === 'reject'
                ? [{ required: true, message: '驳回必须填写意见' }]
                : []
            }
          >
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 冻结的结构 */}
      <Modal
        title={
          detail && detail.version_no !== null
            ? `基线结构 ${formatSnapshotVersion(detail.version_no)}`
            : '基线结构'
        }
        open={structureOpen}
        onCancel={() => setStructureOpen(false)}
        footer={null}
        width={640}
      >
        {detail?.structure?.length ? (
          <Tree
            treeData={detail.structure.map((module) => ({
              key: `m-${module.id}`,
              title: module.name,
              children: module.functions.map((fn) => ({
                key: `f-${fn.id}`,
                title: fn.name,
                children: fn.feature_points.map((point) => ({
                  key: `p-${point.id}`,
                  title: point.name,
                })),
              })),
            }))}
            defaultExpandAll
          />
        ) : (
          <Typography.Text type="secondary">该快照没有结构数据。</Typography.Text>
        )}
      </Modal>

      {/* 分点审核抽屉：勾选部分通过、逐条驳回 */}
      <BaselineReviewDrawer
        open={reviewRevision !== null}
        projectId={projectId}
        revision={reviewRevision}
        onClose={() => setReviewRevision(null)}
        onApproved={() => {
          void reload()
          void reloadRetention()
        }}
      />
    </div>
  )
}
