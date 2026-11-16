import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Tag,
  Tree,
  Typography,
  message,
} from 'antd'
import type { DataNode } from 'antd/es/tree'
import {
  clearBaselineLabel,
  createBaselineFeaturePoint,
  createBaselineFunction,
  createBaselineLabel,
  createBaselineModule,
  deleteBaselineFeaturePoint,
  deleteBaselineFunction,
  deleteBaselineModule,
  listBaselineFeaturePoints,
  listBaselineFunctions,
  listBaselineLabels,
  listBaselineModules,
  listBaselineRevisions,
  migrateBaselineFunctions,
  updateBaselineFunction,
  updateBaselineModule,
} from '../api'
import type {
  BaselineFeaturePoint,
  BaselineFunction,
  BaselineLabel,
  BaselineModule,
  BaselineRevision,
  ClearReason,
  LabelType,
} from '../api'
import { errorCode, errorMessage } from '../api/client'
import { formatSnapshotVersion, isValidationError } from './baselineShared'

/** 标签类型 → 中文与颜色（功能级 / 功能点级通用，互不汇总）。 */
export const LABEL_TYPE_META: Record<LabelType, { label: string; color: string }> = {
  new: { label: '新增', color: 'green' },
  changed: { label: '变更', color: 'orange' },
  affected: { label: '受影响', color: 'gold' },
  unchanged: { label: '无变化', color: 'default' },
}

/** 清除原因 → 中文说明（6 类枚举，后端强校验）。 */
export const CLEAR_REASON_META: Record<ClearReason, string> = {
  requirement_done: '需求已实现',
  requirement_cancelled: '需求已取消',
  misjudged: '之前判断有误',
  priority_changed: '优先级变化',
  duplicate_label: '标签重复',
  other: '其他',
}

interface LabelTarget {
  targetType: 'function' | 'feature_point'
  targetId: number
  name: string
}

interface Props {
  projectId: number
  /** 写操作限项目管理员（后端 403 NOT_PROJECT_ADMIN）。 */
  canWrite: boolean
}

