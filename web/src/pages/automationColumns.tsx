import { Button, Space, Tooltip, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'

import type { AutomationAsset, AutomationRun } from '../api'
import {
  ARCHIVED_EXEC_TOOLTIP,
  PLAYWRIGHT_EXEC_TOOLTIP,
  assetStatusTag,
  formatConfidence,
  formatDuration,
  frameworkTag,
  runStatusTag,
} from './automationMeta'

interface AssetColumnProps {
  /** 写入口（关联 / 执行 / 归档）只有项目管理员才渲染。 */
  canManage: boolean
  onLink: (asset: AutomationAsset) => void
  onRun: (asset: AutomationAsset) => void
  onToggleArchive: (asset: AutomationAsset) => void
}

interface RunColumnProps {
  onOpenReport: (runId: number) => void
}

/**
 * 自动化 Tab 两张表的列定义（纯渲染，不含状态）。
 *
 * **为什么单独成文件**：主文件 `ProjectAutomationTab.tsx` 只留「状态与事件编排」，
 * 列定义拆出来才压得住 400 行的拆分阈值（验证约定 §4.3）。
 * 这与 04 期 `ProjectBaselineTree` → `baselineTreeNodes` 的拆法同一思路。
 */
export function buildAssetColumns({
  canManage,
  onLink,
  onRun,
  onToggleArchive,
}: AssetColumnProps): ColumnsType<AutomationAsset> {
  return [
    {
      title: '文件名',
      key: 'name',
      width: 200,
      render: (_: unknown, asset) => (
        <Space direction="vertical" size={0}>
          <span data-testid={`automation-asset-name-${asset.id}`}>{asset.name}</span>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {asset.file_path}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: '框架',
      dataIndex: 'framework',
      width: 100,
      render: (framework: string) => frameworkTag(framework),
    },
    {
      title: '置信度',
      dataIndex: 'parse_confidence',
      width: 80,
      render: (value: number | null) => formatConfidence(value),
    },
    {
      title: '用例数',
      dataIndex: 'detected_cases',
      width: 80,
    },
    {
      title: '关联用例',
      key: 'linked_case',
      width: 220,
      render: (_: unknown, asset) =>
        asset.linked_case_title ? (
          <Space direction="vertical" size={0}>
            <span data-testid={`automation-asset-linked-${asset.id}`}>
              {asset.linked_case_title}
            </span>
            {asset.linked_case_deleted ? (
              <Typography.Text type="warning" style={{ fontSize: 12 }}>
                源用例已删除
              </Typography.Text>
            ) : null}
          </Space>
        ) : (
          <span data-testid={`automation-asset-linked-${asset.id}`}>—</span>
        ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (status: string) => assetStatusTag(status),
    },
    {
      title: '操作',
      key: 'actions',
      width: 220,
      render: (_: unknown, asset) => (
        <Space size={4} wrap>
          {canManage ? (
            <Button
              size="small"
              onClick={() => onLink(asset)}
              data-testid={`automation-asset-link-btn-${asset.id}`}
            >
              关联用例
            </Button>
          ) : null}
          {canManage ? (
            <Tooltip
              title={
                asset.framework !== 'pytest'
                  ? PLAYWRIGHT_EXEC_TOOLTIP
                  : asset.status !== 'active'
                    ? ARCHIVED_EXEC_TOOLTIP
                    : undefined
              }
            >
              {/* disabled 的按钮不派发鼠标事件，Tooltip 要挂在外层 span 上才会弹。 */}
              <span>
                <Button
                  size="small"
                  type="primary"
                  disabled={asset.framework !== 'pytest' || asset.status !== 'active'}
                  onClick={() => onRun(asset)}
                  data-testid={`automation-run-btn-${asset.id}`}
                >
                  执行
                </Button>
              </span>
            </Tooltip>
          ) : null}
          {canManage ? (
            <Button
              size="small"
              onClick={() => onToggleArchive(asset)}
              data-testid={`automation-asset-archive-btn-${asset.id}`}
            >
              {asset.status === 'active' ? '归档' : '恢复'}
            </Button>
          ) : null}
        </Space>
      ),
    },
  ]
}

export function buildRunColumns({
  onOpenReport,
}: RunColumnProps): ColumnsType<AutomationRun> {
  return [
    {
      title: '发起时间',
      dataIndex: 'started_at',
      width: 180,
      render: (value: string | null) =>
        value ? new Date(value).toLocaleString() : '—',
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (status: string, run) => (
        <span data-testid={`automation-run-status-${run.id}`}>{runStatusTag(status)}</span>
      ),
    },
    {
      title: '统计',
      key: 'stats',
      width: 220,
      render: (_: unknown, run) => (
        <span data-testid={`automation-run-stats-${run.id}`}>
          {run.stats?.total ?? 0} 个资产 / 通过 {run.stats?.passed ?? 0} / 失败{' '}
          {run.stats?.failed ?? 0} / 跳过 {run.stats?.skipped ?? 0}
        </span>
      ),
    },
    {
      title: '耗时',
      key: 'duration',
      width: 100,
      render: (_: unknown, run) => formatDuration(run.duration_ms),
    },
    {
      title: '操作',
      key: 'actions',
      width: 100,
      render: (_: unknown, run) => (
        <Button
          size="small"
          onClick={() => onOpenReport(run.id)}
          data-testid={`automation-run-report-btn-${run.id}`}
        >
          报告
        </Button>
      ),
    },
  ]
}
