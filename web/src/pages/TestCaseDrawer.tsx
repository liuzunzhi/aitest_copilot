import { useEffect, useState } from 'react'
import {
  Alert,
  App as AntdApp,
  Button,
  Descriptions,
  Drawer,
  Input,
  Space,
  Tag,
  Typography,
} from 'antd'

import { ackTestCase, replaceTestCaseSteps, reviewTestCase } from '../api'
import type { TestCase } from '../api'
import { errorMessage } from '../api/client'
import TestCaseStepsEditor from './TestCaseStepsEditor'
import {
  CASE_SOURCE_LABELS,
  NEEDS_REVIEW_REASON_LABELS,
  casePriorityTag,
  caseStatusTag,
  caseTypeTag,
  testPointText,
} from './testCaseMeta'

interface Props {
  open: boolean
  projectId: number
  testCase: TestCase | null
  /** 评审 / 编辑步骤 / 确认复核都限项目管理员（后端 403 NOT_PROJECT_ADMIN）。 */
  canWrite: boolean
  onClose: () => void
  /** 用例变化后回传给父级——列表与抽屉一起刷新。 */
  onUpdated: (updated: TestCase) => void
}

/**
 * 测试用例详情抽屉：元数据 + 步骤 + 待复核告警 + 评审操作。
 *
 * 三种写操作在这里都能完成，父组件不用再开一堆弹窗：
 * - 评审：通过 / 驳回；
 * - 编辑步骤：就地改数组，保存时整体 `PUT /steps`；
 * - 确认已复核：把源测试点快照刷成当前值。
 */
