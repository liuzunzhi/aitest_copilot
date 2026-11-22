import { useCallback, useEffect, useMemo, useState } from 'react'
import type React from 'react'
import {
  App as AntdApp,
  Button,
  Card,
  Select,
  Space,
  Table,
  Typography,
} from 'antd'

import {
  createAutomationRun,
  listAutomationAssets,
  listAutomationRuns,
  updateAutomationAsset,
} from '../api'
import type {
  AutomationAsset,
  AutomationAssetStatus,
  AutomationFramework,
  AutomationRun,
} from '../api'
import { errorMessage } from '../api/client'
import AutomationLinkModal from './AutomationLinkModal'
import AutomationReportDrawer from './AutomationReportDrawer'
import AutomationScanModal from './AutomationScanModal'
import { buildAssetColumns, buildRunColumns } from './automationColumns'
import { ASSET_STATUS_OPTIONS, FRAMEWORK_OPTIONS } from './automationMeta'

interface Props {
  projectId: number
  /** 扫描 / 入库 / 改关联 / 触发执行都限项目管理员（后端 403 NOT_PROJECT_ADMIN）。 */
  canManage: boolean
}

/**
 * 「自动化执行」Tab。
 *
 * 三段式布局：
 * - 上：**资产表**（文件名 / 框架 / 置信度 / 用例数 / 关联用例 / 状态 / 操作）；
 * - 中：**扫描入库弹窗**（目录输入 → 扫描结果清单 → 勾选 → 确认入库）；
 * - 下：**执行记录表**（状态 / 统计 / 耗时 / 发起时间）+ 触发执行 + 报告抽屉。
 *
 * **写入口只有项目管理员能看到**——不是「渲染了点了报 403」，
 * 前端就不给入口（成员 / 访客只读）。
 *
 * **本文件只留状态与事件编排**，列定义在 `automationColumns.tsx`
 * （验证约定 §4.3 的 400 行拆分阈值）。
 */
