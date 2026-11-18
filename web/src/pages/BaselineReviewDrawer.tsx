/** 分点审核抽屉：待审树 + 勾选通过 + 逐条驳回 + 保存草稿 / 提交结论。 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Space,
  Tag,
  Tree,
  Typography,
  message,
} from 'antd'
import {
  approveBaselineReview,
  decideBaselineReview,
  fetchBaselineReviewTree,
} from '../api'
import type {
  BaselineReviewItemDecision,
  BaselineReviewTree,
  BaselineReviewTreeNode,
  BaselineRevision,
  ReviewDecisionValue,
  ReviewEntityType,
} from '../api'
import { errorMessage } from '../api/client'
import {
  buildReviewTreeData,
  flattenReviewTree,
  resolveDecision,
  reviewNodeKey,
} from './baselineReviewNodes'
import type { ReviewNodeDecision } from './baselineReviewNodes'

interface Props {
  open: boolean
  projectId: number
  revision: BaselineRevision | null
  onClose: () => void
  /** 审核通过后通知父组件刷新快照列表。 */
  onApproved: () => void
}

export default function BaselineReviewDrawer({
  open,
  projectId,
  revision,
  onClose,
  onApproved,
}: Props) {
  const [tree, setTree] = useState<BaselineReviewTree | null>(null)
  const [decisions, setDecisions] = useState<Record<string, ReviewNodeDecision>>(
    {},
  )
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [rejectTarget, setRejectTarget] =
    useState<BaselineReviewTreeNode | null>(null)
  const [rejectForm] = Form.useForm()

  const revisionId = revision?.id ?? null

  const load = useCallback(async () => {
    if (!revisionId) return
    setLoading(true)
    try {
      setTree(await fetchBaselineReviewTree(projectId, revisionId))
      setDecisions({})
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [projectId, revisionId])

  useEffect(() => {
    if (!open) return
    void load()
  }, [open, load])

  const nodes = useMemo(
    () => flattenReviewTree(tree?.tree ?? []),
    [tree],
  )

  const stats = useMemo(() => {
    const result: Record<string, number> = {
      total: nodes.length,
      approved: 0,
      rejected: 0,
      pending: 0,
    }
    for (const node of nodes) {
      result[resolveDecision(node, decisions).decision] += 1
    }
    return {
      total: result.total,
      approved: result.approved,
      rejected: result.rejected,
      pending: result.pending,
    }
  }, [decisions, nodes])

  const checkedKeys = useMemo(
    () =>
      nodes
        .filter(
          (node) => resolveDecision(node, decisions).decision === 'approved',
        )
        .map((node) => reviewNodeKey(node.entity_type, node.entity_id)),
    [decisions, nodes],
  )

  const handleCheck = useCallback(
    (checkedValue: unknown) => {
      const keys = Array.isArray(checkedValue)
        ? checkedValue
        : ((checkedValue as { checked: unknown[] })?.checked ?? [])
      const checked = new Set(keys.map(String))
      setDecisions((prev) => {
        const next = { ...prev }
        for (const node of nodes) {
          const key = reviewNodeKey(node.entity_type, node.entity_id)
          const current = resolveDecision(node, prev).decision
          if (checked.has(key)) {
            if (current !== 'approved') {
              next[key] = { decision: 'approved', comment: null }
            }
          } else if (current === 'approved') {
            next[key] = { decision: 'pending', comment: null }
          }
        }
        return next
      })
    },
    [nodes],
  )

  const selectAll = useCallback(() => {
    setDecisions(
      Object.fromEntries(
        nodes.map((node) => [
          reviewNodeKey(node.entity_type, node.entity_id),
          { decision: 'approved' as ReviewDecisionValue, comment: null },
        ]),
      ),
    )
  }, [nodes])

  const clearAll = useCallback(() => {
    setDecisions(
      Object.fromEntries(
        nodes.map((node) => [
          reviewNodeKey(node.entity_type, node.entity_id),
          { decision: 'pending' as ReviewDecisionValue, comment: null },
        ]),
      ),
    )
  }, [nodes])

  const applyReject = useCallback(
    (comment: string) => {
      if (!rejectTarget) return
      const target = rejectTarget
      const targetKey = reviewNodeKey(target.entity_type, target.entity_id)
      const subtree = flattenReviewTree([target])
      setDecisions((prev) => {
        const next = { ...prev }
        for (const node of subtree) {
          const key = reviewNodeKey(node.entity_type, node.entity_id)
          if (key === targetKey) {
            next[key] = { decision: 'rejected', comment }
          } else if (resolveDecision(node, prev).decision === 'approved') {
            next[key] = { decision: 'pending', comment: null }
          }
        }
        return next
      })
      setRejectTarget(null)
      rejectForm.resetFields()
    },
    [rejectForm, rejectTarget],
  )

  const toItems = useCallback((): BaselineReviewItemDecision[] => {
    return nodes.flatMap((node): BaselineReviewItemDecision[] => {
      const key = reviewNodeKey(node.entity_type, node.entity_id)
      const override = decisions[key]
      if (!override) return []
      return [
        {
          entity_type: node.entity_type as ReviewEntityType,
          entity_id: node.entity_id,
          decision: override.decision,
          comment: override.comment ?? null,
        },
      ]
    })
  }, [decisions, nodes])

  const saveDraft = useCallback(async () => {
    if (!revisionId) return
    const items = toItems()
    if (!items.length) {
      message.info('还没有任何决策')
      return
    }
    setSaving(true)
    try {
      const result = await decideBaselineReview(projectId, revisionId, items)
      message.success(
        `决策已保存：通过 ${result.stats.approved}、驳回 ${result.stats.rejected}`,
      )
      await load()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setSaving(false)
    }
  }, [load, projectId, revisionId, toItems])

  const submitConclusion = useCallback(() => {
    if (!revisionId) return
    const items = toItems()
    if (!items.length) {
      message.warning('请先勾选要通过的节点，或单独驳回不通过的节点')
      return
    }
    Modal.confirm({
      title: '提交审核结论？',
      content: `通过 ${stats.approved} 项、驳回 ${stats.rejected} 项、未决策 ${stats.pending} 项（未决策按未通过处理）。提交后生成新的基线快照。`,
      okText: '提交结论',
      cancelText: '取消',
      onOk: async () => {
        setSubmitting(true)
        try {
          await approveBaselineReview(projectId, revisionId, null, items)
          message.success('审核通过，已生成基线快照')
          onApproved()
          onClose()
        } catch (error) {
          message.error(errorMessage(error))
        } finally {
          setSubmitting(false)
        }
      },
    })
  }, [onApproved, onClose, projectId, revisionId, stats, toItems])

  const treeData = useMemo(
    () =>
      buildReviewTreeData(tree?.tree ?? [], {
        decisions,
        onReject: (node) => {
          rejectForm.resetFields()
          setRejectTarget(node)
        },
      }),
    [decisions, rejectForm, tree],
  )

  return (
    <>
      <Drawer
        open={open}
        width={760}
        title={`分点审核 · 第 ${tree?.round_no ?? 1} 轮`}
        onClose={onClose}
        data-testid="review-drawer"
        footer={
          <Space style={{ float: 'right' }}>
            <Button data-testid="review-close" onClick={onClose}>
              关闭
            </Button>
            <Button
              loading={saving}
              disabled={loading || !nodes.length}
              data-testid="review-save"
              onClick={() => void saveDraft()}
            >
              保存草稿
            </Button>
            <Button
              type="primary"
              loading={submitting}
              disabled={loading || !nodes.length}
              data-testid="review-submit"
              onClick={submitConclusion}
            >
              提交结论
            </Button>
          </Space>
        }
      >
        {loading ? (
          <Typography.Text type="secondary">加载待审内容…</Typography.Text>
        ) : !nodes.length ? (
          <Empty description="当前没有可审核的模块 / 功能 / 功能点" />
        ) : (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Alert
              type="info"
              showIcon
              message="勾选 = 本次通过；不勾 = 未决策（提交时按未通过处理）。需要明确驳回的节点请点行内「驳回」并填写意见。"
            />
            <Space wrap>
              <Tag color="success">已通过 {stats.approved}</Tag>
              <Tag color="error">已驳回 {stats.rejected}</Tag>
              <Tag>未决策 {stats.pending}</Tag>
              <Typography.Text type="secondary" data-testid="review-progress">
                已选 {stats.approved} / 共 {stats.total}
              </Typography.Text>
            </Space>
            <Space>
              <Button
                size="small"
                data-testid="review-select-all"
                onClick={selectAll}
              >
                全选
              </Button>
              <Button
                size="small"
                data-testid="review-clear"
                onClick={clearAll}
              >
                清除选择
              </Button>
            </Space>
            <Tree
              checkable
              selectable={false}
              defaultExpandAll
              treeData={treeData}
              checkedKeys={checkedKeys}
              onCheck={handleCheck}
              data-testid="review-tree"
            />
          </Space>
        )}
      </Drawer>

      <Modal
        title="驳回节点"
        open={Boolean(rejectTarget)}
        onCancel={() => {
          setRejectTarget(null)
          rejectForm.resetFields()
        }}
        onOk={() => {
          void rejectForm
            .validateFields()
            .then((values) => applyReject(values.comment))
            .catch(() => undefined)
        }}
        okText="驳回"
        okButtonProps={{ danger: true }}
        cancelText="取消"
        destroyOnHidden
      >
        <Typography.Paragraph type="secondary">
          驳回后该节点不会进入本次快照，但仍留在结构表里，可修改后重新提交。
          {rejectTarget ? `（${rejectTarget.name}）` : ''}
        </Typography.Paragraph>
        <Form form={rejectForm} layout="vertical">
          <Form.Item
            name="comment"
            label="驳回意见"
            rules={[{ required: true, message: '驳回必须填写意见' }]}
          >
            <Input.TextArea
              rows={3}
              maxLength={500}
              data-testid="review-reject-comment"
            />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}
