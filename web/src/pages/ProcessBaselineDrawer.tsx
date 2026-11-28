import { useEffect, useState } from 'react'
import type React from 'react'
import {
  App as AntdApp,
  Alert,
  Button,
  Drawer,
  Form,
  Input,
  Select,
  Space,
  Table,
  Typography,
} from 'antd'

import {
  createProcessScenarios,
  listProcessLinkableTargets,
  replaceProcessLinks,
  replaceProcessSteps,
  updateProcessScenario,
} from '../api'
import type { ProcessLink, ProcessLinkableTarget, ProcessScenario } from '../api'
import { errorMessage } from '../api/client'
import ProcessBaselineStepsEditor from './ProcessBaselineStepsEditor'
import type { EditableProcessStep } from './ProcessBaselineStepsEditor'
import {
  buildProcessLinkColumns,
  ProcessLinkSelect,
  ProcessScenarioMetaView,
} from './processBaselineColumns'
import { IN_REVIEW_TIP } from './processBaselineMeta'

interface Props {
  open: boolean
  projectId: number
  /** `create` = 新建场景（空表单）；`detail` = 详情 / 编辑既有场景。 */
  mode: 'create' | 'detail'
  scenario: ProcessScenario | null
  /** 写操作限项目管理员（后端 403 NOT_PROJECT_ADMIN）。 */
  canManage: boolean
  /** 审核期锁定：项目内有审核中的快照时写入口禁用（后端 409）。 */
  inReview: boolean
  onClose: () => void
  /** 详情模式下场景变化后回传（父级据此刷新列表）。 */
  onUpdated?: (scenario: ProcessScenario) => void
  /** 新建成功后回传。 */
  onCreated?: () => void
}

function targetValue(target: ProcessLinkableTarget): string {
  return `${target.target_type}:${target.target_id}`
}

/**
 * 流程基线场景抽屉：**新建**与**详情 / 编辑**共用一个组件。
 *
 * 两种模式的 UI 完全相同（表单 + 步骤 + 关联），差别只在：
 * - 初始值（新建是空的，详情是库里���）；
 * - 保存动作（新建走 `POST /scenarios`，详情走 `PATCH` + 两个 `PUT`）；
 * - 底部按钮（「创建」/「保存」）。
 *
 * 三块内容在详情模式下都能改完：
 * - 元数据 → `PATCH`（名称 / 描述 / 前置条件 / 状态）；
 * - 步骤 → `PUT .../steps`（**整体覆盖**，不发 `step_no`）；
 * - 关联 → `PUT .../links`（**整体覆盖**，空数组合法）。
 *
 * **默认只读**：点「编辑」才进编辑态，保存后回到只读态——
 * 用户能立刻看到「存进去是什么样」（只读表里的顺序与库里一致，
 * 服务端按数组顺序重排了序号）。
 */
