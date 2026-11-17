/** 基线树的 7 个弹窗：只负责渲染，开关与提交由容器注入。 */

import { useEffect, useMemo } from 'react'
import { Button, Form, Input, Modal, Select, Space, Tag, Typography } from 'antd'
import type {
  BaselineFunction,
  BaselineLabel,
  BaselineModule,
  BaselineRevision,
  ClearReason,
  LabelType,
} from '../api'
import {
  CLEAR_REASON_META,
  CLEAR_REASON_OPTIONS,
  LABEL_TYPE_META,
  LABEL_TYPE_OPTIONS,
} from './baselineMeta'
import { formatSnapshotVersion } from './baselineShared'
import type { LabelTarget } from './baselineShared'

export interface NameDescFormValues {
  name: string
  description?: string | null
}

export interface LabelFormValues {
  revision_id?: number | null
  label_type: LabelType
}

export interface ClearFormValues {
  clear_reason: ClearReason
  clear_note?: string | null
}

export interface MigrateFormValues {
  target_module_id: number
  function_ids: number[]
}

export interface ModuleDialogState {
  open: boolean
  editing?: BaselineModule
}

export interface FunctionDialogState {
  open: boolean
  moduleId?: number
  editing?: BaselineFunction
}

export interface PointDialogState {
  open: boolean
  functionId?: number
  functionName?: string
}

export interface LabelDialogState {
  open: boolean
  target?: LabelTarget
}

export interface ClearDialogState {
  open: boolean
  label?: BaselineLabel
}

export interface MigrateDialogState {
  open: boolean
  module?: BaselineModule
}

export interface BaselineTreeDialogsProps {
  canWrite: boolean
  modules: BaselineModule[]
  functions: BaselineFunction[]
  revisions: BaselineRevision[]
  entityLabels: BaselineLabel[]
  moduleModal: ModuleDialogState
  functionModal: FunctionDialogState
  pointModal: PointDialogState
  labelModal: LabelDialogState
  clearModal: ClearDialogState
  notEmptyModal: MigrateDialogState
  migrateModal: MigrateDialogState
  onCancelModule: () => void
  onSubmitModule: (values: NameDescFormValues) => Promise<void>
  onCancelFunction: () => void
  onSubmitFunction: (values: NameDescFormValues) => Promise<void>
  onCancelPoint: () => void
  onSubmitPoint: (values: NameDescFormValues) => Promise<void>
  onCloseLabel: () => void
  onSubmitLabel: (values: LabelFormValues) => Promise<void>
  onClearLabel: (label: BaselineLabel) => void
  onCancelClear: () => void
  onSubmitClear: (values: ClearFormValues) => Promise<void>
  onCancelNotEmpty: () => void
  onMigrateFromNotEmpty: (module: BaselineModule) => void
  onDeleteWithFunctions: (module: BaselineModule) => void
  onCancelMigrate: () => void
  onSubmitMigrate: (values: MigrateFormValues) => Promise<void>
}

/** 新增 / 重命名模块。 */
function ModuleFormModal({
  open,
  editing,
  onCancel,
  onSubmit,
}: {
  open: boolean
  editing?: BaselineModule
  onCancel: () => void
  onSubmit: (values: NameDescFormValues) => Promise<void>
}) {
  const [form] = Form.useForm<NameDescFormValues>()

  // 重命名时回填、新增时清空——弹窗自己管自己的表单。
  useEffect(() => {
    if (!open) return
    if (editing) {
      form.setFieldsValue({ name: editing.name, description: editing.description })
    } else {
      form.resetFields()
    }
  }, [open, editing, form])

  async function handleOk() {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    await onSubmit(values)
  }

  return (
    <Modal
      title={editing ? '重命名模块' : '新增模块'}
      open={open}
      onCancel={onCancel}
      onOk={handleOk}
      okText="保存"
      cancelText="取消"
      destroyOnHidden
    >
      <Form form={form} layout="vertical">
        <Form.Item name="name" label="模块名" rules={[{ required: true, message: '请输入模块名' }]}>
          <Input placeholder="如：支付模块" />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <Input.TextArea rows={2} placeholder="选填" />
        </Form.Item>
      </Form>
    </Modal>
  )
}

