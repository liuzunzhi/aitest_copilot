import { Button, Descriptions, Popconfirm, Select, Space, Tag, Tooltip, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'

import type { ProcessLink, ProcessLinkableTarget, ProcessScenario } from '../api'
import {
  IN_REVIEW_TIP,
  TARGET_TYPE_LABELS,
  sourceTypeText,
  statusText,
} from './processBaselineMeta'

interface Props {
  /** 写入口（编辑 / 删除）只有项目管理员才渲染。 */
  canManage: boolean
  /** 审核期锁定：有 `status='submitted'` 的快照时写入口禁用。 */
  inReview: boolean
  onOpen: (scenario: ProcessScenario) => void
  onEdit: (scenario: ProcessScenario) => void
  onDelete: (scenario: ProcessScenario) => void
}

/**
 * 流程基线场景表的列定义（**纯渲染**，不碰状态）。
 *
 * **为什么单独成文件**：主文件 `ProjectProcessBaselineTab.tsx` 只留
 * 「状态与事件编排」，列定义拆出来才压得住 400 行的拆分阈值
 * （验证约定 §4.3）。这与 09 期 `automationColumns.tsx` 同一思路。
 */
export function buildProcessScenarioColumns({
  canManage,
  inReview,
  onOpen,
  onEdit,
  onDelete,
}: Props): ColumnsType<ProcessScenario> {
  return [
    {
      title: '场景名称',
      key: 'name',
      width: 240,
      render: (_: unknown, scenario) => (
        <Space direction="vertical" size={0}>
          <span data-testid={`process-baseline-name-${scenario.id}`}>{scenario.name}</span>
          {scenario.description ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {scenario.description}
            </Typography.Text>
          ) : null}
        </Space>
      ),
    },
    {
      title: '来源',
      dataIndex: 'source_type',
      width: 100,
      render: (sourceType: string) => {
        const meta = sourceTypeText(sourceType)
        return (
          <span data-testid={`process-baseline-source-${sourceType}`}>
            <Tag color={meta.color}>{meta.label}</Tag>
          </span>
        )
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (status: string, scenario) => {
        const meta = statusText(status)
        return (
          <span data-testid={`process-baseline-status-${scenario.id}`}>
            <Tag color={meta.color}>{meta.label}</Tag>
          </span>
        )
      },
    },
    {
      title: '步骤数',
      dataIndex: 'step_count',
      width: 80,
      render: (value: number, scenario) => (
        <span data-testid={`process-baseline-step-count-${scenario.id}`}>{value}</span>
      ),
    },
    {
      title: '关联数',
      dataIndex: 'link_count',
      width: 80,
      render: (value: number, scenario) => (
        <span data-testid={`process-baseline-link-count-${scenario.id}`}>{value}</span>
      ),
    },
    {
      title: '修订次数',
      dataIndex: 'version_no',
      width: 90,
      render: (value: number) => `v${value}`,
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 180,
      render: (value: string) => new Date(value).toLocaleString(),
    },
    {
      title: '操作',
      key: 'actions',
      width: 200,
      render: (_: unknown, scenario) => (
        <Space size={4}>
          <Button
            size="small"
            onClick={() => onOpen(scenario)}
            data-testid={`process-baseline-detail-btn-${scenario.id}`}
          >
            详情
          </Button>
          {canManage ? (
            <Tooltip title={inReview ? IN_REVIEW_TIP : undefined}>
              {/* disabled 的按钮不派发鼠标事件，Tooltip 要挂在外层 span 上才会弹。 */}
              <span>
                <Button
                  size="small"
                  disabled={inReview}
                  onClick={() => onEdit(scenario)}
                  data-testid={`process-baseline-edit-btn-${scenario.id}`}
                >
                  编辑
                </Button>
              </span>
            </Tooltip>
          ) : null}
          {canManage ? (
            <Tooltip title={inReview ? IN_REVIEW_TIP : undefined}>
              <span>
                <Popconfirm
                  title="确认删除该场景？"
                  description="步骤与关联会一并删除。"
                  okText="删除"
                  cancelText="取消"
                  onConfirm={() => onDelete(scenario)}
                >
                  <Button
                    size="small"
                    danger
                    disabled={inReview}
                    data-testid={`process-baseline-delete-btn-${scenario.id}`}
                  >
                    删除
                  </Button>
                </Popconfirm>
              </span>
            </Tooltip>
          ) : null}
        </Space>
      ),
    },
  ]
}

/**
 * 抽屉里「关联功能基线」表的列定义（同样是纯渲染）。
 *
 * **编辑态多一列「删除」**——已选列表可以逐条去掉。
 */
export function buildProcessLinkColumns({
  editing,
  onRemove,
}: {
  editing: boolean
  onRemove: (index: number) => void
}): ColumnsType<ProcessLink> {
  return [
    {
      title: '目标类型',
      dataIndex: 'target_type',
      width: 100,
      render: (value: ProcessLink['target_type']) => TARGET_TYPE_LABELS[value] ?? value,
    },
    {
      title: '目标名称',
      dataIndex: 'target_name',
      render: (value: string, row) => (
        <Space size={4}>
          <span>{value}</span>
          {row.target_deleted ? (
            <Tag color="warning" data-testid={`process-baseline-link-deleted-${row.target_id}`}>
              目标已删除
            </Tag>
          ) : null}
        </Space>
      ),
    },
    ...(editing
      ? [
          {
            title: '操作',
            key: 'actions',
            width: 80,
            render: (_: unknown, __: ProcessLink, index: number) => (
              <Button
                size="small"
                danger
                onClick={() => onRemove(index)}
                data-testid={`process-baseline-link-remove-${index}`}
              >
                删除
              </Button>
            ),
          },
        ]
      : []),
  ]
}

/**
 * 关联目标的**多选下拉**（抽屉与新建弹窗共用）。
 *
 * 选中项先落在下拉里，点「加入关联」才并入已选列表——
 * 这样用户能一次选多个再统一确认，不会「点一下就多一行」。
 */
export function ProcessLinkSelect({
  targets,
  value,
  onChange,
  testId,
}: {
  targets: ProcessLinkableTarget[]
  value: string[]
  onChange: (next: string[]) => void
  testId: string
}) {
  return (
    <Select
      mode="multiple"
      allowClear
      showSearch
      optionFilterProp="label"
      placeholder="选择要关联的功能 / 功能点"
      style={{ width: 360 }}
      value={value}
      onChange={(next) => onChange(next as string[])}
      options={targets.map((target) => ({
        value: `${target.target_type}:${target.target_id}`,
        label: `${TARGET_TYPE_LABELS[target.target_type]} · ${target.label}`,
      }))}
      data-testid={testId}
    />
  )
}

/**
 * 场景元数据的**只读展示**（抽屉里的 Descriptions 块）。
 *
 * **追溯三元组只在「文档解析」来源下渲染**——手工添加时六列全为 null，
 * 不渲染空行（spec §8.4）。
 */
export function ProcessScenarioMetaView({ scenario }: { scenario: ProcessScenario }) {
  return (
    <Descriptions size="small" column={2} bordered data-testid="process-baseline-meta-view">
      <Descriptions.Item label="场景名称" span={2}>
        {scenario.name}
      </Descriptions.Item>
      <Descriptions.Item label="描述" span={2}>
        {scenario.description || '—'}
      </Descriptions.Item>
      <Descriptions.Item label="前置条件" span={2}>
        {scenario.precondition || '—'}
      </Descriptions.Item>
      <Descriptions.Item label="来源">{sourceTypeText(scenario.source_type).label}</Descriptions.Item>
      <Descriptions.Item label="状态">{statusText(scenario.status).label}</Descriptions.Item>
      <Descriptions.Item label="修订次数">v{scenario.version_no}</Descriptions.Item>
      <Descriptions.Item label="更新时间">
        {new Date(scenario.updated_at).toLocaleString()}
      </Descriptions.Item>
      {scenario.source_type === 'document_derived' ? (
        <>
          <Descriptions.Item label="来源文档">
            {scenario.source_document_id ?? '—'}
          </Descriptions.Item>
          <Descriptions.Item label="来源版本">
            {scenario.source_version_id ?? '—'}
          </Descriptions.Item>
          <Descriptions.Item label="来源章节" span={2}>
            {scenario.source_chapter_title ?? '—'}
          </Descriptions.Item>
        </>
      ) : null}
    </Descriptions>
  )
}
