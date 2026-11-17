import { useCallback, useEffect, useMemo, useState } from 'react'
import { App as AntdApp, Button, Drawer, Form, Input, Radio, Select, Space, Table, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'

import {
  createChapterLink,
  extractChapterLinks,
  listChapterLinks,
  listChapters,
} from '../api'
import type { Chapter, ChapterLink } from '../api'
import { errorMessage } from '../api/client'
import { linkTypeTag } from './incrementalMeta'

interface Props {
  open: boolean
  projectId: number
  documentId: number
  versionId: number
  /** 补链与重抽限项目管理员。 */
  canWrite: boolean
  onClose: () => void
}

/** 章节引用图抽屉：只读列表 + 管理员补链 / 重抽。 */
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
  const [submitting, setSubmitting] = useState(false)
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

  /** 章节树拍平成「标题 → id」的下拉选项。 */
  const chapterOptions = useMemo(() => {
    const options: { value: number; label: string }[] = []
    const walk = (nodes: Chapter[]) => {
      nodes.forEach((node) => {
        options.push({ value: node.id, label: node.title })
        if (node.children.length) walk(node.children)
      })
    }
    walk(chapters)
    return options
  }, [chapters])

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
    setSubmitting(true)
    try {
      await extractChapterLinks(projectId, documentId, versionId)
      message.success('已按规则重抽引用图')
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setSubmitting(false)
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
      render: (value: string) => (value === 'rule' ? '规则' : '人工'),
    },
  ]

  return (
    <Drawer title="章节引用图" width={720} open={open} onClose={onClose}>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
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
                  placeholder="选择源章节"
                  options={chapterOptions}
                  data-testid="chapter-link-from-select"
                />
              </Form.Item>
              <Form.Item
                name="link_type"
                label="类型"
                rules={[{ required: true, message: '请选择类型' }]}
              >
                <Select
                  data-testid="chapter-link-type-select"
                  options={[
                    { value: 'references', label: '引用' },
                    { value: 'depends_on', label: '依赖' },
                    { value: 'mentions_entity', label: '提及实体' },
                  ]}
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
                    placeholder="选择目标章节"
                    options={chapterOptions}
                    data-testid="chapter-link-to-select"
                  />
                </Form.Item>
              ) : (
                <Form.Item
                  name="entity"
                  label="实体名"
                  rules={[{ required: true, message: '请输入实体名' }]}
                >
                  <Input placeholder="功能点或术语名" data-testid="chapter-link-entity-input" />
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
                  loading={submitting}
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
            只有项目管理员可以补链与重抽引用图，你可以查看已有关系。
          </Typography.Text>
        )}
      </Space>
    </Drawer>
  )
}
