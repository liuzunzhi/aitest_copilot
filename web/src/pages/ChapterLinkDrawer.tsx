import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  App as AntdApp,
  Button,
  ConfigProvider,
  Drawer,
  Form,
  Input,
  Radio,
  Select,
  Space,
  Typography,
} from 'antd'
import type { TableRowSelection } from 'antd/es/table/interface'

import {
  analyzeChapterLinks,
  approveChapterLink,
  approveChapterLinksBatch,
  createChapterLink,
  deleteChapterLink,
  listChapterLinks,
  listChapters,
} from '../api'
import type { Chapter, ChapterLink } from '../api'
import { errorMessage } from '../api/client'
import ChapterLinkDetailModal from './ChapterLinkDetailModal'
import ChapterLinkTable from './ChapterLinkTable'

interface Props {
  open: boolean
  projectId: number
  documentId: number
  versionId: number
  /**
   * 补链 / AI 分析 / 采纳 / 删除**限项目管理员**。
   *
   * 不用外层的 `canWrite`——那个含普通 member（后端允许 member 动自己上传的
   * 版本），但引用图的写操作后端只认 `project_admin`，
   * 口径差会让 member 看到按钮、点下去吃 403。
   */
  canWrite: boolean
  onClose: () => void
}

/** 类型下拉的两行式选项：名称一行、说明一行（长句挤一行看不清）。 */
const LINK_TYPE_OPTIONS = [
  { value: 'references', label: '引用', description: 'A 章节提到「见 B 章节」' },
  { value: 'depends_on', label: '依赖', description: 'A 章节的实现依赖 B 章节' },
  { value: 'mentions_entity', label: '相关', description: 'A 章节提到某个功能点或术语' },
]

/** 章节树拍平成下拉项；缩进用全角空格，保持层级可读。 */
function flattenChapters(chapters: Chapter[], depth = 0): Array<{ value: number; label: string }> {
  return chapters.flatMap((chapter) => [
    { value: chapter.id, label: `${'　'.repeat(depth)}${chapter.title}` },
    ...flattenChapters(chapter.children ?? [], depth + 1),
  ])
}

/**
 * 抽屉顶部的提示语——**按数据状态切换**（12.5 期痛点 2）。
 *
 * 12 期是静态显示「系统已通过 AI 自动识别……」，哪怕这个版本从来没跑过分析。
 * 现在的三态：
 *
 * 1. 一条边都没有 → 引导去点 AI 分析；
 * 2. 有待评审 → 告知「确认后才生效」，并说明不影响传播计算；
 * 3. 只剩已生效 → 12 期的原文案（**一字不改**，e2e 断言依赖它）。
 */
function hintOf(pendingCount: number, totalCount: number) {
  if (totalCount === 0) {
    return {
      type: 'info' as const,
      message:
        '当前版本还没有引用关系。点击右上角【✨ AI 一键分析引用】自动识别，也可手动补充。',
    }
  }
  if (pendingCount > 0) {
    return {
      type: 'warning' as const,
      message: `AI 已识别出 ${pendingCount} 条引用关系，待你确认后生效。确认前不会参与增量分析的传播计算。`,
    }
  }
  return {
    type: 'info' as const,
    message:
      '系统已通过 AI 自动识别章节间的引用关系，您可以修改或删除错误结果，也可以手动补充。',
  }
}