/** 新增 / 重命名功能。 */
function FunctionFormModal({
  open,
  editing,
  onCancel,
  onSubmit,
}: {
  open: boolean
  editing?: BaselineFunction
  onCancel: () => void
  onSubmit: (values: NameDescFormValues) => Promise<void>
}) {
  const [form] = Form.useForm<NameDescFormValues>()

  useEffect(() => {
    if (!open) return
    if (editing) {
      form.setFieldsValue({ name: editing.name, description: editing.description })
    } else {
      form.resetFields()
    }
  }, [open, editing, form])

  async function handleOk() {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    await onSubmit(values)
  }

  return (
    <Modal
      title={editing ? '重命名功能' : '新增功能'}
      open={open}
      onCancel={onCancel}
      onOk={handleOk}
      okText="保存"
      cancelText="取消"
      destroyOnHidden
    >
      <Form form={form} layout="vertical">
        <Form.Item name="name" label="功能名" rules={[{ required: true, message: '请输入功能名' }]}>
          <Input placeholder="如：提交订单" />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <Input.TextArea rows={2} placeholder="选填" />
        </Form.Item>
      </Form>
    </Modal>
  )
}

/** 新增功能点。 */
function FeaturePointFormModal({
  open,
  functionName,
  onCancel,
  onSubmit,
}: {
  open: boolean
  functionName?: string
  onCancel: () => void
  onSubmit: (values: NameDescFormValues) => Promise<void>
}) {
  const [form] = Form.useForm<NameDescFormValues>()

  useEffect(() => {
    if (!open) return
    form.resetFields()
  }, [open, form])

  async function handleOk() {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    await onSubmit(values)
  }

  return (
    <Modal
      title={`新增功能点 · ${functionName ?? ''}`}
      open={open}
      onCancel={onCancel}
      onOk={handleOk}
      okText="保存"
      cancelText="取消"
      destroyOnHidden
    >
      <Form form={form} layout="vertical">
        <Form.Item
          name="name"
          label="功能点名"
          rules={[{ required: true, message: '请输入功能点名' }]}
        >
          <Input placeholder="如：填写收货地址" />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <Input.TextArea rows={2} placeholder="选填" />
        </Form.Item>
      </Form>
    </Modal>
  )
}

/** 打标 + 已有标签列表（每行可「清除」）。 */
function LabelModal({
  open,
  target,
  canWrite,
  revisions,
  entityLabels,
  snapshotLabel,
  onCancel,
  onSubmit,
  onClear,
}: {
  open: boolean
  target?: LabelTarget
  canWrite: boolean
  revisions: BaselineRevision[]
  entityLabels: BaselineLabel[]
  /** 快照 ID → 版本文案；标签行不暴露内部 ID。 */
  snapshotLabel: (revisionId: number) => string
  onCancel: () => void
  onSubmit: (values: LabelFormValues) => Promise<void>
  onClear: (label: BaselineLabel) => void
}) {
  const [form] = Form.useForm<LabelFormValues>()

  useEffect(() => {
    if (!open) return
    form.resetFields()
  }, [open, form])

  async function handleSubmit() {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    await onSubmit(values)
  }

  return (
    <Modal
      title={`标签 · ${target?.name ?? ''}`}
      open={open}
      onCancel={onCancel}
      footer={null}
      width={560}
    >
      {canWrite && (
        <Form form={form} layout="inline" style={{ marginBottom: 12 }}>
          <Form.Item
            name="revision_id"
            label="基准快照"
            tooltip="标签挂在快照上；审核通过新版本时会把生效标签复制过去"
          >
            <Select
              style={{ width: 150 }}
              placeholder="最新快照"
              allowClear
              options={revisions.map((revision) => ({
                value: revision.id,
                label: formatSnapshotVersion(revision.version_no),
              }))}
            />
          </Form.Item>
          <Form.Item
            name="label_type"
            label="标签类型"
            rules={[{ required: true, message: '请选择标签类型' }]}
          >
            <Select
              data-testid="baseline-label-type"
              style={{ width: 120 }}
              placeholder="标签类型"
              options={LABEL_TYPE_OPTIONS}
            />
          </Form.Item>
          <Form.Item>
            <Button type="primary" data-testid="submit-label" onClick={handleSubmit}>
              打标
            </Button>
          </Form.Item>
        </Form>
      )}

      {revisions.length === 0 && (
        <Typography.Paragraph type="secondary">
          还没有审核通过的快照。标签挂在快照上，先提交并通过一次审核才能打标。
        </Typography.Paragraph>
      )}

      {entityLabels.length === 0 ? (
        <Typography.Text type="secondary">该对象暂无标签记录。</Typography.Text>
      ) : (
        <Space direction="vertical" style={{ width: '100%' }} size={6}>
          {entityLabels.map((label) => (
            <Space key={label.id} size={8}>
              <Tag color={LABEL_TYPE_META[label.label_type].color}>
                {LABEL_TYPE_META[label.label_type].label}
              </Tag>
              <Typography.Text type="secondary">
                快照 {snapshotLabel(label.revision_id)}
              </Typography.Text>
              {label.status === 'cleared' ? (
                <Tag>已清除 · {CLEAR_REASON_META[label.clear_reason ?? 'other']}</Tag>
              ) : (
                canWrite && (
                  <Button
                    size="small"
                    danger
                    data-testid={`clear-label-${label.id}`}
                    onClick={() => onClear(label)}
                  >
                    清除
                  </Button>
                )
              )}
            </Space>
          ))}
        </Space>
      )}
    </Modal>
  )
}

