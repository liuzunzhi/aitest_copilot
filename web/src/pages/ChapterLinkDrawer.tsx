import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  App as AntdApp,
  Button,
  Drawer,
  Form,
  Input,
  Popconfirm,
  Radio,
  Select,
  Space,
  Table,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'

import {
  analyzeChapterLinks,
  createChapterLink,
  deleteChapterLink,
  extractChapterLinks,
  listChapterLinks,
  listChapters,
} from '../api'
import type { Chapter, ChapterLink } from '../api'
import { errorMessage } from '../api/client'
import { linkSourceTag, linkTypeTag } from './incrementalMeta'

interface Props {
  open: boolean
  projectId: number
  documentId: number
  versionId: number
  /**
   * 补链 / 重抽 / AI 分析 / 删除**限项目管理员**。
   *
   * 不用外层的 `canWrite`——那个含普通 member（后端允许 member 动自己上传的
   * 版本），但引用图的写操作后端只认 `project_admin`，
   * 口径差会让 member 看到按钮、点下去吃 403。
   */
  canWrite: boolean
  onClose: () => void
}

/** 类型下拉的选项说明——用户第一次用时不知道「类型」该填什么。 */
const LINK_TYPE_OPTIONS = [
  { value: 'references', label: '引用 —— A 章节提到「见 B 章节」' },
  { value: 'depends_on', label: '依赖 —— A 章节的实现依赖 B 章节' },
  { value: 'mentions_entity', label: '相关 —— A 章节提到某个功能点或术语' },
]

/** 章节树拍平成下拉项；缩进用全角空格，保持层级可读。 */
function flattenChapters(chapters: Chapter[], depth = 0): Array<{ value: number; label: string }> {
  return chapters.flatMap((chapter) => [
    { value: chapter.id, label: `${'　'.repeat(depth)}${chapter.title}` },
    ...flattenChapters(chapter.children ?? [], depth + 1),
  ])
}

