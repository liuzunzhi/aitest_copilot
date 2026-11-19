import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  App as AntdApp,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'

import {
  createTestPoint,
  createTestPointAnalysis,
  deleteTestPoint,
  deleteTestPointAnalysis,
  listAvailablePromptTemplates,
  listBaselineRevisions,
  listChapters,
  listDocuments,
  listIncrementalAnalyses,
  listTestPointAnalyses,
  listTestPoints,
  updateTestPoint,
} from '../api'
import type {
  AvailablePromptTemplate,
  BaselineRevision,
  Chapter,
  DocumentItem,
  IncrementalAnalysis,
  TestPoint,
  TestPointAnalysis,
  TestPointUpdatePayload,
} from '../api'
import { errorMessage } from '../api/client'
import { formatSnapshotVersion, isValidationError } from './baselineShared'
import TestPointDrawer from './TestPointDrawer'
import {
  POINT_STATUS_OPTIONS,
  PRIORITY_OPTIONS,
  SOURCE_LABELS,
  TARGET_LABELS,
  TARGET_TYPE_OPTIONS,
  analysisStatusTag,
  pointStatusTag,
  priorityTag,
  targetText,
} from './testPointMeta'

interface Props {
  projectId: number
  /** 发起生成 / 评审 / 手工增删改都限项目管理员（后端 403 NOT_PROJECT_ADMIN）。 */
  canWrite: boolean
}

interface CreateValues {
  template_id: number
  analysis_id?: number | null
  baseline_revision_id?: number | null
  document_version_id?: number | null
  chapter_ids?: number[] | null
}

interface PointFormValues {
  name: string
  target_type: 'function' | 'feature_point'
  target_id: number
  priority: 'high' | 'medium' | 'low'
  precondition?: string
  verification?: string
}

/** 章节树拍平成下拉项；缩进用全角空格，保持层级可读。 */
function flattenChapters(chapters: Chapter[], depth = 0): Array<{ value: number; label: string }> {
  return chapters.flatMap((chapter) => [
    { value: chapter.id, label: `${'　'.repeat(depth)}${chapter.title}` },
    ...flattenChapters(chapter.children ?? [], depth + 1),
  ])
}