export default function TestCaseDrawer({
  open,
  projectId,
  testCase,
  canWrite,
  onClose,
  onUpdated,
}: Props) {
  const { message } = AntdApp.useApp()
  const [comment, setComment] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [editingSteps, setEditingSteps] = useState(false)
  const [stepRows, setStepRows] = useState<
    Array<{ key: string; action: string; expected: string }>
  >([])

  // 切换用例时清空上一轮的评审意见与编辑态——避免把 A 的意见带到 B 上。
  useEffect(() => {
    setComment('')
    setEditingSteps(false)
  }, [testCase?.id])

  useEffect(() => {
    setStepRows(
      (testCase?.steps ?? []).map((step, index) => ({
        key: `s${index}`,
        action: step.action,
        expected: step.expected,
      })),
    )
  }, [testCase?.id, testCase?.steps])

  async function submitReview(action: 'approve' | 'reject') {
    if (!testCase) return
    setSubmitting(true)
    try {
      const updated = await reviewTestCase(projectId, testCase.id, {
        action,
        comment: comment.trim() || null,
      })
      message.success(action === 'approve' ? '已通过' : '已驳回')
      onUpdated(updated)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setSubmitting(false)
    }
  }

  async function saveSteps() {
    if (!testCase) return
    setSubmitting(true)
    try {
      // 整体覆盖：后端只认数组顺序，序号由服务端重排为 1..n。
      const updated = await replaceTestCaseSteps(
        projectId,
        testCase.id,
        stepRows.map((row) => ({ action: row.action, expected: row.expected })),
      )
      message.success('步骤已保存')
      setEditingSteps(false)
      onUpdated(updated)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setSubmitting(false)
    }
  }

  async function confirmReview() {
    if (!testCase) return
    setSubmitting(true)
    try {
      const updated = await ackTestCase(projectId, testCase.id)
      message.success('已确认复核')
      onUpdated(updated)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setSubmitting(false)
    }
  }

  const canReview = canWrite && testCase?.status === 'pending'

  return (
    <Drawer
      title={testCase ? `测试用例 #${testCase.id}` : '测试用例'}
      width={860}
      open={open}
      onClose={onClose}
    >
      {testCase ? (
        <Space direction="vertical" size={16} style={{ width: '100%' }} data-testid="test-case-drawer">
          {testCase.needs_review ? (
            <Alert
              type="warning"
              showIcon
              data-testid="test-case-needs-review-alert"
              message="所属测试点发生变化，请复核用例"
              description={`${
                NEEDS_REVIEW_REASON_LABELS[testCase.needs_review_reason ?? ''] ??
                testCase.needs_review_reason ??
                '源测试点已变更'
              }${
                testCase.needs_review_ack_at
                  ? `（上次确认于 ${new Date(testCase.needs_review_ack_at).toLocaleString()}）`
                  : ''
              }`}
              action={
                canWrite ? (
                  <Button
                    size="small"
                    type="primary"
                    loading={submitting}
                    onClick={confirmReview}
                    data-testid="test-case-ack-btn"
                  >
                    确认已复核
                  </Button>
                ) : null
              }
            />
          ) : null}

          <Typography.Title level={5} style={{ margin: 0 }}>
            {testCase.title}
          </Typography.Title>

          <Descriptions size="small" column={2} bordered>
            <Descriptions.Item label="状态">
              <span data-testid="test-case-review-status">{caseStatusTag(testCase.status)}</span>
            </Descriptions.Item>
            <Descriptions.Item label="优先级">
              {casePriorityTag(testCase.priority)}
            </Descriptions.Item>
            <Descriptions.Item label="用例类型">{caseTypeTag(testCase.case_type)}</Descriptions.Item>
            <Descriptions.Item label="来源">
              {CASE_SOURCE_LABELS[testCase.source_type] ?? testCase.source_type}
            </Descriptions.Item>
            <Descriptions.Item label="所属测试点" span={2}>
              <span data-testid="test-case-source-point">
                {testPointText(testCase.test_point_id, testCase.test_point_name)}
              </span>
            </Descriptions.Item>
            <Descriptions.Item label="功能或功能点" span={2}>
              {testCase.target_name}
            </Descriptions.Item>
            <Descriptions.Item label="章节">{testCase.chapter_title ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="生成记录">
              {testCase.analysis_id ? `#${testCase.analysis_id}` : '手工新增'}
            </Descriptions.Item>
            <Descriptions.Item label="创建时间">
              {new Date(testCase.created_at).toLocaleString()}
            </Descriptions.Item>
            <Descriptions.Item label="评审时间">
              {testCase.reviewed_at ? new Date(testCase.reviewed_at).toLocaleString() : '—'}
            </Descriptions.Item>
            <Descriptions.Item label="评审意见" span={2}>
              {testCase.review_comment ?? '—'}
            </Descriptions.Item>
          </Descriptions>

          <div>
            <Typography.Text strong>前置条件</Typography.Text>
            <Typography.Paragraph style={{ marginTop: 4, whiteSpace: 'pre-wrap' }}>
              {testCase.precondition || '—'}
            </Typography.Paragraph>
          </div>

          <div>
            <Space style={{ marginBottom: 8 }}>
              <Typography.Text strong>操作步骤与预期结果</Typography.Text>
              {canWrite && !editingSteps ? (
                <Button
                  size="small"
                  onClick={() => setEditingSteps(true)}
                  data-testid="test-case-steps-edit-btn"
                >
                  编辑步骤
                </Button>
              ) : null}
            </Space>
            {editingSteps ? (
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                <TestCaseStepsEditor value={stepRows} onChange={setStepRows} />
                <Space>
                  <Button
                    type="primary"
                    loading={submitting}
                    onClick={saveSteps}
                    data-testid="test-case-steps-save-btn"
                  >
                    保存步骤
                  </Button>
                  <Button
                    onClick={() => {
                      setEditingSteps(false)
                      setStepRows(
                        (testCase.steps ?? []).map((step, index) => ({
                          key: `s${index}`,
                          action: step.action,
                          expected: step.expected,
                        })),
                      )
                    }}
                    data-testid="test-case-steps-cancel-btn"
                  >
                    取消
                  </Button>
                </Space>
              </Space>
            ) : (
              <TestCaseStepsEditor readOnly steps={testCase.steps} />
            )}
          </div>

          {testCase.needs_review ? <Tag color="warning">待复核</Tag> : null}

          {canReview ? (
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <Input.TextArea
                rows={2}
                maxLength={500}
                showCount
                placeholder="评审意见（可选）"
                value={comment}
                onChange={(event) => setComment(event.target.value)}
                data-testid="test-case-review-comment"
              />
              <Space>
                <Button
                  type="primary"
                  loading={submitting}
                  onClick={() => submitReview('approve')}
                  data-testid="test-case-approve-btn"
                >
                  通过
                </Button>
                <Button
                  danger
                  loading={submitting}
                  onClick={() => submitReview('reject')}
                  data-testid="test-case-reject-btn"
                >
                  驳回
                </Button>
              </Space>
            </Space>
          ) : testCase.status === 'pending' ? (
            <Typography.Text type="secondary">只有项目管理员可以评审测试用例。</Typography.Text>
          ) : (
            <Typography.Text type="secondary">该用例已评审，不能重复评审。</Typography.Text>
          )}
        </Space>
      ) : null}
    </Drawer>
  )
}