/** 清除原因（6 类枚举，选「其他」必须填备注）。 */
function ClearLabelModal({
  open,
  onCancel,
  onSubmit,
}: {
  open: boolean
  onCancel: () => void
  onSubmit: (values: ClearFormValues) => Promise<void>
}) {
  const [form] = Form.useForm<ClearFormValues>()

  useEffect(() => {
    if (!open) return
    form.resetFields()
  }, [open, form])

  async function handleOk() {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    await onSubmit(values)
  }

  return (
    <Modal
      title="清除标签"
      open={open}
      onCancel={onCancel}
      onOk={handleOk}
      okText="清除"
      cancelText="取消"
      destroyOnHidden
    >
      <Form form={form} layout="vertical">
        <Form.Item
          name="clear_reason"
          label="清除原因"
          rules={[{ required: true, message: '请选择清除原因' }]}
        >
          <Select
            data-testid="baseline-clear-reason"
            placeholder="选择原因"
            options={CLEAR_REASON_OPTIONS}
          />
        </Form.Item>
        <Form.Item
          noStyle
          shouldUpdate={(prev, next) => prev.clear_reason !== next.clear_reason}
        >
          {({ getFieldValue }) =>
            getFieldValue('clear_reason') === 'other' ? (
              <Form.Item
                name="clear_note"
                label="备注"
                rules={[{ required: true, message: '原因为「其他」时必须填写备注' }]}
              >
                <Input.TextArea rows={2} />
              </Form.Item>
            ) : null
          }
        </Form.Item>
      </Form>
    </Modal>
  )
}

/** 批量迁移功能到另一个模块。 */
function MigrateModal({
  open,
  module,
  modules,
  functions,
  onCancel,
  onSubmit,
}: {
  open: boolean
  module?: BaselineModule
  modules: BaselineModule[]
  functions: BaselineFunction[]
  onCancel: () => void
  onSubmit: (values: MigrateFormValues) => Promise<void>
}) {
  const [form] = Form.useForm<MigrateFormValues>()

  useEffect(() => {
    if (!open) return
    form.resetFields()
  }, [open, form])

  async function handleOk() {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    await onSubmit(values)
  }

  return (
    <Modal
      title={`迁移功能 · ${module?.name ?? ''}`}
      open={open}
      onCancel={onCancel}
      onOk={handleOk}
      okText="迁移"
      cancelText="取消"
      destroyOnHidden
    >
      <Form form={form} layout="vertical">
        <Form.Item
          name="target_module_id"
          label="目标模块"
          rules={[{ required: true, message: '请选择目标模块' }]}
        >
          <Select
            data-testid="baseline-migrate-target-module"
            placeholder="选择目标模块"
            options={modules
              .filter((option) => option.id !== module?.id)
              .map((option) => ({ value: option.id, label: option.name }))}
          />
        </Form.Item>
        <Form.Item
          name="function_ids"
          label="要迁移的功能"
          rules={[{ required: true, message: '请选择功能' }]}
        >
          <Select
            data-testid="baseline-migrate-functions"
            mode="multiple"
            placeholder="选择功能"
            options={functions
              .filter((fn) => fn.module_id === module?.id)
              .map((fn) => ({ value: fn.id, label: fn.name }))}
          />
        </Form.Item>
      </Form>
    </Modal>
  )
}

