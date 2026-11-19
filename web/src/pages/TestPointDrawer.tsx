import { useEffect, useState } from 'react'
import { Alert, App as AntdApp, Button, Descriptions, Drawer, Input, Space, Tag, Typography } from 'antd'

import { reviewTestPoint } from '../api'
import type { TestPoint } from '../api'
import { errorMessage } from '../api/client'
import { SOURCE_LABELS, pointStatusTag, priorityTag, targetText } from './testPointMeta'

interface Props {
  open: boolean
  projectId: number
  point: TestPoint | null
  /** 评审限项目管理员（后端 403 NOT_PROJECT_ADMIN）。 */
  canWrite: boolean
  onClose: () => void
  /** 评审成功后把最新测试点回传给父级，列表与抽屉一起刷新。 */
  onReviewed: (point: TestPoint) => void
}

/** 测试点详情抽屉：全文 + 来源追溯 + 评审操作。 */
export default function TestPointDrawer({
  open,
  projectId,
  point,
  canWrite,
  onClose,
  onReviewed,
}: Props) {
  const { message } = AntdApp.useApp()
  const [comment, setComment] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // 切换测试点时清空上一轮的评审意见——避免把 A 的意见带到 B 上。
  useEffect(() => {
    setComment('')
  }, [point?.id])

  async function submitReview(action: 'approve' | 'reject') {
    if (!point) return
    setSubmitting(true)
    try {
      const updated = await reviewTestPoint(projectId, point.id, {
        action,
        comment: comment.trim() || null,
      })
      message.success(action === 'approve' ? '已通过' : '已驳回')
      onReviewed(updated)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setSubmitting(false)
    }
  }

  const canReview = canWrite && point?.status === 'pending'

  return (
    <Drawer
      title={point ? `测试点 #${point.id}` : '测试点'}
      width={720}
      open={open}
      onClose={onClose}
    >
      {point ? (
        <Space direction="vertical" size={16} style={{ width: '100%' }} data-testid="test-point-drawer">
          {point.needs_review ? (
            <Alert
              type="warning"
              showIcon
              data-testid="test-point-needs-review-alert"
              message="该测试点依赖的基线标签已被清除，请复核"
              description={`${point.needs_review_reason ?? '标签已被清除'}${
                point.needs_review_at
                  ? `（${new Date(point.needs_review_at).toLocaleString()}）`
                  : ''
              }`}
            />
          ) : null}

          <Typography.Title level={5} style={{ margin: 0 }}>
            {point.name}
          </Typography.Title>

          <Descriptions size="small" column={2} bordered>
            <Descriptions.Item label="状态">
              <span data-testid="test-point-review-status">{pointStatusTag(point.status)}</span>
            </Descriptions.Item>
            <Descriptions.Item label="优先级">{priorityTag(point.priority)}</Descriptions.Item>
            <Descriptions.Item label="目标" span={2}>
              {targetText(point.target_type, point.target_id, point.target_name)}
            </Descriptions.Item>
            <Descriptions.Item label="章节">{point.chapter_title ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="来源">
              {SOURCE_LABELS[point.source_type] ?? point.source_type}
            </Descriptions.Item>
            <Descriptions.Item label="来源标签">
              {point.source_label_id ? `#${point.source_label_id}` : '—'}
            </Descriptions.Item>
            <Descriptions.Item label="来源增量结论">
              {point.source_conclusion_id ? `#${point.source_conclusion_id}` : '—'}
            </Descriptions.Item>
            <Descriptions.Item label="创建时间">
              {new Date(point.created_at).toLocaleString()}
            </Descriptions.Item>
            <Descriptions.Item label="评审时间">
              {point.reviewed_at ? new Date(point.reviewed_at).toLocaleString() : '—'}
            </Descriptions.Item>
            <Descriptions.Item label="评审意见" span={2}>
              {point.review_comment ?? '—'}
            </Descriptions.Item>
          </Descriptions>

          <div>
            <Typography.Text strong>前置条件</Typography.Text>
            <Typography.Paragraph style={{ marginTop: 4, whiteSpace: 'pre-wrap' }}>
              {point.precondition || '—'}
            </Typography.Paragraph>
          </div>

          <div>
            <Typography.Text strong>验证要点</Typography.Text>
            <Typography.Paragraph style={{ marginTop: 4, whiteSpace: 'pre-wrap' }}>
              {point.verification || '—'}
            </Typography.Paragraph>
          </div>

          {point.needs_review ? <Tag color="warning">待复核</Tag> : null}

          {canReview ? (
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <Input.TextArea
                rows={2}
                maxLength={500}
                showCount
                placeholder="评审意见（可选）"
                value={comment}
                onChange={(event) => setComment(event.target.value)}
                data-testid="test-point-review-comment"
              />
              <Space>
                <Button
                  type="primary"
                  loading={submitting}
                  onClick={() => submitReview('approve')}
                  data-testid="test-point-approve-btn"
                >
                  通过
                </Button>
                <Button danger loading={submitting} onClick={() => submitReview('reject')} data-testid="test-point-reject-btn">
                  驳回
                </Button>
              </Space>
            </Space>
          ) : point.status === 'pending' ? (
            <Typography.Text type="secondary">只有项目管理员可以评审测试点。</Typography.Text>
          ) : (
            <Typography.Text type="secondary">该测试点已评审，不能重复评审。</Typography.Text>
          )}
        </Space>
      ) : null}
    </Drawer>
  )
}