export default function ProcessBaselineDrawer({
  open,
  projectId,
  mode,
  scenario,
  canManage,
  inReview,
  onClose,
  onUpdated,
  onCreated,
}: Props) {
  const { message } = AntdApp.useApp()
  const [form] = Form.useForm<{
    name: string
    description?: string
    precondition?: string
    status: 'active' | 'archived'
  }>()

  const isCreate = mode === 'create'
  const [editing, setEditing] = useState(isCreate)
  const [saving, setSaving] = useState(false)
  const [stepRows, setStepRows] = useState<EditableProcessStep[]>([])
  const [linkRows, setLinkRows] = useState<ProcessLink[]>([])
  const [pendingTargets, setPendingTargets] = useState<string[]>([])
  const [targets, setTargets] = useState<ProcessLinkableTarget[]>([])
  /** 可关联目标是否还在加载（加载期间下拉置 loading + disabled，见 `ProcessLinkSelect`）。 */
  const [loadingTargets, setLoadingTargets] = useState(false)

  const locked = inReview && canManage && !isCreate

  /** 编辑态回到「库里现在是什么样」——取消编辑与打开抽屉时都调它。 */
  function resetToServer() {
    if (!scenario) return
    setStepRows(
      (scenario.steps ?? []).map((step, index) => ({
        key: `s${index}`,
        action: step.action,
        expected: step.expected,
      })),
    )
    setLinkRows(scenario.links ?? [])
    setPendingTargets([])
  }

  useEffect(() => {
    if (!open) return
    if (isCreate) {
      form.setFieldsValue({
        name: '',
        description: '',
        precondition: '',
        status: 'active',
      })
      // 新建时**先给一行空步骤**——否则步骤表是空的，
      // 用户得先点「新增步骤」才知道这里能填（08 期同一口径）。
      setStepRows([{ key: 's0', action: '', expected: '' }])
      setLinkRows([])
      setPendingTargets([])
      setEditing(true)
      return
    }
    if (!scenario) return
    form.setFieldsValue({
      name: scenario.name,
      description: scenario.description ?? '',
      precondition: scenario.precondition ?? '',
      status: scenario.status,
    })
    resetToServer()
    setEditing(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, scenario, form, isCreate])

  useEffect(() => {
    if (!open || !canManage) return
    // 先清空再拉取：重新打开抽屉时不会短暂显示上次的（可能是别的项目的）目标。
    setTargets([])
    setLoadingTargets(true)
    listProcessLinkableTargets(projectId)
      .then(setTargets)
      .catch((error) => message.error(errorMessage(error)))
      .finally(() => setLoadingTargets(false))
  }, [open, canManage, projectId, message])

  /** 把下拉里选中的目标并入已选列表（同一目标不重复）。 */
  function confirmLinks() {
    const picked = targets.filter((target) => pendingTargets.includes(targetValue(target)))
    setLinkRows((prev) => {
      const known = new Set(prev.map((row) => `${row.target_type}:${row.target_id}`))
      const added = picked
        .filter((target) => !known.has(targetValue(target)))
        .map((target) => ({
          target_type: target.target_type,
          target_id: target.target_id,
          target_name: target.target_name,
          target_deleted: false,
        }))
      return [...prev, ...added]
    })
    setPendingTargets([])
  }

  async function save() {
    let values: {
      name: string
      description?: string
      precondition?: string
      status: 'active' | 'archived'
    }
    try {
      values = await form.validateFields()
    } catch (error) {
      // 表单校验失败：提示由表单就地渲染，不弹「请求失败」。
      if (error && typeof error === 'object' && 'errorFields' in error) return
      throw error
    }
    const steps = stepRows
      .map((row) => ({ action: row.action.trim(), expected: row.expected.trim() }))
      .filter((row) => row.action)
    if (!steps.length) {
      message.warning('至少要保留一个步骤（操作不能为空）')
      return
    }
    const links = linkRows.map((row) => ({
      target_type: row.target_type,
      target_id: row.target_id,
    }))

    setSaving(true)
    try {
      if (isCreate || !scenario) {
        // **批量**接口——这里只提交一条（反推候选的采纳也走同一个入口）。
        const result = await createProcessScenarios(projectId, [
          {
            name: values.name.trim(),
            description: values.description ?? '',
            precondition: values.precondition ?? '',
            // 手工添加**不做追溯要求**：六列追溯字段服务端强制置 NULL。
            source_type: 'manual',
            steps,
            links,
          },
        ])
        message.success(`已创建 ${result.created} 个场景`)
        onCreated?.()
        onClose()
        return
      }
      let latest = await updateProcessScenario(projectId, scenario.id, {
        name: values.name.trim(),
        description: values.description ?? '',
        precondition: values.precondition ?? '',
        status: values.status,
      })
      latest = await replaceProcessSteps(projectId, scenario.id, steps)
      latest = await replaceProcessLinks(projectId, scenario.id, links)
      message.success('场景已保存')
      setEditing(false)
      onUpdated?.(latest)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  const linkColumns = buildProcessLinkColumns({
    editing,
    onRemove: (index) => setLinkRows((prev) => prev.filter((_, i) => i !== index)),
  })

  return (
    <Drawer
      title={
        isCreate
          ? '新建流程基线场景'
          : scenario
            ? `流程基线场景 #${scenario.id}`
            : '流程基线场景'
      }
      width={900}
      open={open}
      onClose={onClose}
    >
      <Space
        direction="vertical"
        size={16}
        style={{ width: '100%' }}
        data-testid="process-baseline-drawer"
      >
        {locked ? <Alert type="warning" showIcon message={IN_REVIEW_TIP} /> : null}

        {editing ? (
          <Form
            form={form}
            layout="vertical"
            requiredMark={false}
            data-testid="process-baseline-meta-form"
          >
            <Form.Item
              name="name"
              label="场景名称"
              rules={[{ required: true, message: '请输入场景名称' }]}
            >
              <Input maxLength={255} data-testid="process-baseline-name-input" />
            </Form.Item>
            <Form.Item name="description" label="描述">
              <Input.TextArea rows={2} maxLength={500} data-testid="process-baseline-desc-input" />
            </Form.Item>
            <Form.Item name="precondition" label="前置条件">
              <Input.TextArea
                rows={2}
                maxLength={1000}
                data-testid="process-baseline-precondition-input"
              />
            </Form.Item>
            {!isCreate ? (
              <Form.Item name="status" label="状态">
                <Select
                  options={[
                    { value: 'active', label: '在用' },
                    { value: 'archived', label: '已归档' },
                  ]}
                  data-testid="process-baseline-status-select"
                />
              </Form.Item>
            ) : null}
          </Form>
        ) : scenario ? (
          <ProcessScenarioMetaView scenario={scenario} />
        ) : null}

        <div>
          <Typography.Text strong>操作步骤与预期结果</Typography.Text>
          <div style={{ marginTop: 8 }}>
            {editing ? (
              <ProcessBaselineStepsEditor value={stepRows} onChange={setStepRows} />
            ) : (
              <ProcessBaselineStepsEditor readOnly steps={scenario?.steps ?? []} />
            )}
          </div>
        </div>

        <div>
          <Space style={{ marginBottom: 8 }}>
            <Typography.Text strong>关联功能基线</Typography.Text>
            {editing ? (
              <Space>
                <ProcessLinkSelect
                  targets={targets}
                  value={pendingTargets}
                  onChange={setPendingTargets}
                  testId="process-baseline-link-select"
                  loading={loadingTargets}
                />
                <Button
                  size="small"
                  disabled={!pendingTargets.length}
                  onClick={confirmLinks}
                  data-testid="process-baseline-link-confirm-btn"
                >
                  加入关联
                </Button>
              </Space>
            ) : null}
          </Space>
          <Table<ProcessLink>
            rowKey={(row) => `${row.target_type}:${row.target_id}`}
            size="small"
            columns={linkColumns}
            dataSource={linkRows}
            pagination={false}
            locale={{ emptyText: '还没有关联功能基线' }}
            data-testid="process-baseline-links-table"
            onRow={(_: unknown, index?: number) =>
              ({
                'data-testid': `process-baseline-link-row-${index ?? 0}`,
              }) as React.HTMLAttributes<HTMLElement>
            }
          />
        </div>

        {canManage ? (
          <Space>
            {editing ? (
              <>
                <Button
                  type="primary"
                  loading={saving}
                  disabled={locked}
                  onClick={() => void save()}
                  data-testid="process-baseline-save-btn"
                >
                  {isCreate ? '创建' : '保存'}
                </Button>
                {!isCreate ? (
                  <Button
                    onClick={() => {
                      setEditing(false)
                      resetToServer()
                    }}
                    data-testid="process-baseline-cancel-btn"
                  >
                    取消
                  </Button>
                ) : null}
              </>
            ) : (
              <Button
                type="primary"
                disabled={locked}
                onClick={() => setEditing(true)}
                data-testid="process-baseline-drawer-edit-btn"
              >
                编辑
              </Button>
            )}
          </Space>
        ) : (
          <Typography.Text type="secondary">
            只有项目管理员可以编辑流程基线场景，你可以查看内容。
          </Typography.Text>
        )}
      </Space>
    </Drawer>
  )
}