/** AC-64：模块下还有功能时给「迁移功能」「删除功能并删除模块」两个入口。 */
function NotEmptyModal({
  open,
  module,
  functionCount,
  onCancel,
  onMigrate,
  onDeleteWithFunctions,
}: {
  open: boolean
  module?: BaselineModule
  /** 该模块下的功能数。 */
  functionCount: number
  onCancel: () => void
  onMigrate: (module: BaselineModule) => void
  onDeleteWithFunctions: (module: BaselineModule) => void
}) {
  return (
    <Modal
      title="模块下还有功能"
      open={open}
      onCancel={onCancel}
      footer={null}
      width={480}
    >
      <Typography.Paragraph>
        模块「{module?.name ?? ''}」下还有 {functionCount} 个功能，删掉模块会连带影响它们。请先选一种处理方式：
      </Typography.Paragraph>
      <Space>
        <Button type="primary" data-testid="not-empty-migrate" onClick={() => module && onMigrate(module)}>
          迁移功能
        </Button>
        <Button
          danger
          data-testid="not-empty-delete-functions"
          onClick={() => module && onDeleteWithFunctions(module)}
        >
          删除功能并删除模块
        </Button>
      </Space>
    </Modal>
  )
}

export function BaselineTreeDialogs({
  canWrite,
  modules,
  functions,
  revisions,
  entityLabels,
  moduleModal,
  functionModal,
  pointModal,
  labelModal,
  clearModal,
  notEmptyModal,
  migrateModal,
  onCancelModule,
  onSubmitModule,
  onCancelFunction,
  onSubmitFunction,
  onCancelPoint,
  onSubmitPoint,
  onCloseLabel,
  onSubmitLabel,
  onClearLabel,
  onCancelClear,
  onSubmitClear,
  onCancelNotEmpty,
  onMigrateFromNotEmpty,
  onDeleteWithFunctions,
  onCancelMigrate,
  onSubmitMigrate,
}: BaselineTreeDialogsProps) {
  /** 快照 ID → 版本文案。标签行不暴露内部 ID，用户只认版本号。 */
  const revisionVersionMap = useMemo(() => {
    const map = new Map<number, string>()
    for (const revision of revisions) {
      map.set(revision.id, formatSnapshotVersion(revision.version_no))
    }
    return map
  }, [revisions])

  function snapshotLabel(revisionId: number): string {
    return revisionVersionMap.get(revisionId) ?? '未知快照'
  }

  const notEmptyFunctionCount = notEmptyModal.module
    ? functions.filter((fn) => fn.module_id === notEmptyModal.module?.id).length
    : 0

  return (
    <>
      {/* 模块 */}
      <ModuleFormModal
        open={moduleModal.open}
        editing={moduleModal.editing}
        onCancel={onCancelModule}
        onSubmit={onSubmitModule}
      />

      {/* 功能 */}
      <FunctionFormModal
        open={functionModal.open}
        editing={functionModal.editing}
        onCancel={onCancelFunction}
        onSubmit={onSubmitFunction}
      />

      {/* 功能点 */}
      <FeaturePointFormModal
        open={pointModal.open}
        functionName={pointModal.functionName}
        onCancel={onCancelPoint}
        onSubmit={onSubmitPoint}
      />

      {/* 打标 / 清除 */}
      <LabelModal
        open={labelModal.open}
        target={labelModal.target}
        canWrite={canWrite}
        revisions={revisions}
        entityLabels={entityLabels}
        snapshotLabel={snapshotLabel}
        onCancel={onCloseLabel}
        onSubmit={onSubmitLabel}
        onClear={onClearLabel}
      />

      {/* 清除原因 */}
      <ClearLabelModal open={clearModal.open} onCancel={onCancelClear} onSubmit={onSubmitClear} />

      {/* 模块下还有功能：给「迁移功能」「删除功能」两个入口（AC-64） */}
      <NotEmptyModal
        open={notEmptyModal.open}
        module={notEmptyModal.module}
        functionCount={notEmptyFunctionCount}
        onCancel={onCancelNotEmpty}
        onMigrate={onMigrateFromNotEmpty}
        onDeleteWithFunctions={onDeleteWithFunctions}
      />

      {/* 批量迁移 */}
      <MigrateModal
        open={migrateModal.open}
        module={migrateModal.module}
        modules={modules}
        functions={functions}
        onCancel={onCancelMigrate}
        onSubmit={onSubmitMigrate}
      />
    </>
  )
}
