import { useEffect, useState } from 'react'
import { Button, Input, Space, Table, Tooltip, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'

import type { ProcessStep } from '../api'

export interface EditableProcessStep {
  /** 前端自增的临时 key——后端只认数组顺序，不认 id。 */
  key: string
  action: string
  expected: string
}

interface Props {
  /** 只读模式：展示已有步骤，不给编辑控件。 */
  readOnly?: boolean
  /** 已有步骤（只读模式用）。 */
  steps?: ProcessStep[]
  /** 受控的编辑态（编辑模式用）。 */
  value?: EditableProcessStep[]
  onChange?: (next: EditableProcessStep[]) => void
  /** 新增一行时预填的操作文本。 */
  createAction?: string
}

/**
 * 流程基线的步骤编辑器。
 *
 * **照抄 `TestCaseStepsEditor.tsx` 改写**（08 期那一份）——
 * 受控数组 + 上移 / 下移 / 删除 / 新增，**不发 `step_no`**。
 *
 * 保存走整体覆盖（`PUT /scenarios/{id}/steps`）：后端只认数组顺序，
 * 序号由服务端重排为 1..n，所以这里只管维护数组。
 *
 * 顺序调整用「上移 / 下移」按钮而不是拖拽：
 * 拖拽在 antd Table 里要额外引依赖，且无障碍性差——
 * 按钮对键盘与读屏用户都直接可用。
 */
export default function ProcessBaselineStepsEditor({
  readOnly = false,
  steps = [],
  value,
  onChange,
  createAction = '',
}: Props) {
  const [local, setLocal] = useState<EditableProcessStep[]>(value ?? [])

  // 受控：外部换场景时同步本地态（抽屉里切场景，步骤不能串）。
  useEffect(() => {
    if (value !== undefined) setLocal(value)
  }, [value])

  const rows: EditableProcessStep[] = readOnly
    ? steps.map((step, index) => ({
        key: `ro-${index}`,
        action: step.action,
        expected: step.expected,
      }))
    : local

  function update(next: EditableProcessStep[]) {
    setLocal(next)
    onChange?.(next)
  }

  function patch(index: number, field: 'action' | 'expected', text: string) {
    const next = local.map((row, i) => (i === index ? { ...row, [field]: text } : row))
    update(next)
  }

  function addRow() {
    const next = [
      ...local,
      { key: `new-${Date.now()}-${local.length}`, action: createAction, expected: '' },
    ]
    update(next)
  }

  function removeRow(index: number) {
    update(local.filter((_, i) => i !== index))
  }

  function move(index: number, delta: -1 | 1) {
    const target = index + delta
    if (target < 0 || target >= local.length) return
    const next = [...local]
    const [row] = next.splice(index, 1)
    next.splice(target, 0, row)
    update(next)
  }

  const columns: ColumnsType<EditableProcessStep> = [
    {
      title: '序号',
      dataIndex: 'key',
      width: 64,
      render: (_: unknown, __: EditableProcessStep, index: number) => index + 1,
    },
    {
      title: '操作步骤',
      dataIndex: 'action',
      render: (_: unknown, row: EditableProcessStep, index: number) =>
        readOnly ? (
          <span data-testid={`process-baseline-step-action-${index}`}>{row.action}</span>
        ) : (
          <Input
            value={row.action}
            maxLength={1000}
            placeholder="做什么"
            onChange={(event) => patch(index, 'action', event.target.value)}
            data-testid={`process-baseline-step-action-input-${index}`}
          />
        ),
    },
    {
      title: '预期结果',
      dataIndex: 'expected',
      render: (_: unknown, row: EditableProcessStep, index: number) =>
        readOnly ? (
          <span data-testid={`process-baseline-step-expected-${index}`}>
            {row.expected || '—'}
          </span>
        ) : (
          <Input
            value={row.expected}
            maxLength={1000}
            placeholder="可观察到的结果"
            onChange={(event) => patch(index, 'expected', event.target.value)}
            data-testid={`process-baseline-step-expected-input-${index}`}
          />
        ),
    },
    ...(readOnly
      ? []
      : [
          {
            title: '操作',
            key: 'actions',
            width: 132,
            render: (_: unknown, __: EditableProcessStep, index: number) => (
              <Space size={4}>
                <Tooltip title="上移">
                  <Button
                    size="small"
                    disabled={index === 0}
                    onClick={() => move(index, -1)}
                    data-testid={`process-baseline-step-up-${index}`}
                  >
                    上移
                  </Button>
                </Tooltip>
                <Tooltip title="下移">
                  <Button
                    size="small"
                    disabled={index === local.length - 1}
                    onClick={() => move(index, 1)}
                    data-testid={`process-baseline-step-down-${index}`}
                  >
                    下移
                  </Button>
                </Tooltip>
                <Button
                  size="small"
                  danger
                  onClick={() => removeRow(index)}
                  data-testid={`process-baseline-step-remove-${index}`}
                >
                  删除
                </Button>
              </Space>
            ),
          },
        ]),
  ]

  return (
    <div>
      <Table<EditableProcessStep>
        rowKey="key"
        columns={columns}
        dataSource={rows}
        pagination={false}
        size="small"
        locale={{ emptyText: readOnly ? '该场景还没有步骤' : '还没有步骤，点「新增步骤」加一行' }}
        data-testid={readOnly ? 'process-baseline-steps-readonly' : 'process-baseline-steps-editor'}
      />
      {readOnly ? null : (
        <Space style={{ marginTop: 12 }}>
          <Button onClick={addRow} data-testid="process-baseline-step-add-btn">
            新增步骤
          </Button>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            保存时会整体覆盖已有步骤，序号按当前顺序重排。
          </Typography.Text>
        </Space>
      )}
    </div>
  )
}
