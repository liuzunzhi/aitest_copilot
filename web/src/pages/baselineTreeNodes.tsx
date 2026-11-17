/** 基线树的节点渲染：把树的 title JSX 从容器里搬出来。 */

import { Button, Popconfirm, Space, Tag, Typography } from 'antd'
import type { DataNode } from 'antd/es/tree'
import type {
  BaselineFeaturePoint,
  BaselineFunction,
  BaselineModule,
  LabelType,
} from '../api'
import { LABEL_TYPE_META } from './baselineMeta'
import type { LabelTarget } from './baselineShared'

/** 标签类型 → Tag 列表（功能级 / 功能点级通用，互不汇总）。 */
export function labelTags(types: LabelType[]) {
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

/**
 * 构造树的 treeData。
 *
 * 节点上的按钮只负责 `stopPropagation` + 调回调，
 * 表单重置 / 弹窗开关都在容器里做（容器包一层 handler 再传进来）。
 */
export interface BaselineTreeNodeOptions {
  modules: BaselineModule[]
  visibleFunctions: BaselineFunction[]
  points: Record<number, BaselineFeaturePoint[]>
  canWrite: boolean
  onAddFunction: (module: BaselineModule) => void
  onRenameModule: (module: BaselineModule) => void
  onMigrateModule: (module: BaselineModule) => void
  onToggleArchive: (module: BaselineModule) => void
  onDeleteModule: (module: BaselineModule) => void
  onAddPoint: (fn: BaselineFunction) => void
  onOpenLabels: (target: LabelTarget) => void
  onDeleteFunction: (fn: BaselineFunction) => void
  onDeletePoint: (point: BaselineFeaturePoint, functionId: number) => void
}

export function buildBaselineTreeData(options: BaselineTreeNodeOptions): DataNode[] {
  const {
    modules,
    visibleFunctions,
    points,
    canWrite,
    onAddFunction,
    onRenameModule,
    onMigrateModule,
    onToggleArchive,
    onDeleteModule,
    onAddPoint,
    onOpenLabels,
    onDeleteFunction,
    onDeletePoint,
  } = options

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
                onAddFunction(module)
              }}
            >
              新增功能
            </Button>
            <Button
              type="link"
              size="small"
              data-testid={`baseline-module-rename-${module.id}`}
              onClick={(event) => {
                event.stopPropagation()
                onRenameModule(module)
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
                onMigrateModule(module)
              }}
            >
              迁移功能
            </Button>
            <Button
              type="link"
              size="small"
              data-testid="baseline-module-archive"
              onClick={(event) => {
                event.stopPropagation()
                onToggleArchive(module)
              }}
            >
              {module.status === 'archived' ? '取消归档' : '归档'}
            </Button>
            <Popconfirm
              title="删除该模块？"
              description="模块下若还有功能，需要先迁移或删除功能。"
              okText="删除"
              cancelText="取消"
              onConfirm={() => onDeleteModule(module)}
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
                      onAddPoint(fn)
                    }}
                  >
                    新增功能点
                  </Button>
                  <Button
                    type="link"
                    size="small"
                    data-testid={`baseline-labels-function-${fn.id}`}
                    onClick={(event) => {
                      event.stopPropagation()
                      onOpenLabels({
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
                    onConfirm={() => onDeleteFunction(fn)}
                  >
                    <Button
                      type="link"
                      size="small"
                      danger
                      data-testid={`baseline-function-delete-${fn.id}`}
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
                      data-testid={`baseline-labels-point-${point.id}`}
                      onClick={(event) => {
                        event.stopPropagation()
                        onOpenLabels({
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
                      onConfirm={() => onDeletePoint(point, fn.id)}
                    >
                      <Button
                        type="link"
                        size="small"
                        danger
                        data-testid={`baseline-point-delete-${point.id}`}
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
}