/** 章节引用图抽屉：只读列表 + 管理员 AI 分析 / 补链 / 重抽 / 删除。 */
export default function ChapterLinkDrawer({
  open,
  projectId,
  documentId,
  versionId,
  canWrite,
  onClose,
}: Props) {
  const { message } = AntdApp.useApp()
  const [links, setLinks] = useState<ChapterLink[]>([])
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [loading, setLoading] = useState(false)
  /** 三个操作的 loading 分开——共用一个 state 时用户分不清在等哪个。 */
  const [analyzing, setAnalyzing] = useState(false)
  const [extracting, setExtracting] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [targetKind, setTargetKind] = useState<'chapter' | 'entity'>('chapter')
  const [form] = Form.useForm<{
    from_chapter_id: number
    link_type: ChapterLink['link_type']
    to_chapter_id?: number
    entity?: string
  }>()

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const [linkList, chapterTree] = await Promise.all([
        listChapterLinks(projectId, documentId, versionId),
        listChapters(projectId, documentId, versionId),
      ])
      setLinks(linkList)
      setChapters(chapterTree)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [projectId, documentId, versionId, message])

  useEffect(() => {
    if (!open) return
    void reload()
  }, [open, reload])

  const chapterOptions = useMemo(() => flattenChapters(chapters), [chapters])

  async function analyze() {
    setAnalyzing(true)
    try {
      const result = await analyzeChapterLinks(projectId, documentId, versionId)
      message.success(
        `AI 分析完成：${result.chapter_count} 个章节，发现 ${result.analyzed_count} 条引用关系` +
          (result.discarded_count ? `（${result.discarded_count} 条越界已丢弃）` : ''),
      )
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setAnalyzing(false)
    }
  }

  async function submit() {
    try {
      const values = await form.validateFields()
      setSubmitting(true)
      await createChapterLink(projectId, documentId, versionId, {
        from_chapter_id: values.from_chapter_id,
        link_type: values.link_type,
        to_chapter_id: targetKind === 'chapter' ? values.to_chapter_id : null,
        entity: targetKind === 'entity' ? values.entity : null,
      })
      message.success('已补一条引用关系')
      form.resetFields()
      await reload()
    } catch (error) {
      if (error && typeof error === 'object' && 'errorFields' in error) return
      message.error(errorMessage(error))
    } finally {
      setSubmitting(false)
    }
  }

  async function reExtract() {
    setExtracting(true)
    try {
      await extractChapterLinks(projectId, documentId, versionId)
      message.success('已按规则重抽引用图')
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setExtracting(false)
    }
  }

  async function remove(linkId: number) {
    setDeletingId(linkId)
    try {
      await deleteChapterLink(projectId, documentId, versionId, linkId)
      message.success('已删除这条引用关系')
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setDeletingId(null)
    }
  }

  const columns: ColumnsType<ChapterLink> = [
    {
      title: '源章节',
      dataIndex: 'from_chapter_title',
      render: (value: string | null) => value ?? '—',
    },
    {
      title: '类型',
      dataIndex: 'link_type',
      width: 110,
      render: (value: string) => linkTypeTag(value),
    },
    {
      title: '目标',
      key: 'target',
      render: (_: unknown, row) =>
        row.to_chapter_id !== null ? (
          row.to_chapter_title ?? `章节 #${row.to_chapter_id}`
        ) : (
          <Typography.Text>实体「{row.entity}」</Typography.Text>
        ),
    },
    {
      title: '来源',
      dataIndex: 'source',
      width: 90,
      render: (value: string) => linkSourceTag(value),
    },
    {
      title: '操作',
      key: 'action',
      width: 70,
      render: (_: unknown, row) =>
        canWrite ? (
          <Popconfirm
            title="确认删除这条引用关系？"
            description={
              row.source === 'rule'
                ? '删除后再次「按规则重抽」会重新生成这条关系。'
                : undefined
            }
            onConfirm={() => void remove(row.id)}
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
        ) : null,
    },
  ]

  return (
    <Drawer
      title="章节引用图"
      width={720}
      open={open}
      onClose={onClose}
      extra={
        canWrite ? (
          <Button
            type="primary"
            loading={analyzing}
            data-testid="chapter-link-ai-analyze-btn"
            onClick={() => void analyze()}
          >
            ✨ AI 一键分析引用
          </Button>
        ) : null
      }
    >
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Alert
          type="info"
          showIcon
          data-testid="chapter-link-ai-hint"
          message="系统已通过 AI 自动识别章节间的引用关系，您可以修改或删除错误结果，也可以手动补充。"
        />

        {analyzing ? (
          <Typography.Text type="secondary" data-testid="chapter-link-analyzing-tip">
            正在调用模型分析章节引用关系，可能需要 1–2 分钟…
          </Typography.Text>
        ) : null}

        <Table<ChapterLink>
          size="small"
          rowKey="id"
          columns={columns}
          dataSource={links}
          pagination={false}
          loading={loading}
          locale={{ emptyText: '该版本还没有引用关系' }}
          data-testid="chapter-link-table"
        />

        {canWrite ? (
          <div>
            <Typography.Title level={5} style={{ marginTop: 0 }}>
              补一条引用关系
            </Typography.Title>
            <Form
              form={form}
              layout="vertical"
              initialValues={{ link_type: 'references', target_kind: 'chapter' }}
            >
              <Form.Item
                name="from_chapter_id"
                label="源章节"
                rules={[{ required: true, message: '请选择源章节' }]}
              >
                <Select
                  placeholder="请选择源章节"
                  options={chapterOptions}
                  showSearch
                  optionFilterProp="label"
                  data-testid="chapter-link-from-select"
                />
              </Form.Item>
              <Form.Item
                name="link_type"
                label="类型"
                rules={[{ required: true, message: '请选择类型' }]}
              >
                <Select
                  placeholder="请选择引用关系类型"
                  options={LINK_TYPE_OPTIONS}
                  data-testid="chapter-link-type-select"
                />
              </Form.Item>
              <Form.Item label="目标类型">
                <Radio.Group
                  value={targetKind}
                  onChange={(event) => setTargetKind(event.target.value)}
                  data-testid="chapter-link-target-kind"
                  options={[
                    { value: 'chapter', label: '目标章节' },
                    { value: 'entity', label: '实体名' },
                  ]}
                  optionType="button"
                />
              </Form.Item>
              {targetKind === 'chapter' ? (
                <Form.Item
                  name="to_chapter_id"
                  label="目标章节"
                  rules={[{ required: true, message: '请选择目标章节' }]}
                >
                  <Select
                    placeholder="请选择目标章节"
                    options={chapterOptions}
                    showSearch
                    optionFilterProp="label"
                    data-testid="chapter-link-to-select"
                  />
                </Form.Item>
              ) : (
                <Form.Item
                  name="entity"
                  label="实体名"
                  rules={[{ required: true, message: '请输入实体名' }]}
                >
                  <Input
                    placeholder="格式：功能:用户登录，如 功能:退款审核 / 术语:订单锁定"
                    data-testid="chapter-link-entity-input"
                  />
                </Form.Item>
              )}
              <Space>
                <Button
                  type="primary"
                  loading={submitting}
                  data-testid="chapter-link-create-btn"
                  onClick={submit}
                >
                  补链
                </Button>
                <Button
                  loading={extracting}
                  data-testid="chapter-link-extract-btn"
                  onClick={reExtract}
                >
                  按规则重抽
                </Button>
              </Space>
            </Form>
          </div>
        ) : (
          <Typography.Text type="secondary">
            只有项目管理员可以分析、补链与删除引用图，你可以查看已有关系。
          </Typography.Text>
        )}
      </Space>
    </Drawer>
  )
}