/**
 * 章节引用图抽屉（12 期 AI 分析 + 12.5 期人工评审闭环）。
 *
 * 布局三区：**待评审区** / **已生效区** / **补链表单**。
 * AI 分析期间用 `ConfigProvider componentDisabled` 锁住整个抽屉，
 * 防止「分析还在转圈、用户又点了删除」的并发冲突。
 */
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
  /** 各操作的 loading 分开——共用一个 state 时用户分不清在等哪个。 */
  const [analyzing, setAnalyzing] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [approvingId, setApprovingId] = useState<number | null>(null)
  const [batchApproving, setBatchApproving] = useState(false)
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [detail, setDetail] = useState<ChapterLink | null>(null)
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
  const pendingLinks = useMemo(
    () => links.filter((item) => item.status === 'pending'),
    [links],
  )
  const effectiveLinks = useMemo(
    () => links.filter((item) => item.status === 'approved'),
    [links],
  )
  const hint = hintOf(pendingLinks.length, links.length)
  // 选中的 id 必须仍然在待评审区（重分析后旧 id 会消失）——
  // 在**渲染期**过滤而不是 useEffect 里 setState，避免多一轮渲染。
  const pendingIdSet = useMemo(
    () => new Set(pendingLinks.map((item) => item.id)),
    [pendingLinks],
  )
  const activeSelectedIds = useMemo(
    () => selectedIds.filter((id) => pendingIdSet.has(id)),
    [selectedIds, pendingIdSet],
  )

  const rowSelection: TableRowSelection<ChapterLink> = {
    selectedRowKeys: activeSelectedIds,
    onChange: (keys) => setSelectedIds(keys as number[]),
  }

  async function analyze() {
    setAnalyzing(true)
    try {
      const result = await analyzeChapterLinks(projectId, documentId, versionId)
      message.success(
        `AI 分析完成：${result.chapter_count} 个章节，识别 ${result.analyzed_count} 条引用关系` +
          (result.discarded_count ? `（${result.discarded_count} 条越界已丢弃）` : '') +
          '，请确认后生效',
      )
      setSelectedIds([])
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

  async function approveOne(link: ChapterLink) {
    setApprovingId(link.id)
    try {
      await approveChapterLink(projectId, documentId, versionId, link.id)
      message.success('已采纳，这条引用关系开始生效')
      setSelectedIds((current) => current.filter((id) => id !== link.id))
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setApprovingId(null)
    }
  }

  async function approveSelected() {
    if (activeSelectedIds.length === 0) return
    setBatchApproving(true)
    try {
      const result = await approveChapterLinksBatch(
        projectId,
        documentId,
        versionId,
        activeSelectedIds,
      )
      message.success(`已采纳 ${result.approved_count} 条引用关系`)
      setSelectedIds([])
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setBatchApproving(false)
    }
  }

  async function remove(link: ChapterLink) {
    setDeletingId(link.id)
    try {
      await deleteChapterLink(projectId, documentId, versionId, link.id)
      message.success('已删除这条引用关系')
      setSelectedIds((current) => current.filter((id) => id !== link.id))
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <Drawer
      title="章节引用图"
      width={860}
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
      {/* 分析期间锁住抽屉内所有交互（AI 按钮在 extra 里，不受影响） */}
      <ConfigProvider componentDisabled={analyzing}>
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Alert
            type={hint.type}
            showIcon
            data-testid="chapter-link-hint"
            message={hint.message}
          />

          {analyzing ? (
            <Typography.Text type="secondary" data-testid="chapter-link-analyzing-tip">
              正在调用模型分析章节引用关系，可能需要 1–2 分钟…
            </Typography.Text>
          ) : null}

          {pendingLinks.length > 0 ? (
            <div data-testid="chapter-link-pending-section">
              <Space style={{ marginBottom: 8 }}>
                <Typography.Title level={5} style={{ margin: 0 }}>
                  待评审（{pendingLinks.length}）
                </Typography.Title>
                <Typography.Text type="secondary">
                  已选 {activeSelectedIds.length} 条
                </Typography.Text>
                {canWrite ? (
                  <>
                    <Button
                      type="primary"
                      disabled={activeSelectedIds.length === 0}
                      loading={batchApproving}
                      data-testid="chapter-link-pending-batch-approve-btn"
                      onClick={() => void approveSelected()}
                    >
                      批量采纳
                    </Button>
                    <Button
                      disabled={activeSelectedIds.length === 0}
                      data-testid="chapter-link-pending-clear-btn"
                      onClick={() => setSelectedIds([])}
                    >
                      清空选择
                    </Button>
                  </>
                ) : null}
              </Space>
              <ChapterLinkTable
                links={pendingLinks}
                mode="pending"
                canWrite={canWrite}
                loading={loading}
                deletingId={deletingId}
                approvingId={approvingId}
                rowSelection={canWrite ? rowSelection : undefined}
                emptyText="没有待评审的引用关系"
                onDetail={setDetail}
                onDelete={(link) => void remove(link)}
                onApprove={(link) => void approveOne(link)}
              />
            </div>
          ) : null}

          <div data-testid="chapter-link-effective-section">
            <Typography.Title level={5} style={{ marginTop: 0 }}>
              已生效（{effectiveLinks.length}）
            </Typography.Title>
            <ChapterLinkTable
              links={effectiveLinks}
              mode="effective"
              canWrite={canWrite}
              loading={loading}
              deletingId={deletingId}
              approvingId={approvingId}
              emptyText={
                links.length === 0
                  ? '该版本还没有引用关系'
                  : '还没有生效的引用关系'
              }
              onDetail={setDetail}
              onDelete={(link) => void remove(link)}
              onApprove={(link) => void approveOne(link)}
            />
          </div>

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
                  extra="从这里出发的章节，例如「2.1 登录流程」"
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
                  extra="引用 —— A 提到「见 B」/ 依赖 —— A 的实现依赖 B / 相关 —— A 提到某个功能点或术语"
                  rules={[{ required: true, message: '请选择类型' }]}
                >
                  <Select
                    placeholder="请选择引用关系类型"
                    options={LINK_TYPE_OPTIONS}
                    optionRender={(option) => (
                      <div style={{ lineHeight: 1.4 }}>
                        <div>{option.data.label}</div>
                        <div style={{ fontSize: 12, color: 'rgba(0,0,0,0.45)' }}>
                          {option.data.description}
                        </div>
                      </div>
                    )}
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
                    extra="被引用的章节，例如「3 支付回调」；不能选自己"
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
                    extra="格式：功能:用户登录，如 功能:退款审核 / 术语:订单锁定"
                    rules={[{ required: true, message: '请输入实体名' }]}
                  >
                    <Input
                      placeholder="格式：功能:用户登录，如 功能:退款审核 / 术语:订单锁定"
                      data-testid="chapter-link-entity-input"
                    />
                  </Form.Item>
                )}
                <Button
                  type="primary"
                  loading={submitting}
                  disabled={analyzing}
                  data-testid="chapter-link-create-btn"
                  onClick={() => void submit()}
                >
                  补链
                </Button>
              </Form>
            </div>
          ) : (
            <Typography.Text type="secondary">
              只有项目管理员可以分析、采纳、补链与删除引用图，你可以查看已有关系。
            </Typography.Text>
          )}
        </Space>
      </ConfigProvider>

      <ChapterLinkDetailModal link={detail} onClose={() => setDetail(null)} />
    </Drawer>
  )
}
