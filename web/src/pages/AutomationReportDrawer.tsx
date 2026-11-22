import { useEffect, useState } from 'react'
import {
  Alert,
  App as AntdApp,
  Drawer,
  Space,
  Table,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'

import { fetchAutomationRunReport } from '../api'
import type { AutomationRunItem, AutomationRunReport } from '../api'
import { errorMessage } from '../api/client'
import {
  formatDuration,
  frameworkTag,
  resultTag,
  runStatusTag,
} from './automationMeta'

interface Props {
  open: boolean
  projectId: number
  runId: number | null
  onClose: () => void
}

/**
 * 单次执行报告抽屉：统计 + 明细表 + 追溯链 + 日志。
 *
 * **两套状态文案不能混**（09 期红线）：
 * - 顶部的 `status` 是**执行进程**的状态（`执行完成` / `执行失败`）；
 * - 明细里的 `result` 是**用例**的结果（`通过` / `失败` / `跳过`）。
 *
 * `status='succeeded'` 且 `exit_code=1` 是**正常情况**——
 * pytest 进程跑完了，只是有测试没过（业务结果，不是系统错误）。
 */
export default function AutomationReportDrawer({
  open,
  projectId,
  runId,
  onClose,
}: Props) {
  const { message } = AntdApp.useApp()
  const [report, setReport] = useState<AutomationRunReport | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open || runId === null) {
      setReport(null)
      return
    }
    let cancelled = false
    setLoading(true)
    fetchAutomationRunReport(projectId, runId)
      .then((data) => {
        if (!cancelled) setReport(data)
      })
      .catch((error) => {
        if (!cancelled) message.error(errorMessage(error))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, projectId, runId, message])

  const itemColumns: ColumnsType<AutomationRunItem> = [
    {
      title: '文件',
      key: 'file',
      width: 200,
      render: (_: unknown, item) => item.file_path ?? `资产 #${item.asset_id}`,
    },
    {
      title: '框架',
      key: 'framework',
      width: 90,
      render: (_: unknown, item) =>
        item.framework ? frameworkTag(item.framework) : '—',
    },
    {
      title: '结果',
      key: 'result',
      width: 80,
      render: (_: unknown, item) => (
        <span data-testid={`automation-report-result-${item.asset_id}`}>
          {resultTag(item.result)}
        </span>
      ),
    },
    {
      title: '耗时',
      key: 'duration',
      width: 90,
      render: (_: unknown, item) => formatDuration(item.duration_ms),
    },
    {
      title: '追溯链',
      key: 'traceability',
      render: (_: unknown, item) => {
        const trace = item.traceability
        if (!trace.linked_case_id && !trace.case_title) return '—'
        return (
          <Space
            direction="vertical"
            size={0}
            data-testid={`automation-report-trace-${item.asset_id}`}
          >
            <span>用例：{trace.case_title ?? '—'}</span>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              测试点：{trace.test_point_name ?? '—'}
            </Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              目标：{trace.target_name ?? '—'}
            </Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              章节：{trace.chapter_title ?? '—'}
            </Typography.Text>
            {trace.source_case_deleted ? (
              <Typography.Text type="warning" style={{ fontSize: 12 }}>
                源用例已删除（显示的是执行时的快照）
              </Typography.Text>
            ) : null}
          </Space>
        )
      },
    },
    {
      title: '失败原因',
      key: 'error',
      render: (_: unknown, item) => item.error ?? '—',
    },
  ]

  return (
    <Drawer
      title={runId === null ? '执行报告' : `执行报告 #${runId}`}
      width={1000}
      open={open}
      onClose={onClose}
      destroyOnHidden
    >
      {/* 锚点常驻：抽屉一打开就在，e2e 可以拿它判断「抽屉已落位」。 */}
      <div data-testid="automation-report-drawer">
        {loading && !report ? (
          <Typography.Text type="secondary">正在加载执行报告…</Typography.Text>
        ) : null}
        {report ? (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            {report.error ? (
              <Alert type="error" showIcon message="执行未正常完成" description={report.error} />
            ) : null}

            <Space size={24} wrap data-testid="automation-report-stats">
              <span>
                状态：
                <span data-testid="automation-report-status">
                  {runStatusTag(report.status)}
                </span>
              </span>
              <span>框架：{frameworkTag(report.framework)}</span>
              <span>退出码：{report.exit_code ?? '—'}</span>
              <span>
                统计：{report.stats?.total ?? 0} 个资产 / 通过 {report.stats?.passed ?? 0} / 失败{' '}
                {report.stats?.failed ?? 0} / 跳过 {report.stats?.skipped ?? 0}
              </span>
              <span>耗时：{formatDuration(report.duration_ms)}</span>
              <span>
                发起时间：
                {report.started_at ? new Date(report.started_at).toLocaleString() : '—'}
              </span>
            </Space>

            <div>
              <Typography.Text strong>执行明细</Typography.Text>
              <Table<AutomationRunItem>
                rowKey="asset_id"
                size="small"
                columns={itemColumns}
                dataSource={report.items}
                pagination={false}
                scroll={{ x: 900 }}
                locale={{ emptyText: '这次执行没有明细' }}
                data-testid="automation-report-item-table"
              />
            </div>

            <div>
              <Typography.Text strong>执行日志</Typography.Text>
              <Typography.Paragraph
                style={{
                  marginTop: 4,
                  whiteSpace: 'pre-wrap',
                  fontFamily: 'monospace',
                  fontSize: 12,
                  maxHeight: 320,
                  overflow: 'auto',
                }}
                data-testid="automation-report-log"
              >
                {report.log || '（没有日志输出）'}
              </Typography.Paragraph>
            </div>
          </Space>
        ) : null}
      </div>
    </Drawer>
  )
}
