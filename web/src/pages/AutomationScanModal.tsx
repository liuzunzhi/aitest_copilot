import { useState } from 'react'
import {
  App as AntdApp,
  Alert,
  Button,
  Input,
  Modal,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'

import { createAutomationAssets, scanAutomationAssets } from '../api'
import type { AssetsCreateResult, ScannedAsset, ScanResult } from '../api'
import { errorMessage } from '../api/client'
import { formatConfidence, frameworkTag, scanStatusTag } from './automationMeta'

interface Props {
  open: boolean
  projectId: number
  onClose: () => void
  /** 入库成功后回调（父级据此刷新资产表）。 */
  onImported: (result: AssetsCreateResult) => void
}

/**
 * 扫描入库弹窗：目录输入 → 扫描结果清单 → 勾选 → 确认入库。
 *
 * **扫描只出清单，不写表**（PRD 2.4.6「由人工确认后入库」）——
 * 批量新建几十个实体是高风险行为，必须人工确认。
 *
 * **低置信度（< 0.7）默认不勾选**（spec §3.2）并标「低置信度，请人工确认」；
 * **已入库的项默认不勾选**（后端会按唯一索引跳过，勾了也只是白跑一趟）。
 *
 * 入库时前端传的置信度与用例数只是**对照值**——服务端会重扫重算。
 */
export default function AutomationScanModal({ open, projectId, onClose, onImported }: Props) {
  const { message } = AntdApp.useApp()
  const [directory, setDirectory] = useState('')
  const [scanning, setScanning] = useState(false)
  const [importing, setImporting] = useState(false)
  const [result, setResult] = useState<ScanResult | null>(null)
  const [selected, setSelected] = useState<string[]>([])

  async function doScan() {
    setScanning(true)
    try {
      const data = await scanAutomationAssets(projectId, directory.trim())
      setResult(data)
      // 默认勾选：未入库 + 置信度达标。其余交给人工判断。
      setSelected(
        data.assets
          .filter((item) => item.status === 'new' && !item.low_confidence)
          .map((item) => item.file_path),
      )
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setScanning(false)
    }
  }

  async function doImport() {
    if (!result) return
    const picked = result.assets.filter((item) => selected.includes(item.file_path))
    if (!picked.length) {
      message.warning('请至少勾选一个资产')
      return
    }
    setImporting(true)
    try {
      const created = await createAutomationAssets(
        projectId,
        picked.map((item) => ({
          file_path: item.file_path,
          name: item.name,
          framework: item.framework,
          parse_confidence: item.parse_confidence,
          detected_cases: item.detected_cases,
        })),
      )
      message.success(`已入库 ${created.created} 个资产，跳过 ${created.skipped} 个`)
      onImported(created)
      onClose()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setImporting(false)
    }
  }

  const columns: ColumnsType<ScannedAsset> = [
    {
      title: '文件名',
      dataIndex: 'name',
      width: 180,
      render: (name: string, item) => (
        <Space size={4}>
          <span>{name}</span>
          {item.low_confidence ? (
            <Tag color="warning" data-testid={`automation-scan-low-${item.file_path}`}>
              低置信度，请人工确认
            </Tag>
          ) : null}
        </Space>
      ),
    },
    {
      title: '相对路径',
      dataIndex: 'file_path',
      render: (path: string) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {path}
        </Typography.Text>
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
      width: 90,
      render: (value: number) => formatConfidence(value),
    },
    {
      title: '用例数',
      dataIndex: 'detected_cases',
      width: 80,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (status: string) => scanStatusTag(status),
    },
  ]

  return (
    <Modal
      open={open}
      title="扫描自动化资产"
      onCancel={onClose}
      onOk={doImport}
      confirmLoading={importing}
      okText="确认入库"
      cancelText="取消"
      okButtonProps={{
        'data-testid': 'automation-scan-confirm-btn',
        disabled: !result || !selected.length,
      }}
      width={900}
      destroyOnHidden
    >
      <Space
        direction="vertical"
        size={12}
        style={{ width: '100%' }}
        data-testid="automation-scan-modal"
      >
        <Space.Compact style={{ width: '100%' }}>
          <Input
            placeholder="扫描目录（相对自动化根目录，留空表示全部）"
            value={directory}
            onChange={(event) => setDirectory(event.target.value)}
            onPressEnter={() => void doScan()}
            data-testid="automation-scan-dir-input"
          />
          <Button type="primary" loading={scanning} onClick={() => void doScan()} data-testid="automation-scan-run-btn">
            扫描
          </Button>
        </Space.Compact>

        {result ? (
          <Space size={16} wrap data-testid="automation-scan-stats">
            <span>根目录：{result.root}</span>
            <span>扫描文件 {result.scanned_files} 个</span>
            <span>识别 {result.matched} 个</span>
            <span>未识别 {result.skipped} 个</span>
          </Space>
        ) : (
          <Alert
            type="info"
            showIcon
            message="扫描只出清单，不会直接入库——勾选后点「确认入库」才会写库。"
          />
        )}

        {result && result.assets.length ? (
          <Table<ScannedAsset>
            rowKey="file_path"
            size="small"
            columns={columns}
            dataSource={result.assets}
            pagination={false}
            scroll={{ y: 320 }}
            rowSelection={{
              selectedRowKeys: selected,
              onChange: (keys) => setSelected(keys as string[]),
              getCheckboxProps: (item) => ({
                disabled: item.status === 'existing',
                name: item.file_path,
                // 勾选框的 testid 落在真正的 <input> 上，e2e 直接点它。
                'data-testid': `automation-scan-check-${item.file_path}`,
              }),
            }}
            locale={{ emptyText: '没有识别到自动化资产' }}
            data-testid="automation-scan-table"
          />
        ) : null}
      </Space>
    </Modal>
  )
}
