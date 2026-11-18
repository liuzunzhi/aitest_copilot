/** 分点审核抽屉的待审树渲染：名称 + 决策标 + 驳回入口。 */

import type { ReactNode } from 'react'
import { Button, Space, Tag, Tooltip, Typography } from 'antd'
import type { DataNode } from 'antd/es/tree'
import type {
  BaselineReviewTreeNode,
  ReviewDecisionValue,
} from '../api'

export interface ReviewNodeDecision {
  decision: ReviewDecisionValue
  comment?: string | null
}

export interface ReviewNodeOptions {
  decisions: Record<string, ReviewNodeDecision>
  onReject: (node: BaselineReviewTreeNode) => void
}

const TYPE_META: Record<string, { label: string; color: string }> = {
  module: { label: '模块', color: 'blue' },
  function: { label: '功能', color: 'geekblue' },
  feature_point: { label: '功能点', color: 'default' },
}

const DECISION_META: Record<string, { label: string; color: string }> = {
  approved: { label: '已通过', color: 'success' },
  rejected: { label: '已驳回', color: 'error' },
  pending: { label: '未决策', color: 'default' },
}

export function reviewNodeKey(entityType: string, entityId: number): string {
  return `${entityType}:${entityId}`
}

/** 当前决策：用户的本地改动优先，其次用服务端已保存的决策。 */
export function resolveDecision(
  node: BaselineReviewTreeNode,
  decisions: Record<string, ReviewNodeDecision>,
): ReviewNodeDecision {
  return (
    decisions[reviewNodeKey(node.entity_type, node.entity_id)] ?? {
      decision: node.decision,
      comment: node.comment,
    }
  )
}

/** 把树摊平成节点数组（用于全选 / 统计 / 决策转换）。 */
export function flattenReviewTree(
  nodes: BaselineReviewTreeNode[],
): BaselineReviewTreeNode[] {
  return nodes.flatMap((node) => [node, ...flattenReviewTree(node.children)])
}

function nodeTitle(
  node: BaselineReviewTreeNode,
  options: ReviewNodeOptions,
  parentRejected: boolean,
): ReactNode {
  const current = resolveDecision(node, options.decisions)
  const meta = DECISION_META[current.decision] ?? DECISION_META.pending
  const type = TYPE_META[node.entity_type] ?? TYPE_META.feature_point
  const key = reviewNodeKey(node.entity_type, node.entity_id)

  return (
    <Space size={6} wrap data-testid={`review-node-${key}`}>
      <Tag color={type.color}>{type.label}</Tag>
      <span>{node.name}</span>
      <Tag color={meta.color}>{meta.label}</Tag>
      {parentRejected && current.decision !== 'rejected' && (
        <Tag color="orange">随父驳回</Tag>
      )}
      {current.decision === 'rejected' && current.comment && (
        <Typography.Text type="danger">意见：{current.comment}</Typography.Text>
      )}
      {current.decision !== 'rejected' && (
        <Tooltip title="单独驳回该节点（需填写意见）">
          <Button
            size="small"
            type="link"
            danger
            data-testid={`review-reject-${key}`}
            onClick={(event) => {
              event.stopPropagation()
              options.onReject(node)
            }}
          >
            驳回
          </Button>
        </Tooltip>
      )}
    </Space>
  )
}

function buildNode(
  node: BaselineReviewTreeNode,
  options: ReviewNodeOptions,
  parentRejected: boolean,
): DataNode {
  const rejected =
    parentRejected ||
    resolveDecision(node, options.decisions).decision === 'rejected'
  const children = node.children.map((child) =>
    buildNode(child, options, rejected),
  )
  return {
    key: reviewNodeKey(node.entity_type, node.entity_id),
    title: nodeTitle(node, options, parentRejected),
    children: children.length ? children : undefined,
  }
}

export function buildReviewTreeData(
  nodes: BaselineReviewTreeNode[],
  options: ReviewNodeOptions,
): DataNode[] {
  return nodes.map((node) => buildNode(node, options, false))
}
