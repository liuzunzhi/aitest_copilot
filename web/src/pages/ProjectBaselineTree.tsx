import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button, Input, Select, Space, Tree, Typography, message } from 'antd'
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
  BaselineDeriveDetail,
  BaselineFeaturePoint,
  BaselineFunction,
  BaselineLabel,
  BaselineModule,
  BaselineRevision,
  BaselineStatusFilter,
  LabelType,
} from '../api'
import { errorCode, errorMessage } from '../api/client'
import {
  LABEL_TYPE_OPTIONS,
  SOURCE_TYPE_OPTIONS,
  STATUS_FILTER_OPTIONS,
} from './baselineMeta'
import type { LabelTarget } from './baselineShared'
import { buildBaselineTreeData } from './baselineTreeNodes'
import BaselineDeriveDrawer from './BaselineDeriveDrawer'
import BaselineDeriveModal from './BaselineDeriveModal'
import { BaselineTreeDialogs } from './ProjectBaselineTreeDialogs'
import type {
  ClearDialogState,
  ClearFormValues,
  FunctionDialogState,
  LabelDialogState,
  LabelFormValues,
  MigrateDialogState,
  MigrateFormValues,
  ModuleDialogState,
  NameDescFormValues,
  PointDialogState,
} from './ProjectBaselineTreeDialogs'

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
  const [entityLabels, setEntityLabels] = useState<BaselineLabel[]>([])
  const [keyword, setKeyword] = useState('')
  const [labelType, setLabelType] = useState<string | undefined>()
  const [sourceType, setSourceType] = useState<string | undefined>()
  /** 归档模块保留历史但不参与默认展示（spec §2.3 第 5 条）。 */
  const [statusFilter, setStatusFilter] = useState<BaselineStatusFilter>('active')

  const [moduleModal, setModuleModal] = useState<ModuleDialogState>({ open: false })
  const [functionModal, setFunctionModal] = useState<FunctionDialogState>({ open: false })
  const [pointModal, setPointModal] = useState<PointDialogState>({ open: false })
  const [labelModal, setLabelModal] = useState<LabelDialogState>({ open: false })
  const [clearModal, setClearModal] = useState<ClearDialogState>({ open: false })
  const [migrateModal, setMigrateModal] = useState<MigrateDialogState>({ open: false })
  /** AC-64：模块下还有功能时不给删，给「迁移功能」「删除功能」两个入口。 */
  const [notEmptyModal, setNotEmptyModal] = useState<MigrateDialogState>({ open: false })

  /** 从文档推导基线：选文档弹窗 + 结果抽屉（候选草稿，确认后才进结构表）。 */
  const [deriveModalOpen, setDeriveModalOpen] = useState(false)
  const [deriveDetail, setDeriveDetail] = useState<BaselineDeriveDetail | null>(null)

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
      listBaselineModules(projectId, {
        status: statusFilter,
        page_size: 200,
      }),
      listBaselineFunctions(projectId, {
        status: statusFilter,
        page_size: 200,
      }),
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
  }, [projectId, statusFilter])

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

  const loadPoints = useCallback(
    async (functionId: number) => {
      if (points[functionId]) return
      try {
        const list = await listBaselineFeaturePoints(projectId, functionId)
        setPoints((prev) => ({ ...prev, [functionId]: list }))
      } catch (error) {
        message.error(errorMessage(error))
      }
    },
    [projectId, points],
  )

  /* ------------------------------------------------------------ 标签面板 */

  const reloadLabels = useCallback(async () => {
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
  }, [projectId, labelModal.target])

  const openLabels = useCallback(
    async (target: LabelTarget) => {
      setLabelModal({ open: true, target })
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
    },
    [projectId],
  )

  /* --------------------------------------------------------------- 写操作 */

  const submitModule = useCallback(
    async (values: NameDescFormValues) => {
      try {
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
        message.error(errorMessage(error))
      }
    },
    [projectId, moduleModal.editing, reload],
  )

  const submitFunction = useCallback(
    async (values: NameDescFormValues) => {
      if (!functionModal.moduleId) return
      try {
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
        message.error(errorMessage(error))
      }
    },
    [projectId, functionModal.moduleId, functionModal.editing, reload],
  )

  const submitPoint = useCallback(
    async (values: NameDescFormValues) => {
      if (!pointModal.functionId) return
      const functionId = pointModal.functionId
      try {
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
        message.error(errorMessage(error))
      }
    },
    [projectId, pointModal.functionId, reload],
  )

  const removeModule = useCallback(
    async (module: BaselineModule) => {
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
    },
    [projectId, reload],
  )

  /** 归档 / 取消归档：状态经 PATCH 写入，审计沿用 module.update。 */
  const toggleModuleArchive = useCallback(
    async (module: BaselineModule) => {
      const next = module.status === 'archived' ? 'active' : 'archived'
      try {
        await updateBaselineModule(projectId, module.id, { status: next })
        message.success(next === 'archived' ? '模块已归档' : '模块已取消归档')
        await reload()
      } catch (error) {
        message.error(errorMessage(error))
      }
    },
    [projectId, reload],
  )

  /** AC-64：把模块下所有功能一并删掉，再删模块本身。 */
  const removeModuleWithFunctions = useCallback(
    async (module: BaselineModule) => {
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
    },
    [projectId, functions, reload],
  )

  const removeFunction = useCallback(
    async (fn: BaselineFunction) => {
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
    },
    [projectId, reload],
  )

  const removePoint = useCallback(
    async (point: BaselineFeaturePoint, functionId: number) => {
      try {
        const result = await deleteBaselineFeaturePoint(projectId, point.id)
        message.success(result.warning ?? '功能点已删除')
        const list = await listBaselineFeaturePoints(projectId, functionId)
        setPoints((prev) => ({ ...prev, [functionId]: list }))
        await reload()
      } catch (error) {
        message.error(errorMessage(error))
      }
    },
    [projectId, reload],
  )

  const submitLabel = useCallback(
    async (values: LabelFormValues) => {
      if (!labelModal.target) return
      try {
        await createBaselineLabel(projectId, {
          revision_id: values.revision_id ?? null,
          target_type: labelModal.target.targetType,
          target_id: labelModal.target.targetId,
          label_type: values.label_type,
        })
        message.success('标签已打上')
        setLabelModal({ open: false })
        await reload()
        await reloadLabels()
      } catch (error) {
        message.error(errorMessage(error))
      }
    },
    [projectId, labelModal.target, reload, reloadLabels],
  )

  const submitClear = useCallback(
    async (values: ClearFormValues) => {
      if (!clearModal.label) return
      try {
        await clearBaselineLabel(projectId, clearModal.label.id, {
          clear_reason: values.clear_reason,
          clear_note: values.clear_note ?? null,
        })
        message.success('标签已清除，历史留痕')
        setClearModal({ open: false })
        await reloadLabels()
        await reload()
      } catch (error) {
        message.error(errorMessage(error))
      }
    },
    [projectId, clearModal.label, reload, reloadLabels],
  )

  const submitMigrate = useCallback(
    async (values: MigrateFormValues) => {
      if (!migrateModal.module) return
      try {
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
        message.error(errorMessage(error))
      }
    },
    [projectId, migrateModal.module, reload],
  )

  /* --------------------------------------------------------------- 渲染 */

  const openModuleModal = useCallback((editing?: BaselineModule) => {
    setModuleModal({ open: true, editing })
  }, [])

  const openFunctionModal = useCallback(
    (moduleId: number, editing?: BaselineFunction) => {
      setFunctionModal({ open: true, moduleId, editing })
    },
    [],
  )

  const openPointModal = useCallback((functionId: number, functionName: string) => {
    setPointModal({ open: true, functionId, functionName })
  }, [])

  const openMigrateModal = useCallback((module: BaselineModule) => {
    setMigrateModal({ open: true, module })
  }, [])

  const treeData = useMemo(
    () =>
      buildBaselineTreeData({
        modules,
        visibleFunctions,
        points,
        canWrite,
        onAddFunction: (module) => openFunctionModal(module.id),
        onRenameModule: (module) => openModuleModal(module),
        onMigrateModule: (module) => openMigrateModal(module),
        onToggleArchive: (module) => void toggleModuleArchive(module),
        onDeleteModule: (module) => void removeModule(module),
        onAddPoint: (fn) => openPointModal(fn.id, fn.name),
        onOpenLabels: (target) => void openLabels(target),
        onDeleteFunction: (fn) => void removeFunction(fn),
        onDeletePoint: (point, functionId) => void removePoint(point, functionId),
      }),
    [
      modules,
      visibleFunctions,
      points,
      canWrite,
      openFunctionModal,
      openModuleModal,
      openMigrateModal,
      toggleModuleArchive,
      removeModule,
      openPointModal,
      openLabels,
      removeFunction,
      removePoint,
    ],
  )

  return (
    <div>
      <Space wrap style={{ marginBottom: 12 }}>
        <Input.Search
          allowClear
          placeholder="搜索功能名"
          style={{ width: 200 }}
          data-testid="baseline-keyword"
          onSearch={setKeyword}
          onChange={(event) => {
            if (!event.target.value) setKeyword('')
          }}
        />
        <Select
          allowClear
          placeholder="标签类型"
          style={{ width: 140 }}
          data-testid="baseline-label-filter"
          value={labelType}
          onChange={(value) => setLabelType(value)}
          options={LABEL_TYPE_OPTIONS}
        />
        <Select
          allowClear
          placeholder="来源类型"
          style={{ width: 140 }}
          data-testid="baseline-source-filter"
          value={sourceType}
          onChange={(value) => setSourceType(value)}
          options={SOURCE_TYPE_OPTIONS}
        />
        {canWrite && (
          <Button type="primary" data-testid="add-module" onClick={() => openModuleModal()}>
            新增模块
          </Button>
        )}
        {canWrite && (
          <Button
            data-testid="derive-from-document"
            onClick={() => setDeriveModalOpen(true)}
          >
            从文档推导
          </Button>
        )}
        <Button onClick={() => reload().catch((error) => message.error(errorMessage(error)))}>
          刷新
        </Button>
        <Select
          data-testid="baseline-status-filter"
          style={{ width: 120 }}
          value={statusFilter}
          onChange={(value: BaselineStatusFilter) => setStatusFilter(value)}
          options={STATUS_FILTER_OPTIONS}
        />
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

      <BaselineDeriveModal
        open={deriveModalOpen}
        projectId={projectId}
        onClose={() => setDeriveModalOpen(false)}
        onDerived={(detail) => setDeriveDetail(detail)}
      />

      <BaselineDeriveDrawer
        open={deriveDetail !== null}
        projectId={projectId}
        detail={deriveDetail}
        onClose={() => setDeriveDetail(null)}
        onAdopted={() => {
          reload().catch((error) => message.error(errorMessage(error)))
        }}
      />

      <BaselineTreeDialogs
        canWrite={canWrite}
        modules={modules}
        functions={functions}
        revisions={revisions}
        entityLabels={entityLabels}
        moduleModal={moduleModal}
        functionModal={functionModal}
        pointModal={pointModal}
        labelModal={labelModal}
        clearModal={clearModal}
        notEmptyModal={notEmptyModal}
        migrateModal={migrateModal}
        onCancelModule={() => setModuleModal({ open: false })}
        onSubmitModule={submitModule}
        onCancelFunction={() => setFunctionModal({ open: false })}
        onSubmitFunction={submitFunction}
        onCancelPoint={() => setPointModal({ open: false })}
        onSubmitPoint={submitPoint}
        onCloseLabel={() => setLabelModal({ open: false })}
        onSubmitLabel={submitLabel}
        onClearLabel={(label) => setClearModal({ open: true, label })}
        onCancelClear={() => setClearModal({ open: false })}
        onSubmitClear={submitClear}
        onCancelNotEmpty={() => setNotEmptyModal({ open: false })}
        onMigrateFromNotEmpty={(module) => {
          setNotEmptyModal({ open: false })
          openMigrateModal(module)
        }}
        onDeleteWithFunctions={(module) => void removeModuleWithFunctions(module)}
        onCancelMigrate={() => setMigrateModal({ open: false })}
        onSubmitMigrate={submitMigrate}
      />
    </div>
  )
}