export default function ProjectAutomationTab({ projectId, canManage }: Props) {
  const { message } = AntdApp.useApp()
  const [assets, setAssets] = useState<AutomationAsset[]>([])
  const [runs, setRuns] = useState<AutomationRun[]>([])
  const [loading, setLoading] = useState(false)
  const [frameworkFilter, setFrameworkFilter] = useState<AutomationFramework | undefined>()
  const [statusFilter, setStatusFilter] = useState<AutomationAssetStatus | undefined>()

  const [scanOpen, setScanOpen] = useState(false)
  const [running, setRunning] = useState(false)
  const [linkAsset, setLinkAsset] = useState<AutomationAsset | null>(null)
  const [reportRunId, setReportRunId] = useState<number | null>(null)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const [assetPage, runPage] = await Promise.all([
        listAutomationAssets(projectId, {
          framework: frameworkFilter,
          status: statusFilter,
          page_size: 200,
        }),
        listAutomationRuns(projectId, { page_size: 50 }),
      ])
      setAssets(assetPage.items)
      setRuns(runPage.items)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [projectId, frameworkFilter, statusFilter, message])

  useEffect(() => {
    void reload()
  }, [reload])

  /** 可执行的资产：Pytest + 在用。Playwright 本期只读，执行入口置灰。 */
  const executableAssets = useMemo(
    () => assets.filter((item) => item.framework === 'pytest' && item.status === 'active'),
    [assets],
  )

  /**
   * 触发执行。
   *
   * **同步跑完才返回**（后端不引入异步队列），所以一次可能跑几十秒——
   * 这与 04 的「从文档推导基线」同一策略：按钮要有 loading，用户知道在等。
   *
   * @param assetIds 不传 = 执行全部可执行资产；传了 = 只执行这几个。
   */
  async function triggerRun(assetIds?: number[]) {
    const ids = assetIds ?? executableAssets.map((item) => item.id)
    if (!ids.length) {
      message.warning('没有可执行的资产（本期只执行 Pytest，且资产要在用）')
      return
    }
    setRunning(true)
    try {
      const run = await createAutomationRun(projectId, ids)
      // **执行完成 ≠ 全部通过**：退出码非 0 只是「有测试失败」，
      // 那在明细的 result 里看，不在这里混为一谈。
      message.success(
        run.status === 'succeeded'
          ? `执行完成（退出码 ${run.exit_code ?? '—'}）`
          : '执行未正常完成，请在报告里看原因',
      )
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setRunning(false)
    }
  }

  async function toggleArchive(asset: AutomationAsset) {
    const next = asset.status === 'active' ? 'archived' : 'active'
    try {
      await updateAutomationAsset(projectId, asset.id, { status: next })
      message.success(next === 'archived' ? '资产已归档' : '资产已恢复')
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  const assetColumns = buildAssetColumns({
    canManage,
    onLink: setLinkAsset,
    onRun: (asset) => void triggerRun([asset.id]),
    onToggleArchive: (asset) => void toggleArchive(asset),
  })

  const runColumns = buildRunColumns({
    onOpenReport: setReportRunId,
  })

  return (
    <div>
      <Card
        title="自动化资产"
        size="small"
        style={{ marginBottom: 16 }}
        extra={
          canManage ? (
            <Space>
              <Button
                type="primary"
                onClick={() => setScanOpen(true)}
                data-testid="automation-scan-btn"
              >
                扫描入库
              </Button>
              <Button
                loading={running}
                onClick={() => void triggerRun()}
                data-testid="automation-run-btn"
              >
                执行全部可执行资产
              </Button>
            </Space>
          ) : null
        }
      >
        {!canManage ? (
          <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
            只有项目管理员可以扫描、入库与执行，你可以查看资产与报告。
          </Typography.Text>
        ) : null}
        <Space wrap style={{ marginBottom: 12 }}>
          <Select
            allowClear
            placeholder="框架"
            style={{ width: 140 }}
            options={FRAMEWORK_OPTIONS}
            value={frameworkFilter}
            onChange={(value) => setFrameworkFilter(value)}
            data-testid="automation-asset-framework-filter"
          />
          <Select
            allowClear
            placeholder="状态"
            style={{ width: 140 }}
            options={ASSET_STATUS_OPTIONS}
            value={statusFilter}
            onChange={(value) => setStatusFilter(value)}
            data-testid="automation-asset-status-filter"
          />
          <Button onClick={() => void reload()} data-testid="automation-refresh-btn">
            刷新
          </Button>
        </Space>
        <Table<AutomationAsset>
          rowKey="id"
          columns={assetColumns}
          dataSource={assets}
          loading={loading}
          pagination={false}
          scroll={{ x: 1000 }}
          locale={{ emptyText: '还没有自动化资产' }}
          data-testid="automation-asset-table"
          // 行锚点：e2e 用 `automation-asset-row-{id}` 定位具体某一行。
          // TS 的 `HTMLAttributes` 不带 `data-*` 索引签名（JSX 里允许是因为
          // 带连字符的属性名走特例），对象字面量要显式断言一下。
          onRow={(asset) =>
            ({
              'data-testid': `automation-asset-row-${asset.id}`,
            }) as React.HTMLAttributes<HTMLElement>
          }
        />
      </Card>

      <Card title="执行记录" size="small">
        <Table<AutomationRun>
          rowKey="id"
          columns={runColumns}
          dataSource={runs}
          loading={loading}
          pagination={false}
          scroll={{ x: 800 }}
          locale={{ emptyText: '还没有执行记录' }}
          data-testid="automation-run-table"
        />
      </Card>

      <AutomationScanModal
        open={scanOpen}
        projectId={projectId}
        onClose={() => setScanOpen(false)}
        onImported={() => void reload()}
      />

      <AutomationLinkModal
        open={linkAsset !== null}
        projectId={projectId}
        asset={linkAsset}
        onClose={() => setLinkAsset(null)}
        onUpdated={() => void reload()}
      />

      <AutomationReportDrawer
        open={reportRunId !== null}
        projectId={projectId}
        runId={reportRunId}
        onClose={() => setReportRunId(null)}
      />
    </div>
  )
}
