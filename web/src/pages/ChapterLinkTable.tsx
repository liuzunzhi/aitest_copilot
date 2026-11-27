import { Button, Popconfirm, Space, Table, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { TableRowSelection } from 'antd/es/table/interface'

import type { ChapterLink } from '../api'
import { linkSourceTag, linkTypeTag } from './incrementalMeta'

interface Props {
  links: ChapterLink[]
  /** 待评审区多一个「采纳」按钮，其余列完全一致。 */
  mode: 'pending' | 'effective'
  canWrite: boolean
  /** 首次加载 / reload 时的表格骨架。 */
  loading: boolean
  deletingId: number | null
  approvingId: number | null
  /** 待评审区的勾选配置；已生效区不传（不可多选）。 */
  rowSelection?: TableRowSelection<ChapterLink>
  emptyText: string
  onDetail: (link: ChapterLink) => void
  onDelete: (link: ChapterLink) => void
  onApprove: (link: ChapterLink) => void
}

/**
 * 引用边表格（待评审区 / 已生效区**共用**同一套列定义）。
 *
 * 抽成独立组件而不是在抽屉里写两份 `columns`：
 * 两个区只有「操作列多不多一个采纳按钮」这一个差异，
 * 写两份列定义迟早漂移（负例：12 期在来源列上踩过三元表达式的坑）。
 */
export default function ChapterLinkTable({
  links,
  mode,
  canWrite,
  loading,
  deletingId,
  approvingId,
  rowSelection,
  emptyText,
  onDetail,
  onDelete,
  onApprove,
}: Props) {
  const columns: ColumnsType<ChapterLink> = [
    {
      title: '源章节',
      dataIndex: 'from_chapter_title',
      render: (value: string | null) => value ?? '—',
    },
    {
      title: '类型',
      dataIndex: 'link_type',
      width: 100,
      render: (value: string) => linkTypeTag(value),
    },
    {
      title: '目标',
      key: 'target',
      render: (_: unknown, row) =>
        row.to_chapter_id !== null ? (
          (row.to_chapter_title ?? `章节 #${row.to_chapter_id}`)
        ) : (
          <Typography.Text>实体「{row.entity}」</Typography.Text>
        ),
    },
    {
      title: '置信度',
      dataIndex: 'confidence',
      width: 84,
      render: (value: number | null) => (value === null ? '—' : value.toFixed(2)),
    },
    {
      title: '来源',
      dataIndex: 'source',
      width: 76,
      render: (value: string) => linkSourceTag(value),
    },
    {
      title: '操作',
      key: 'action',
      width: mode === 'pending' ? 200 : 130,
      render: (_: unknown, row) =>
        // 访客没有操作列内容（AC-238：采纳 / 详情 / 删除都只给项目管理员）
        canWrite ? (
          <Space size={4}>
            <Button
              size="small"
              data-testid={`chapter-link-detail-btn-${row.id}`}
              onClick={() => onDetail(row)}
            >
              详情
            </Button>
            {mode === 'pending' ? (
              <Button
                size="small"
                type="primary"
                loading={approvingId === row.id}
                data-testid={`chapter-link-approve-btn-${row.id}`}
                onClick={() => onApprove(row)}
              >
                采纳
              </Button>
            ) : null}
            <Popconfirm
              title={
                mode === 'pending'
                  ? '确认删除这条待评审的引用关系？'
                  : '确认删除这条引用关系？'
              }
              okText="删除"
              cancelText="取消"
              description={
                row.source === 'rule'
                  ? '删除后再次「按规则重抽」会重新生成这条关系。'
                  : undefined
              }
              onConfirm={() => onDelete(row)}
            >
              <Button
                size="small"
                danger
                loading={deletingId === row.id}
                data-testid={`chapter-link-delete-btn-${row.id}`}
              >
                删除
              </Button>
            </Popconfirm>
          </Space>
        ) : null,
    },
  ]

  return (
    <Table<ChapterLink>
      size="small"
      rowKey="id"
      columns={columns}
      dataSource={links}
      pagination={false}
      loading={loading}
      rowSelection={rowSelection}
      locale={{ emptyText }}
      data-testid={
        mode === 'pending'
          ? 'chapter-link-pending-table'
          : 'chapter-link-effective-table'
      }
    />
  )
}
