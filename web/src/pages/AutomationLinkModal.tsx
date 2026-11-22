import { useEffect, useState } from 'react'
import { App as AntdApp, Modal, Select, Space, Typography } from 'antd'

import { listTestCases, updateAutomationAsset } from '../api'
import type { AutomationAsset, TestCase } from '../api'
import { errorMessage } from '../api/client'

interface Props {
  open: boolean
  projectId: number
  asset: AutomationAsset | null
  onClose: () => void
  /** 关联变更后回传（父级据此刷新资产表）。 */
  onUpdated: (asset: AutomationAsset) => void
}

/**
 * 关联用例弹窗。
 *
 * **关联是单向的**（资产 → 用例），不回写 08 的用例表；
 * 关联的用例必须**属于本项目**（服务端校验，前端只列本项目的用例）。
 * 选空 = 解绑。
 */
export default function AutomationLinkModal({
  open,
  projectId,
  asset,
  onClose,
  onUpdated,
}: Props) {
  const { message } = AntdApp.useApp()
  const [cases, setCases] = useState<TestCase[]>([])
  const [value, setValue] = useState<number | undefined>(undefined)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) return
    setValue(asset?.linked_case_id ?? undefined)
    listTestCases(projectId, { page_size: 200 })
      .then((page) => setCases(page.items))
      .catch((error) => message.error(errorMessage(error)))
  }, [open, projectId, asset?.linked_case_id, message])

  async function submit() {
    if (!asset) return
    setSaving(true)
    try {
      const updated = await updateAutomationAsset(projectId, asset.id, {
        linked_case_id: value ?? null,
      })
      message.success(value ? '已关联用例' : '已解绑用例')
      onUpdated(updated)
      onClose()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open={open}
      title={asset ? `关联用例 · ${asset.name}` : '关联用例'}
      onCancel={onClose}
      onOk={submit}
      confirmLoading={saving}
      okText="保存"
      cancelText="取消"
      okButtonProps={{ 'data-testid': 'automation-asset-link-confirm-btn' }}
      width={640}
      destroyOnHidden
    >
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <Typography.Text type="secondary">
          关联后，执行报告的追溯链会展示该用例的测试点 / 目标 / 章节；留空表示不关联。
        </Typography.Text>
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="选择要关联的测试用例"
          style={{ width: '100%' }}
          value={value}
          onChange={(next) => setValue(next)}
          options={cases.map((item) => ({ value: item.id, label: `#${item.id} · ${item.title}` }))}
          data-testid="automation-asset-link-select"
        />
      </Space>
    </Modal>
  )
}