export default function ProjectTestPointsTab({ projectId, canWrite }: Props) {
  const { message, modal } = AntdApp.useApp()
  const [createForm] = Form.useForm<CreateValues>()
  const [pointForm] = Form.useForm<PointFormValues>()

  const [analyses, setAnalyses] = useState<TestPointAnalysis[]>([])
  const [points, setPoints] = useState<TestPoint[]>([])
  const [loading, setLoading] = useState(false)
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [targetTypeFilter, setTargetTypeFilter] = useState<string | undefined>()

  // 发起生成弹窗的数据源
  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [templates, setTemplates] = useState<AvailablePromptTemplate[]>([])
  const [incrementalAnalyses, setIncrementalAnalyses] = useState<IncrementalAnalysis[]>([])
  const [revisions, setRevisions] = useState<BaselineRevision[]>([])
  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [chapterOptions, setChapterOptions] = useState<Array<{ value: number; label: string }>>([])
  // 打开弹窗时快照一份「已通过」的测试点，用于冲突二次确认
  const [approvedPoints, setApprovedPoints] = useState<TestPoint[]>([])

  // 详情抽屉
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerPoint, setDrawerPoint] = useState<TestPoint | null>(null)

  // 手工新增 / 编辑弹窗：`editingPoint` 为 null 表示新增
  const [editOpen, setEditOpen] = useState(false)
  const [editingPoint, setEditingPoint] = useState<TestPoint | null>(null)
  const [saving, setSaving] = useState(false)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const [analysisPage, pointPage] = await Promise.all([
        listTestPointAnalyses(projectId, { page_size: 100 }),
        listTestPoints(projectId, {
          status: statusFilter as TestPoint['status'] | undefined,
          target_type: targetTypeFilter as TestPoint['target_type'] | undefined,
          page_size: 200,
        }),
      ])
      setAnalyses(analysisPage.items)
      setPoints(pointPage.items)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [projectId, statusFilter, targetTypeFilter, message])

  useEffect(() => {
    void reload()
  }, [reload])

  async function loadChapterOptions(versionId: number | undefined) {
    if (!versionId) {
      setChapterOptions([])
      return
    }
    const document = documents.find((item) => item.active_version?.id === versionId)
    if (!document) {
      setChapterOptions([])
      return
    }
    try {
      const tree = await listChapters(projectId, document.id, versionId)
      setChapterOptions(flattenChapters(tree))
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  async function openCreate() {
    setCreateOpen(true)
    try {
      const [templateList, analysisPage, revisionPage, documentList, approvedPage] =
        await Promise.all([
          listAvailablePromptTemplates('test_point'),
          listIncrementalAnalyses(projectId, { page_size: 100 }),
          listBaselineRevisions(projectId, { status: 'approved', page_size: 200 }),
          listDocuments(projectId),
          listTestPoints(projectId, { status: 'approved', page_size: 200 }),
        ])
      setTemplates(templateList)
      setIncrementalAnalyses(analysisPage.items.filter((item) => item.status === 'succeeded'))
      setRevisions(revisionPage.items)
      setDocuments(documentList)
      setApprovedPoints(approvedPage.items)
      const current = createForm.getFieldValue('template_id') as number | undefined
      if (templateList.length && !templateList.some((item) => item.id === current)) {
        createForm.setFieldValue('template_id', templateList[0].id)
      }
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  function handleCreateValuesChange(changed: Record<string, unknown>) {
    if ('analysis_id' in changed) {
      const analysis = incrementalAnalyses.find((item) => item.id === changed.analysis_id)
      const versionId = analysis?.document_version_id ?? undefined
      createForm.setFieldValue('document_version_id', versionId)
      createForm.setFieldValue('chapter_ids', [])
      void loadChapterOptions(versionId)
    }
    if ('document_version_id' in changed) {
      createForm.setFieldValue('chapter_ids', [])
      void loadChapterOptions(changed.document_version_id as number | undefined)
    }
  }

  /** 所选章节已有评审通过的测试点时二次确认——服务端不静默覆盖。 */
  async function confirmOverwrite(chapterIds: number[]): Promise<boolean> {
    if (!chapterIds.length) return true
    const conflicts = approvedPoints.filter(
      (item) => item.chapter_id !== null && chapterIds.includes(item.chapter_id),
    )
    if (!conflicts.length) return true
    return new Promise<boolean>((resolve) => {
      modal.confirm({
        title: '将覆盖已有评审结果',
        content: `所选章节已有 ${conflicts.length} 条评审通过的测试点，继续将为其生成新的测试点。`,
        okText: '继续生成',
        cancelText: '取消',
        onOk: () => resolve(true),
        onCancel: () => resolve(false),
      })
    })
  }

  async function submitCreate() {
    let values: CreateValues
    try {
      values = await createForm.validateFields()
    } catch (error) {
      if (isValidationError(error)) return
      throw error
    }
    if (!values.analysis_id && !values.baseline_revision_id) {
      message.error('至少选择增量分析记录或基线快照之一')
      return
    }
    const chapterIds = values.chapter_ids ?? []
    if (!(await confirmOverwrite(chapterIds))) return

    setCreating(true)
    try {
      const detail = await createTestPointAnalysis(projectId, {
        template_id: values.template_id,
        analysis_id: values.analysis_id ?? null,
        baseline_revision_id: values.baseline_revision_id ?? null,
        document_version_id: values.document_version_id ?? null,
        chapter_ids: chapterIds.length ? chapterIds : null,
      })
      message.success(
        detail.status === 'succeeded'
          ? `生成完成，产出 ${detail.stats?.test_point_count ?? detail.points.length} 条测试点`
          : '生成未成功，请在记录里查看原因',
      )
      setCreateOpen(false)
      createForm.resetFields()
      setChapterOptions([])
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
      // 失败时后端已把记录落成 failed，刷新列表让失败记录可见
      await reload()
    } finally {
      setCreating(false)
    }
  }

  async function removeAnalysis(analysis: TestPointAnalysis) {
    try {
      await deleteTestPointAnalysis(projectId, analysis.id)
      message.success('生成记录已删除')
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  function openCreatePoint() {
    setEditingPoint(null)
    pointForm.resetFields()
    pointForm.setFieldsValue({ target_type: 'function', priority: 'medium' })
    setEditOpen(true)
  }

  function openEditPoint(point: TestPoint) {
    setEditingPoint(point)
    pointForm.resetFields()
    pointForm.setFieldsValue({
      name: point.name,
      target_type: point.target_type,
      target_id: point.target_id,
      priority: point.priority,
      precondition: point.precondition ?? '',
      verification: point.verification ?? '',
    })
    setEditOpen(true)
  }

  async function submitPoint() {
    let values: PointFormValues
    try {
      values = await pointForm.validateFields()
    } catch (error) {
      if (isValidationError(error)) return
      throw error
    }
    setSaving(true)
    try {
      if (editingPoint) {
        const payload: TestPointUpdatePayload = {
          name: values.name,
          priority: values.priority,
          precondition: values.precondition ?? '',
          verification: values.verification ?? '',
        }
        await updateTestPoint(projectId, editingPoint.id, payload)
        message.success('测试点已更新')
      } else {
        await createTestPoint(projectId, {
          name: values.name,
          target_type: values.target_type,
          target_id: values.target_id,
          priority: values.priority,
          precondition: values.precondition ?? '',
          verification: values.verification ?? '',
        })
        message.success('测试点已新增')
      }
      setEditOpen(false)
      setEditingPoint(null)
      pointForm.resetFields()
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  async function removePoint(point: TestPoint) {
    try {
      await deleteTestPoint(projectId, point.id)
      message.success('测试点已删除')
      if (drawerPoint?.id === point.id) setDrawerOpen(false)
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  const analysisOptions = useMemo(
    () =>
      incrementalAnalyses.map((item) => ({
        value: item.id,
        label: `分析 #${item.id} · ${item.document_name ?? '未关联文档'}`,
      })),
    [incrementalAnalyses],
  )

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

  const analysisColumns: ColumnsType<TestPointAnalysis> = [
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
      render: (status: string) => analysisStatusTag(status),
    },
    {
      title: '模板',
      key: 'template',
      render: (_: unknown, analysis) =>
        `${analysis.template_name ?? '—'} · v${analysis.template_version}`,
    },
    {
      title: '文档',
      dataIndex: 'document_name',
      render: (value: string | null) => value ?? '—',
    },
    {
      title: '统计',
      key: 'stats',
      width: 200,
      render: (_: unknown, analysis) => (
        <span data-testid={`test-point-analysis-stats-${analysis.id}`}>
          {analysis.stats?.test_point_count ?? 0} 条 / 丢弃 {analysis.stats?.discarded_count ?? 0}
          <br />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            章节 {analysis.stats?.chapter_count ?? 0}
          </Typography.Text>
        </span>
      ),
    },
    ...(canWrite
      ? [
          {
            title: '操作',
            key: 'actions',
            width: 100,
            render: (_: unknown, analysis: TestPointAnalysis) => (
              <Popconfirm
                title="删除生成记录会连带删除它产出的测试点，确认？"
                okText="删除"
                cancelText="取消"
                onConfirm={() => removeAnalysis(analysis)}
              >
                <Button size="small" danger data-testid={`test-point-analysis-delete-${analysis.id}`}>
                  删除
                </Button>
              </Popconfirm>
            ),
          },
        ]
      : []),
  ]

  const pointColumns: ColumnsType<TestPoint> = [
    {
      title: '名称',
      key: 'name',
      render: (_: unknown, point) => (
        <span data-testid={`test-point-name-${point.id}`}>
          {point.name}
          {point.needs_review ? (
            <Typography.Text type="warning" style={{ marginLeft: 8, fontSize: 12 }}>
              待复核
            </Typography.Text>
          ) : null}
        </span>
      ),
    },
    {
      title: '目标',
      key: 'target',
      width: 240,
      render: (_: unknown, point) =>
        targetText(point.target_type, point.target_id, point.target_name),
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      width: 90,
      render: (priority: string) => priorityTag(priority),
    },
    {
      title: '章节',
      dataIndex: 'chapter_title',
      width: 150,
      render: (value: string | null) => value ?? '—',
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (status: string, point) => (
        <span data-testid={`test-point-status-${point.id}`}>{pointStatusTag(status)}</span>
      ),
    },
    {
      title: '来源',
      key: 'source',
      width: 130,
      render: (_: unknown, point) =>
        `${SOURCE_LABELS[point.source_type] ?? point.source_type}${
          point.analysis_id ? ` #${point.analysis_id}` : ''
        }`,
    },
    {
      title: '操作',
      key: 'actions',
      width: 240,
      render: (_: unknown, point) => (
        <Space size={4} wrap>
          <Button
            size="small"
            data-testid={`test-point-detail-btn-${point.id}`}
            onClick={() => {
              setDrawerPoint(point)
              setDrawerOpen(true)
            }}
          >
            详情
          </Button>
          {canWrite && point.status === 'pending' ? (
            <Button
              size="small"
              type="primary"
              data-testid={`test-point-review-btn-${point.id}`}
              onClick={() => {
                setDrawerPoint(point)
                setDrawerOpen(true)
              }}
            >
              评审
            </Button>
          ) : null}
          {canWrite ? (
            <>
              <Button
                size="small"
                data-testid={`test-point-edit-btn-${point.id}`}
                onClick={() => openEditPoint(point)}
              >
                编辑
              </Button>
              <Popconfirm
                title="确认删除该测试点？"
                okText="删除"
                cancelText="取消"
                onConfirm={() => removePoint(point)}
              >
                <Button size="small" danger data-testid={`test-point-delete-btn-${point.id}`}>
                  删除
                </Button>
              </Popconfirm>
            </>
          ) : null}
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Card
        title="生成记录"
        size="small"
        style={{ marginBottom: 16 }}
        extra={
          canWrite ? (
            <Button
              type="primary"
              onClick={openCreate}
              data-testid="test-point-analysis-create-btn"
            >
              发起生成
            </Button>
          ) : null
        }
      >
        {!canWrite ? (
          <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
            只有项目管理员可以发起生成、评审与手工增删改，你可以查看测试点。
          </Typography.Text>
        ) : null}
        <Table<TestPointAnalysis>
          rowKey="id"
          columns={analysisColumns}
          dataSource={analyses}
          loading={loading}
          pagination={false}
          locale={{ emptyText: '还没有测试点生成记录' }}
          data-testid="test-point-analysis-table"
        />
      </Card>

      <Card
        title="测试点"
        size="small"
        extra={
          canWrite ? (
            <Button onClick={openCreatePoint} data-testid="test-point-create-btn">
              手工新增
            </Button>
          ) : null
        }
      >
        <Space wrap style={{ marginBottom: 12 }}>
          <Select
            allowClear
            placeholder="状态"
            style={{ width: 140 }}
            options={POINT_STATUS_OPTIONS}
            value={statusFilter}
            onChange={(value) => setStatusFilter(value)}
            data-testid="test-point-status-filter"
          />
          <Select
            allowClear
            placeholder="目标类型"
            style={{ width: 140 }}
            options={TARGET_TYPE_OPTIONS}
            value={targetTypeFilter}
            onChange={(value) => setTargetTypeFilter(value)}
            data-testid="test-point-target-filter"
          />
          <Button onClick={() => void reload()}>刷新</Button>
        </Space>
        <Table<TestPoint>
          rowKey="id"
          columns={pointColumns}
          dataSource={points}
          loading={loading}
          pagination={false}
          scroll={{ x: 980 }}
          locale={{ emptyText: '还没有测试点' }}
          data-testid="test-point-table"
        />
      </Card>

      <Modal
        open={createOpen}
        title="发起测试点生成"
        onCancel={() => {
          setCreateOpen(false)
          createForm.resetFields()
          setChapterOptions([])
        }}
        onOk={submitCreate}
        confirmLoading={creating}
        okText="开始生成"
        cancelText="取消"
        okButtonProps={{ 'data-testid': 'test-point-submit-btn' }}
        width={640}
        destroyOnHidden
      >
        <Form
          form={createForm}
          layout="vertical"
          requiredMark={false}
          onValuesChange={handleCreateValuesChange}
        >
          <Form.Item
            name="template_id"
            label="模板"
            rules={[{ required: true, message: '请选择提示词模板' }]}
          >
            <Select
              placeholder={templates.length ? '选择测试点模板' : '暂无可用模板'}
              disabled={templates.length === 0}
              options={templates.map((item) => ({
                value: item.id,
                label: `${item.name} · v${item.version_no}`,
              }))}
              data-testid="test-point-template-select"
            />
          </Form.Item>
          <Form.Item name="analysis_id" label="增量分析记录">
            <Select
              allowClear
              placeholder="选择已成功的增量分析（与基线快照至少选一个）"
              showSearch
              optionFilterProp="label"
              options={analysisOptions}
              data-testid="test-point-analysis-select"
            />
          </Form.Item>
          <Form.Item name="baseline_revision_id" label="基线快照">
            <Select
              allowClear
              placeholder="选择审核通过的基线快照"
              showSearch
              optionFilterProp="label"
              options={revisionOptions}
              data-testid="test-point-revision-select"
            />
          </Form.Item>
          <Form.Item name="document_version_id" label="文档版本">
            <Select
              allowClear
              placeholder="不限定文档时可留空"
              showSearch
              optionFilterProp="label"
              options={versionOptions}
              data-testid="test-point-version-select"
            />
          </Form.Item>
          <Form.Item name="chapter_ids" label="章节">
            <Select
              mode="multiple"
              allowClear
              placeholder={chapterOptions.length ? '留空表示全文档' : '先选择文档版本'}
              disabled={chapterOptions.length === 0}
              options={chapterOptions}
              data-testid="test-point-chapters-select"
            />
          </Form.Item>
        </Form>
        {templates.length === 0 ? (
          <Typography.Text type="secondary">
            请先在系统设置中启用 `task_type='test_point'` 的提示词模板。
          </Typography.Text>
        ) : null}
      </Modal>

      <Modal
        open={editOpen}
        title={editingPoint ? '编辑测试点' : '手工新增测试点'}
        onCancel={() => {
          setEditOpen(false)
          setEditingPoint(null)
        }}
        onOk={submitPoint}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        okButtonProps={{ 'data-testid': 'test-point-edit-submit-btn' }}
        destroyOnHidden
      >
        <Form form={pointForm} layout="vertical" requiredMark={false}>
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入测试点名称' }]}
          >
            <Input maxLength={255} data-testid="test-point-name-input" />
          </Form.Item>
          {editingPoint ? (
            <Form.Item label="目标">
              <Typography.Text>
                {targetText(
                  editingPoint.target_type,
                  editingPoint.target_id,
                  editingPoint.target_name,
                )}
              </Typography.Text>
            </Form.Item>
          ) : (
            <>
              <Form.Item
                name="target_type"
                label="目标类型"
                rules={[{ required: true, message: '请选择目标类型' }]}
              >
                <Select options={TARGET_TYPE_OPTIONS} data-testid="test-point-target-type-select" />
              </Form.Item>
              <Form.Item
                name="target_id"
                label="目标 ID"
                rules={[{ required: true, message: '请输入功能或功能点 ID' }]}
                extra={`填写${TARGET_LABELS.function}或${TARGET_LABELS.feature_point}的 ID`}
              >
                <InputNumber min={1} style={{ width: '100%' }} data-testid="test-point-target-id-input" />
              </Form.Item>
            </>
          )}
          <Form.Item
            name="priority"
            label="优先级"
            rules={[{ required: true, message: '请选择优先级' }]}
          >
            <Select options={PRIORITY_OPTIONS} data-testid="test-point-priority-select" />
          </Form.Item>
          <Form.Item name="precondition" label="前置条件">
            <Input.TextArea rows={2} maxLength={1000} data-testid="test-point-precondition-input" />
          </Form.Item>
          <Form.Item name="verification" label="验证要点">
            <Input.TextArea rows={3} maxLength={2000} data-testid="test-point-verification-input" />
          </Form.Item>
        </Form>
      </Modal>

      <TestPointDrawer
        open={drawerOpen}
        projectId={projectId}
        point={drawerPoint}
        canWrite={canWrite}
        onClose={() => setDrawerOpen(false)}
        onReviewed={(updated) => {
          setDrawerPoint(updated)
          void reload()
        }}
      />
    </div>
  )
}
