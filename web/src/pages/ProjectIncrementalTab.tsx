import { useCallback, useEffect, useMemo, useState } from 'react'
import { App as AntdApp, Button, Card, Form, Select, Table, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'

import {
  createIncrementalAnalysis,
  fetchIncrementalAnalysis,
  listAvailablePromptTemplates,
  listBaselineRevisions,
  listDocuments,
  listIncrementalAnalyses,
  listIncrementalConclusions,
} from '../api'
import type {
  AvailablePromptTemplate,
  BaselineRevision,
  DocumentItem,
  IncrementalAnalysis,
  IncrementalConclusion,
} from '../api'
import { errorMessage } from '../api/client'
import { formatSnapshotVersion, isValidationError } from './baselineShared'
import ProjectIncrementalDrawer from './ProjectIncrementalDrawer'
import { GRANULARITY_LABEL, statusTag } from './incrementalMeta'

/** 第二遍模板与第一遍同属 `task_type='incremental'`，靠名字前缀区分，不能进第一遍下拉。 */
const SECOND_PASS_NAME_KEYWORD = '第二遍'

interface Props {
  projectId: number
  /** 发起分析限项目管理员（后端 403 NOT_PROJECT_ADMIN）。 */
  canWrite: boolean
}

export default function ProjectIncrementalTab({ projectId, canWrite }: Props) {
  const { message } = AntdApp.useApp()
  const [form] = Form.useForm<{
    template_id: number
    baseline_revision_id: number
    document_version_id: number
  }>()

  const [analyses, setAnalyses] = useState<IncrementalAnalysis[]>([])
  const [revisions, setRevisions] = useState<BaselineRevision[]>([])
  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [templates, setTemplates] = useState<AvailablePromptTemplate[]>([])
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)

  const [drawerOpen, setDrawerOpen] = useState(false)
  const [detail, setDetail] = useState<IncrementalAnalysis | null>(null)
  const [conclusions, setConclusions] = useState<IncrementalConclusion[]>([])
  const [detailLoading, setDetailLoading] = useState(false)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const [analysisPage, revisionPage, documentList, templateList] = await Promise.all([
        listIncrementalAnalyses(projectId, { page_size: 100 }),
        listBaselineRevisions(projectId, { status: 'approved', page_size: 200 }),
        listDocuments(projectId),
        listAvailablePromptTemplates('incremental'),
      ])
      setAnalyses(analysisPage.items)
      setRevisions(revisionPage.items)
      setDocuments(documentList)
      const firstPass = templateList.filter(
        (item) => !item.name.includes(SECOND_PASS_NAME_KEYWORD),
      )
      setTemplates(firstPass)
      // 首次加载时默认选中第一个可用模板；已被停用的旧选择不保留
      const current = form.getFieldValue('template_id') as number | undefined
      if (firstPass.length && !firstPass.some((item) => item.id === current)) {
        form.setFieldValue('template_id', firstPass[0].id)
      }
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [projectId, message, form])

  useEffect(() => {
    void reload()
  }, [reload])

  const revisionOptions = useMemo(
    () =>
      revisions.map((revision) => ({
        value: revision.id,
        label: `${formatSnapshotVersion(revision.version_no)} · ${new Date(
          revision.created_at,
        ).toLocaleString()}`,
      })),
    [revisions],
  )

  // 只有生效版本能参与分析，待确认 / 已归档 / 已作废的版本不进下拉
  const versionOptions = useMemo(
    () =>
      documents
        .filter((document) => document.active_version)
        .map((document) => ({
          value: document.active_version!.id,
          label: `${document.name} · V${document.active_version!.version_no}`,
        })),
    [documents],
  )

  async function submitAnalysis() {
    try {
      const values = await form.validateFields()
      setCreating(true)
      const analysis = await createIncrementalAnalysis(projectId, {
        template_id: values.template_id,
        baseline_revision_id: values.baseline_revision_id,
        document_version_id: values.document_version_id,
        split_granularity: 'chapter',
      })
      message.success(
        analysis.status === 'succeeded'
          ? `分析完成，产出 ${analysis.stats?.conclusion_count ?? 0} 条结论`
          : '分析未成功，请在详情里查看原因',
      )
      await reload()
    } catch (error) {
      if (isValidationError(error)) return
      message.error(errorMessage(error))
      // 模型失败时后端已把记录落成 failed，刷新列表让失败记录可见
      await reload()
    } finally {
      setCreating(false)
    }
  }

  async function openDetail(analysis: IncrementalAnalysis) {
    setDrawerOpen(true)
    setDetail(analysis)
    setConclusions([])
    setDetailLoading(true)
    try {
      const [fresh, page] = await Promise.all([
        fetchIncrementalAnalysis(projectId, analysis.id),
        listIncrementalConclusions(projectId, analysis.id, { page_size: 200 }),
      ])
      setDetail(fresh)
      setConclusions(page.items)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setDetailLoading(false)
    }
  }

  /** 第二遍跑完后重新拉详情，让抽屉里的状态与统计同步。 */
  async function refreshDetail() {
    if (!detail) return
    try {
      const fresh = await fetchIncrementalAnalysis(projectId, detail.id)
      setDetail(fresh)
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  const columns: ColumnsType<IncrementalAnalysis> = [
    {
      title: '发起时间',
      dataIndex: 'created_at',
      width: 180,
      render: (value: string) => new Date(value).toLocaleString(),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (status: string) => statusTag(status),
    },
    {
      title: '基线快照',
      dataIndex: 'baseline_revision_version',
      width: 110,
      render: (value: string | null) => value ?? '—',
    },
    {
      title: '文档版本',
      key: 'document',
      render: (_: unknown, analysis) => (
        <span data-testid={`incremental-doc-${analysis.id}`}>
          {analysis.document_name ?? '—'} · V{analysis.document_version_no ?? '—'}
        </span>
      ),
    },
    {
      title: '章节 / 结论 / 丢弃',
      key: 'stats',
      width: 200,
      render: (_: unknown, analysis) => {
        const stats = analysis.stats
        return (
          <span data-testid={`incremental-stats-${analysis.id}`}>
            {stats?.chapter_count ?? 0} / {stats?.conclusion_count ?? 0} /{' '}
            {stats?.discarded_count ?? 0}
            <br />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              第二遍 {analysis.second_pass_status ?? '未执行'}
            </Typography.Text>
          </span>
        )
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 100,
      render: (_: unknown, analysis) => (
        <Button
          size="small"
          data-testid={`incremental-detail-btn-${analysis.id}`}
          onClick={() => openDetail(analysis)}
        >
          详情
        </Button>
      ),
    },
  ]

  return (
    <div>
      {canWrite ? (
        <Card title="发起分析" size="small" style={{ marginBottom: 16 }}>
          <Form
            form={form}
            layout="inline"
            initialValues={{ split_granularity: 'chapter' }}
            onFinish={submitAnalysis}
          >
            <Form.Item
              name="baseline_revision_id"
              label="基线快照"
              rules={[{ required: true, message: '请选择审核通过的基线快照' }]}
            >
              <Select
                style={{ width: 260 }}
                placeholder="选择审核通过的快照"
                showSearch
                optionFilterProp="label"
                options={revisionOptions}
                data-testid="incremental-baseline-select"
              />
            </Form.Item>
            <Form.Item
              name="document_version_id"
              label="文档版本"
              rules={[{ required: true, message: '请选择生效的文档版本' }]}
            >
              <Select
                style={{ width: 240 }}
                placeholder="选择生效版本"
                showSearch
                optionFilterProp="label"
                options={versionOptions}
                data-testid="incremental-version-select"
              />
            </Form.Item>
            <Form.Item
              name="template_id"
              label="模板"
              rules={[{ required: true, message: '请选择提示词模板' }]}
            >
              {/* 模板来自「系统设置 → 提示词模板」，只列启用的第一遍模板 */}
              <Select
                style={{ width: 240 }}
                placeholder={templates.length ? '选择提示词模板' : '暂无可用模板'}
                disabled={templates.length === 0}
                options={templates.map((item) => ({
                  value: item.id,
                  label: `${item.name} · v${item.version_no}`,
                }))}
                data-testid="incremental-template-select"
              />
            </Form.Item>
            <Form.Item label="切分粒度">
              <Select
                style={{ width: 170 }}
                value="chapter"
                disabled
                options={[{ value: 'chapter', label: GRANULARITY_LABEL }]}
                data-testid="incremental-granularity-select"
              />
            </Form.Item>
            <Form.Item>
              <Button
                type="primary"
                htmlType="submit"
                loading={creating}
                disabled={templates.length === 0}
                data-testid="incremental-create-btn"
              >
                发起分析
              </Button>
            </Form.Item>
          </Form>
          {templates.length === 0 ? (
            <Typography.Text type="secondary" style={{ marginTop: 8, display: 'block' }}>
              请先在系统设置中启用提示词模板，再发起分析。
            </Typography.Text>
          ) : null}
          {revisionOptions.length === 0 || versionOptions.length === 0 ? (
            <Typography.Text type="secondary" style={{ marginTop: 8, display: 'block' }}>
              发起分析需要一份审核通过的基线快照和一个生效的文档版本：
              先在「基线管理」提交并审核通过，再到「文档」确认版本生效。
            </Typography.Text>
          ) : null}
        </Card>
      ) : (
        <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
          只有项目管理员可以发起增量分析，你可以查看历史记录与结论。
        </Typography.Text>
      )}

      <Card title="分析记录" size="small">
        <Table<IncrementalAnalysis>
          rowKey="id"
          columns={columns}
          dataSource={analyses}
          loading={loading}
          pagination={false}
          locale={{ emptyText: '还没有增量分析记录' }}
          data-testid="incremental-analysis-table"
        />
      </Card>

      <ProjectIncrementalDrawer
        open={drawerOpen}
        analysis={detail}
        conclusions={conclusions}
        loading={detailLoading}
        canWrite={canWrite}
        onClose={() => setDrawerOpen(false)}
        onRefresh={refreshDetail}
      />
    </div>
  )
}