export default function ProjectBaselineTree({ projectId, canWrite }: Props) {
  const [modules, setModules] = useState<BaselineModule[]>([])
  const [functions, setFunctions] = useState<BaselineFunction[]>([])
  const [revisions, setRevisions] = useState<BaselineRevision[]>([])
  const [points, setPoints] = useState<Record<number, BaselineFeaturePoint[]>>({})
  const [keyword, setKeyword] = useState('')
  const [labelType, setLabelType] = useState<string | undefined>()
  const [sourceType, setSourceType] = useState<string | undefined>()

  const [moduleModal, setModuleModal] = useState<{
    open: boolean
    editing?: BaselineModule
  }>({ open: false })
  const [functionModal, setFunctionModal] = useState<{
    open: boolean
    moduleId?: number
    editing?: BaselineFunction
  }>({ open: false })
  const [pointModal, setPointModal] = useState<{
    open: boolean
    functionId?: number
    functionName?: string
    editing?: BaselineFeaturePoint
  }>({ open: false })
  const [labelModal, setLabelModal] = useState<{ open: boolean; target?: LabelTarget }>({
    open: false,
  })
  const [clearModal, setClearModal] = useState<{ open: boolean; label?: BaselineLabel }>({
    open: false,
  })
  const [migrateModal, setMigrateModal] = useState<{
    open: boolean
    module?: BaselineModule
  }>({ open: false })
  /** AC-64：模块下还有功能时不给删，给「迁移功能」「删除功能」两个入口。 */
  const [notEmptyModal, setNotEmptyModal] = useState<{
    open: boolean
    module?: BaselineModule
  }>({ open: false })

  const [moduleForm] = Form.useForm()
  const [functionForm] = Form.useForm()
  const [pointForm] = Form.useForm()
  const [labelForm] = Form.useForm()
  const [clearForm] = Form.useForm()
  const [migrateForm] = Form.useForm()

  /**
   * 模块层默认展开（功能行直接可见），功能点按需懒加载：
   * 展开功能节点时 rc-tree 触发 loadData，把功能点拉回来。
   *
   * rc-tree 的 `defaultExpandAll` 只在首次渲染生效，而 treeData 是异步回来的，
   * 所以这里自己管 `expandedKeys`；用户手动收起的模块记在 collapsedRef 里，
   * reload 后不再被强行展开。
   */
  const [expandedKeys, setExpandedKeys] = useState<string[]>([])
  const collapsedRef = useRef<Set<string>>(new Set())

  const reload = useCallback(async () => {
    const [modulePage, functionPage] = await Promise.all([
      listBaselineModules(projectId, { page_size: 200 }),
      listBaselineFunctions(projectId, { page_size: 200 }),
    ])
    setModules(modulePage.items)
    setFunctions(functionPage.items)
    // 模块默认展开；功能节点的展开状态跨 reload 保留
    const functionKeys = new Set(functionPage.items.map((fn) => `f-${fn.id}`))
    setExpandedKeys((prev) => {
      const next = new Set(
        prev.filter((key) => key.startsWith('f-') && functionKeys.has(key)),
      )
      for (const module of modulePage.items) {
        const key = `m-${module.id}`
        if (!collapsedRef.current.has(key)) next.add(key)
      }
      return [...next]
    })
  }, [projectId])

  const reloadRevisions = useCallback(async () => {
    const page = await listBaselineRevisions(projectId, {
      status: 'approved',
      page_size: 200,
    })
    setRevisions(page.items)
  }, [projectId])

  useEffect(() => {
    reload().catch((error) => message.error(errorMessage(error)))
    reloadRevisions().catch((error) => message.error(errorMessage(error)))
  }, [reload, reloadRevisions])

  /** 筛选只作用于功能层；模块骨架保留，便于看清归属。 */
  const visibleFunctions = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    return functions.filter((fn) => {
      if (sourceType && fn.source_type !== sourceType) return false
      if (labelType && !fn.label_types.includes(labelType as LabelType)) return false
      if (kw && !fn.name.toLowerCase().includes(kw)) return false
      return true
    })
  }, [functions, keyword, labelType, sourceType])

  async function loadPoints(functionId: number) {
    if (points[functionId]) return
    try {
      const list = await listBaselineFeaturePoints(projectId, functionId)
      setPoints((prev) => ({ ...prev, [functionId]: list }))
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  /* --------------------------------------------------------------- 写操作 */

  async function submitModule() {
    try {
      const values = await moduleForm.validateFields()
      if (moduleModal.editing) {
        await updateBaselineModule(projectId, moduleModal.editing.id, {
          name: values.name,
          description: values.description ?? null,
        })
        message.success('模块已更新')
      } else {
        await createBaselineModule(projectId, {
          name: values.name,
          description: values.description ?? null,
        })
        message.success('模块已创建')
      }
      setModuleModal({ open: false })
      await reload()
    } catch (error) {
      if (isValidationError(error)) return
      message.error(errorMessage(error))
    }
  }

  async function submitFunction() {
    if (!functionModal.moduleId) return
    try {
      const values = await functionForm.validateFields()
      if (functionModal.editing) {
        await updateBaselineFunction(projectId, functionModal.editing.id, {
          name: values.name,
          description: values.description ?? null,
        })
        message.success('功能已更新')
      } else {
        await createBaselineFunction(projectId, {
          module_id: functionModal.moduleId,
          name: values.name,
          description: values.description ?? null,
        })
        message.success('功能已创建')
      }
      setFunctionModal({ open: false })
      await reload()
    } catch (error) {
      if (isValidationError(error)) return
      message.error(errorMessage(error))
    }
  }

  async function submitPoint() {
    if (!pointModal.functionId) return
    const functionId = pointModal.functionId
    try {
      const values = await pointForm.validateFields()
      await createBaselineFeaturePoint(projectId, functionId, {
        name: values.name,
        description: values.description ?? null,
      })
      message.success('功能点已创建')
      setPointModal({ open: false })
      const list = await listBaselineFeaturePoints(projectId, functionId)
      setPoints((prev) => ({ ...prev, [functionId]: list }))
      await reload()
    } catch (error) {
      if (isValidationError(error)) return
      message.error(errorMessage(error))
    }
  }

  async function removeModule(module: BaselineModule) {
    try {
      const result = await deleteBaselineModule(projectId, module.id)
      message.success(result.warning ?? '模块已删除')
      await reload()
    } catch (error) {
      if (errorCode(error) === 'MODULE_NOT_EMPTY') {
        // 409：模块下还有功能。给两个入口而不是一句「删不掉」。
        setNotEmptyModal({ open: true, module })
        return
      }
      message.error(errorMessage(error))
    }
  }

  /** AC-64：把模块下所有功能一并删掉，再删模块本身。 */
  async function removeModuleWithFunctions(module: BaselineModule) {
    const children = functions.filter((fn) => fn.module_id === module.id)
    try {
      for (const fn of children) {
        await deleteBaselineFunction(projectId, fn.id)
      }
      const result = await deleteBaselineModule(projectId, module.id)
      message.success(result.warning ?? '模块已删除')
      setNotEmptyModal({ open: false })
      setPoints((prev) => {
        const next = { ...prev }
        for (const fn of children) delete next[fn.id]
        return next
      })
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  async function removeFunction(fn: BaselineFunction) {
    try {
      const result = await deleteBaselineFunction(projectId, fn.id)
      message.success(result.warning ?? '功能已删除')
      setPoints((prev) => {
        const next = { ...prev }
        delete next[fn.id]
        return next
      })
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  async function removePoint(point: BaselineFeaturePoint, functionId: number) {
    try {
      const result = await deleteBaselineFeaturePoint(projectId, point.id)
      message.success(result.warning ?? '功能点已删除')
      const list = await listBaselineFeaturePoints(projectId, functionId)
      setPoints((prev) => ({ ...prev, [functionId]: list }))
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  async function submitLabel() {
    if (!labelModal.target) return
    try {
      const values = await labelForm.validateFields()
      await createBaselineLabel(projectId, {
        revision_id: values.revision_id ?? null,
        target_type: labelModal.target.targetType,
        target_id: labelModal.target.targetId,
        label_type: values.label_type,
      })
      message.success('标签已打上')
      labelForm.resetFields()
      setLabelModal({ open: false })
      await reload()
      await reloadLabels()
    } catch (error) {
      if (isValidationError(error)) return
      message.error(errorMessage(error))
    }
  }

  async function submitClear() {
    if (!clearModal.label) return
    try {
      const values = await clearForm.validateFields()
      await clearBaselineLabel(projectId, clearModal.label.id, {
        clear_reason: values.clear_reason,
        clear_note: values.clear_note ?? null,
      })
      message.success('标签已清除，历史留痕')
      setClearModal({ open: false })
      await reloadLabels()
      await reload()
    } catch (error) {
      if (isValidationError(error)) return
      message.error(errorMessage(error))
    }
  }

  async function submitMigrate() {
    if (!migrateModal.module) return
    try {
      const values = await migrateForm.validateFields()
      await migrateBaselineFunctions(
        projectId,
        migrateModal.module.id,
        values.target_module_id,
        values.function_ids,
      )
      message.success('功能已迁移')
      setMigrateModal({ open: false })
      await reload()
    } catch (error) {
      if (isValidationError(error)) return
      message.error(errorMessage(error))
    }
  }

  /* ------------------------------------------------------------ 标签面板 */

  const [entityLabels, setEntityLabels] = useState<BaselineLabel[]>([])

  async function reloadLabels() {
    if (!labelModal.target) {
      setEntityLabels([])
      return
    }
    try {
      const page = await listBaselineLabels(projectId, {
        target_type: labelModal.target.targetType,
        target_id: labelModal.target.targetId,
        status: 'all',
        page_size: 200,
      })
      setEntityLabels(page.items)
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  async function openLabels(target: LabelTarget) {
    setLabelModal({ open: true, target })
    labelForm.resetFields()
    try {
      const page = await listBaselineLabels(projectId, {
        target_type: target.targetType,
        target_id: target.targetId,
        status: 'all',
        page_size: 200,
      })
      setEntityLabels(page.items)
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  /* --------------------------------------------------------------- 渲染 */

  function labelTags(types: LabelType[]) {
    if (!types.length) return null
    return (
      <Space size={4} wrap>
        {types.map((type) => (
          <Tag key={type} color={LABEL_TYPE_META[type].color}>
            {LABEL_TYPE_META[type].label}
          </Tag>
        ))}
      </Space>
    )
  }

  const treeData = useMemo<DataNode[]>(() => {
    return modules.map((module) => ({
      key: `m-${module.id}`,
      title: (
        <Space size={6} wrap>
          <Typography.Text strong>{module.name}</Typography.Text>
          <Tag>{module.function_count} 个功能</Tag>
          {canWrite && (
            <Space size={0}>
              <Button
                type="link"
                size="small"
                data-testid={`add-function-${module.id}`}
                onClick={(event) => {
                  event.stopPropagation()
                  functionForm.resetFields()
                  setFunctionModal({ open: true, moduleId: module.id })
                }}
              >
                新增功能
              </Button>
              <Button
                type="link"
                size="small"
                onClick={(event) => {
                  event.stopPropagation()
                  moduleForm.setFieldsValue({
                    name: module.name,
                    description: module.description,
                  })
                  setModuleModal({ open: true, editing: module })
                }}
              >
                重命名
              </Button>
              <Button
                type="link"
                size="small"
                data-testid={`migrate-${module.id}`}
                onClick={(event) => {
                  event.stopPropagation()
                  migrateForm.resetFields()
                  setMigrateModal({ open: true, module })
                }}
              >
                迁移功能
              </Button>
              <Popconfirm
                title="删除该模块？"
                description="模块下若还有功能，需要先迁移或删除功能。"
                okText="删除"
                cancelText="取消"
                onConfirm={() => removeModule(module)}
              >
                <Button
                  type="link"
                  size="small"
                  danger
                  data-testid={`delete-module-${module.id}`}
                  onClick={(event) => event.stopPropagation()}
                >
                  删除
                </Button>
              </Popconfirm>
            </Space>
          )}
        </Space>
      ),
      children: visibleFunctions
        .filter((fn) => fn.module_id === module.id)
        .map((fn) => {
          const children = points[fn.id]
          return {
            key: `f-${fn.id}`,
            title: (
              <Space size={6} wrap>
                <Typography.Text>{fn.name}</Typography.Text>
                <Tag color="blue">第 {fn.version_no} 版</Tag>
                {/* AC-63：来源只展示，不可编辑 */}
                <Tag color={fn.source_type === 'manual' ? 'default' : 'cyan'}>
                  {fn.source_type === 'manual' ? '手工' : '文档解析'}
                </Tag>
                {fn.moved_from_module_id && (
                  // AC-65：迁移过的功能保留来源模块
                  <Tag color="purple">
                    来自{modules.find((m) => m.id === fn.moved_from_module_id)?.name ?? '原模块'}
                  </Tag>
                )}
                {labelTags(fn.label_types)}
                {fn.feature_point_label_count > 0 && !fn.label_types.length && (
                  <Tag color="warning">
                    功能点有 {fn.feature_point_label_count} 个标签
                  </Tag>
                )}
                {canWrite && (
                  <Space size={0}>
                    <Button
                      type="link"
                      size="small"
                      data-testid={`add-point-${fn.id}`}
                      onClick={(event) => {
                        event.stopPropagation()
                        pointForm.resetFields()
                        setPointModal({
                          open: true,
                          functionId: fn.id,
                          functionName: fn.name,
                        })
                      }}
                    >
                      新增功能点
                    </Button>
                    <Button
                      type="link"
                      size="small"
                      data-testid={`labels-${fn.id}`}
                      onClick={(event) => {
                        event.stopPropagation()
                        openLabels({
                          targetType: 'function',
                          targetId: fn.id,
                          name: fn.name,
                        })
                      }}
                    >
                      标签
                    </Button>
                    <Popconfirm
                      title="删除该功能？"
                      okText="删除"
                      cancelText="取消"
                      onConfirm={() => removeFunction(fn)}
                    >
                      <Button
                        type="link"
                        size="small"
                        danger
                        onClick={(event) => event.stopPropagation()}
                      >
                        删除
                      </Button>
                    </Popconfirm>
                  </Space>
                )}
              </Space>
            ),
            isLeaf: Boolean(children) && children.length === 0,
            children: children?.map((point) => ({
              key: `p-${point.id}`,
              title: (
                <Space size={6} wrap>
                  <Typography.Text type="secondary">{point.name}</Typography.Text>
                  {/* AC-63：来源只展示，不可编辑 */}
                  <Tag color={point.source_type === 'manual' ? 'default' : 'cyan'}>
                    {point.source_type === 'manual' ? '手工' : '文档解析'}
                  </Tag>
                  {labelTags(point.label_types)}
                  {canWrite && (
                    <Space size={0}>
                      <Button
                        type="link"
                        size="small"
                        data-testid={`labels-${point.id}`}
                        onClick={(event) => {
                          event.stopPropagation()
                          openLabels({
                            targetType: 'feature_point',
                            targetId: point.id,
                            name: point.name,
                          })
                        }}
                      >
                        标签
                      </Button>
                      <Popconfirm
                        title="删除该功能点？"
                        okText="删除"
                        cancelText="取消"
                        onConfirm={() => removePoint(point, fn.id)}
                      >
                        <Button
                          type="link"
                          size="small"
                          danger
                          onClick={(event) => event.stopPropagation()}
                        >
                          删除
                        </Button>
                      </Popconfirm>
                    </Space>
                  )}
                </Space>
              ),
            })),
          }
        }),
    }))
  }, [
    modules,
    visibleFunctions,
    points,
    canWrite,
    functionForm,
    moduleForm,
    pointForm,
    migrateForm,
  ])

  const moduleOptions = modules.map((module) => ({
    value: module.id,
    label: module.name,
  }))

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

  return (
    <div>
      <Space wrap style={{ marginBottom: 12 }}>
        <Input.Search
          allowClear
          placeholder="搜索功能名"
          style={{ width: 200 }}
          onSearch={setKeyword}
          onChange={(event) => {
            if (!event.target.value) setKeyword('')
          }}
        />
        <Select
          allowClear
          placeholder="标签类型"
          style={{ width: 140 }}
          value={labelType}
          onChange={(value) => setLabelType(value)}
          options={(Object.keys(LABEL_TYPE_META) as LabelType[]).map((type) => ({
            value: type,
            label: LABEL_TYPE_META[type].label,
          }))}
        />
        <Select
          allowClear
          placeholder="来源类型"
          style={{ width: 140 }}
          value={sourceType}
          onChange={(value) => setSourceType(value)}
          options={[
            { value: 'manual', label: '手工添加' },
            { value: 'document', label: '文档解析' },
          ]}
        />
        {canWrite && (
          <Button
            type="primary"
            data-testid="add-module"
            onClick={() => {
              moduleForm.resetFields()
              setModuleModal({ open: true })
            }}
          >
            新增模块
          </Button>
        )}
        <Button onClick={() => reload().catch((error) => message.error(errorMessage(error)))}>
          刷新
        </Button>
      </Space>

      {modules.length === 0 ? (
        <Typography.Text type="secondary">
          还没有模块结构。{canWrite ? '先新增模块，再在其下建功能与功能点。' : ''}
        </Typography.Text>
      ) : (
        <Tree
          treeData={treeData}
          expandedKeys={expandedKeys}
          onExpand={(keys) => {
            const next = keys.map((key) => key.toString())
            setExpandedKeys(next)
            // 记住用户手动收起的模块，reload 后不再强行展开
            const nextSet = new Set(next)
            for (const key of collapsedRef.current) {
              if (key.startsWith('m-') && nextSet.has(key)) collapsedRef.current.delete(key)
            }
            for (const key of expandedKeys) {
              if (key.startsWith('m-') && !nextSet.has(key)) collapsedRef.current.add(key)
            }
          }}
          loadData={(node) =>
            node.key.toString().startsWith('f-')
              ? loadPoints(Number(node.key.toString().slice(2)))
              : Promise.resolve()
          }
        />
      )}

      {/* 模块 */}
      <Modal
        title={moduleModal.editing ? '重命名模块' : '新增模块'}
        open={moduleModal.open}
        onCancel={() => setModuleModal({ open: false })}
        onOk={submitModule}
        okText="保存"
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={moduleForm} layout="vertical">
          <Form.Item
            name="name"
            label="模块名"
            rules={[{ required: true, message: '请输入模块名' }]}
          >
            <Input placeholder="如：支付模块" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} placeholder="选填" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 功能 */}
      <Modal
        title={functionModal.editing ? '重命名功能' : '新增功能'}
        open={functionModal.open}
        onCancel={() => setFunctionModal({ open: false })}
        onOk={submitFunction}
        okText="保存"
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={functionForm} layout="vertical">
          <Form.Item
            name="name"
            label="功能名"
            rules={[{ required: true, message: '请输入功能名' }]}
          >
            <Input placeholder="如：提交订单" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} placeholder="选填" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 功能点 */}
      <Modal
        title={`新增功能点 · ${pointModal.functionName}`}
        open={pointModal.open}
        onCancel={() => setPointModal({ open: false })}
        onOk={submitPoint}
        okText="保存"
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={pointForm} layout="vertical">
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

      {/* 打标 / 清除 */}
      <Modal
        title={`标签 · ${labelModal.target?.name ?? ''}`}
        open={labelModal.open}
        onCancel={() => setLabelModal({ open: false })}
        footer={null}
        width={560}
      >
        {canWrite && (
          <Form form={labelForm} layout="inline" style={{ marginBottom: 12 }}>
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
                style={{ width: 120 }}
                placeholder="标签类型"
                options={(Object.keys(LABEL_TYPE_META) as LabelType[]).map((type) => ({
                  value: type,
                  label: LABEL_TYPE_META[type].label,
                }))}
              />
            </Form.Item>
            <Form.Item>
              <Button type="primary" data-testid="submit-label" onClick={submitLabel}>
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
                      onClick={() => {
                        clearForm.resetFields()
                        setClearModal({ open: true, label })
                      }}
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

      {/* 清除原因 */}
      <Modal
        title="清除标签"
        open={clearModal.open}
        onCancel={() => setClearModal({ open: false })}
        onOk={submitClear}
        okText="清除"
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={clearForm} layout="vertical">
          <Form.Item
            name="clear_reason"
            label="清除原因"
            rules={[{ required: true, message: '请选择清除原因' }]}
          >
            <Select
              placeholder="选择原因"
              options={(Object.keys(CLEAR_REASON_META) as ClearReason[]).map((reason) => ({
                value: reason,
                label: CLEAR_REASON_META[reason],
              }))}
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

      {/* 模块下还有功能：给「迁移功能」「删除功能」两个入口（AC-64） */}
      <Modal
        title="模块下还有功能"
        open={notEmptyModal.open}
        onCancel={() => setNotEmptyModal({ open: false })}
        footer={null}
        width={480}
      >
        <Typography.Paragraph>
          模块「{notEmptyModal.module?.name ?? ''}」下还有{' '}
          {functions.filter((fn) => fn.module_id === notEmptyModal.module?.id).length}{' '}
          个功能，删掉模块会连带影响它们。请先选一种处理方式：
        </Typography.Paragraph>
        <Space>
          <Button
            type="primary"
            data-testid="not-empty-migrate"
            onClick={() => {
              const module = notEmptyModal.module
              setNotEmptyModal({ open: false })
              if (!module) return
              migrateForm.resetFields()
              setMigrateModal({ open: true, module })
            }}
          >
            迁移功能
          </Button>
          <Button
            danger
            data-testid="not-empty-delete-functions"
            onClick={() => {
              const module = notEmptyModal.module
              if (!module) return
              void removeModuleWithFunctions(module)
            }}
          >
            删除功能并删除模块
          </Button>
        </Space>
      </Modal>

      {/* 批量迁移 */}
      <Modal
        title={`迁移功能 · ${migrateModal.module?.name ?? ''}`}
        open={migrateModal.open}
        onCancel={() => setMigrateModal({ open: false })}
        onOk={submitMigrate}
        okText="迁移"
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={migrateForm} layout="vertical">
          <Form.Item
            name="target_module_id"
            label="目标模块"
            rules={[{ required: true, message: '请选择目标模块' }]}
          >
            <Select
              placeholder="选择目标模块"
              options={moduleOptions.filter(
                (option) => option.value !== migrateModal.module?.id,
              )}
            />
          </Form.Item>
          <Form.Item
            name="function_ids"
            label="要迁移的功能"
            rules={[{ required: true, message: '请选择功能' }]}
          >
            <Select
              mode="multiple"
              placeholder="选择功能"
              options={functions
                .filter((fn) => fn.module_id === migrateModal.module?.id)
                .map((fn) => ({ value: fn.id, label: fn.name }))}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
