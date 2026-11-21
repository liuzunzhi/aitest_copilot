import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  App as AntdApp,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'

import {
  ackTestCase,
  createTestCase,
  createTestCaseAnalysis,
  deleteTestCase,
  deleteTestCaseAnalysis,
  exportTestCases,
  listAvailablePromptTemplates,
  listTestCaseAnalyses,
  listTestCases,
  listTestPoints,
  updateTestCase,
} from '../api'
import type {
  AvailablePromptTemplate,
  TestCase,
  TestCaseAnalysis,
  TestCasePayload,
  TestCasePriority,
  TestCaseType,
  TestPoint,
} from '../api'
import { errorMessage } from '../api/client'
import { isValidationError } from './baselineShared'
import TestCaseDrawer from './TestCaseDrawer'
import TestCaseStepsEditor from './TestCaseStepsEditor'
import {
  CASE_PRIORITY_OPTIONS,
  CASE_SOURCE_LABELS,
  CASE_STATUS_OPTIONS,
  CASE_TYPE_OPTIONS,
  caseAnalysisStatusTag,
  casePriorityTag,
  caseStatusTag,
  caseTypeTag,
  testPointText,
} from './testCaseMeta'

interface Props {
  projectId: number
  /** 发起生成 / 评审 / 手工增删改都限项目管理员（后端 403 NOT_PROJECT_ADMIN）。 */
  canWrite: boolean
}

interface CreateValues {
  template_id: number
  test_point_ids?: number[] | null
}

interface CaseFormValues {
  test_point_id: number
  title: string
  case_type: TestCaseType
  priority: TestCasePriority
  precondition?: string
}

interface EditableStep {
  key: string
  action: string
  expected: string
}

/**
 * 「测试用例」Tab。
 *
 * 两段式布局（与「测试点」Tab 同构）：
 * 上半是生成记录（这次跑了什么、产出多少），下半是用例表（要评审的产物）。
 *
 * **操作列的分工**：详情看内容、评审走抽屉、编辑改元数据、
 * 删除是破坏性动作——按这个顺序从左到右排，常用的在前。
 */
export default function ProjectTestCasesTab({ projectId, canWrite }: Props) {
  const { message } = AntdApp.useApp()
  const [createForm] = Form.useForm<CreateValues>()
  const [caseForm] = Form.useForm<CaseFormValues>()

  const [analyses, setAnalyses] = useState<TestCaseAnalysis[]>([])
  const [cases, setCases] = useState<TestCase[]>([])
  const [loading, setLoading] = useState(false)
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [needsReviewFilter, setNeedsReviewFilter] = useState<boolean | undefined>()
  const [keyword, setKeyword] = useState('')

  // 发起生成弹窗
  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [templates, setTemplates] = useState<AvailablePromptTemplate[]>([])
  const [approvedPoints, setApprovedPoints] = useState<TestPoint[]>([])
  /** 手工新增时可挂**任意**测试点（含 pending / rejected）——与生成的严格口径不同。 */
  const [allPoints, setAllPoints] = useState<TestPoint[]>([])

  // 详情抽屉
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerCase, setDrawerCase] = useState<TestCase | null>(null)

  // 手工新增 / 编辑弹窗：`editingCase` 为 null 表示新增
  const [editOpen, setEditOpen] = useState(false)
  const [editingCase, setEditingCase] = useState<TestCase | null>(null)
  const [saving, setSaving] = useState(false)
  const [stepRows, setStepRows] = useState<EditableStep[]>([])

  const [exporting, setExporting] = useState(false)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const [analysisPage, casePage] = await Promise.all([
        listTestCaseAnalyses(projectId, { page_size: 100 }),
        listTestCases(projectId, {
          status: statusFilter as TestCase['status'] | undefined,
          needs_review: needsReviewFilter,
          page_size: 200,
        }),
      ])
      setAnalyses(analysisPage.items)
      setCases(casePage.items)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [projectId, statusFilter, needsReviewFilter, message])

  useEffect(() => {
    void reload()
  }, [reload])

  async function loadApprovedPoints() {
    try {
      const pointPage = await listTestPoints(projectId, { status: 'approved', page_size: 200 })
      setApprovedPoints(pointPage.items)
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  async function loadAllPoints() {
    try {
      const pointPage = await listTestPoints(projectId, { page_size: 200 })
      setAllPoints(pointPage.items)
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  async function openCreate() {
    setCreateOpen(true)
    try {
      const templateList = await listAvailablePromptTemplates('test_case')
      setTemplates(templateList)
      // 模板默认值要**立刻**落位：用户可能在模板列表回来之前就点「开始生成」，
      // 此时表单校验会因「模板必填」卡住，提交静默失败。
      const current = createForm.getFieldValue('template_id') as number | undefined
      if (templateList.length && !templateList.some((item) => item.id === current)) {
        createForm.setFieldValue('template_id', templateList[0].id)
      }
      // 挂靠下拉可以晚一点填——它不影响提交。
      void loadApprovedPoints()
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  async function submitCreate() {
    let values: CreateValues
    try {
      values = await createForm.validateFields()
    } catch (error) {
      if (isValidationError(error)) return
      throw error
    }
    const pointIds = values.test_point_ids ?? []

    setCreating(true)
    try {
      const detail = await createTestCaseAnalysis(projectId, {
        template_id: values.template_id,
        test_point_ids: pointIds.length ? pointIds : null,
      })
      message.success(
        detail.status === 'succeeded'
          ? `生成完成，产出 ${detail.stats?.case_count ?? detail.cases.length} 条用例`
          : '生成未成功，请在记录里查看原因',
      )
      setCreateOpen(false)
      createForm.resetFields()
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
      await reload()
    } finally {
      setCreating(false)
    }
  }

  async function removeAnalysis(analysis: TestCaseAnalysis) {
    try {
      await deleteTestCaseAnalysis(projectId, analysis.id)
      message.success('生成记录已删除')
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  function openCreateCase() {
    setEditingCase(null)
    caseForm.resetFields()
    caseForm.setFieldsValue({ case_type: 'functional', priority: 'medium' })
    setStepRows([
      { key: 's0', action: '', expected: '' },
    ])
    setEditOpen(true)
    // 挂靠下拉要列**全部**测试点（含 pending / rejected）——
    // 手工补录不该被评审状态卡死；没点过「发起生成」时这里还没加载过。
    void loadAllPoints()
  }

  function openEditCase(testCase: TestCase) {
    setEditingCase(testCase)
    caseForm.resetFields()
    caseForm.setFieldsValue({
      test_point_id: testCase.test_point_id,
      title: testCase.title,
      case_type: testCase.case_type,
      priority: testCase.priority,
      precondition: testCase.precondition ?? '',
    })
    setStepRows(
      (testCase.steps ?? []).map((step, index) => ({
        key: `s${index}`,
        action: step.action,
        expected: step.expected,
      })),
    )
    setEditOpen(true)
  }

  async function submitCase() {
    let values: CaseFormValues
    try {
      values = await caseForm.validateFields()
    } catch (error) {
      if (isValidationError(error)) return
      throw error
    }
    const steps = stepRows
      .map((row) => ({ action: row.action.trim(), expected: row.expected.trim() }))
      .filter((row) => row.action)

    setSaving(true)
    try {
      if (editingCase) {
        await updateTestCase(projectId, editingCase.id, {
          title: values.title,
          case_type: values.case_type,
          priority: values.priority,
          precondition: values.precondition ?? '',
        })
        message.success('用例已更新')
      } else {
        const payload: TestCasePayload = {
          test_point_id: values.test_point_id,
          title: values.title,
          case_type: values.case_type,
          priority: values.priority,
          precondition: values.precondition ?? '',
          steps,
        }
        await createTestCase(projectId, payload)
        message.success('用例已新增')
      }
      setEditOpen(false)
      setEditingCase(null)
      caseForm.resetFields()
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  async function removeCase(testCase: TestCase) {
    try {
      await deleteTestCase(projectId, testCase.id)
      message.success('用例已删除')
      if (drawerCase?.id === testCase.id) setDrawerOpen(false)
      await reload()
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  async function doExport() {
    setExporting(true)
    try {
      const { blob, fileName } = await exportTestCases(projectId, {
        status: statusFilter as TestCase['status'] | undefined,
      })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = fileName
      anchor.click()
      URL.revokeObjectURL(url)
      message.success('用例已导出')
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setExporting(false)
    }
  }

  const pointOptions = useMemo(
    () =>
      approvedPoints.map((point) => ({
        value: point.id,
        label: `#${point.id} · ${point.name}`,
      })),
    [approvedPoints],
  )

  /** 手工挂靠用：所有测试点都可选。 */
  const allPointOptions = useMemo(
    () =>
      allPoints.map((point) => ({
        value: point.id,
        label: `#${point.id} · ${point.name}`,
      })),
    [allPoints],
  )

  const filteredCases = useMemo(() => {
    const word = keyword.trim()
    if (!word) return cases
    return cases.filter((item) =>
      [item.title, item.test_point_name, item.target_name].some((text) =>
        text?.includes(word),
      ),
    )
  }, [cases, keyword])

  const analysisColumns: ColumnsType<TestCaseAnalysis> = [
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
      render: (status: string) => caseAnalysisStatusTag(status),
    },
    {
      title: '模板',
      key: 'template',
      render: (_: unknown, analysis) =>
        `${analysis.template_name ?? '—'} · v${analysis.template_version}`,
    },
    {
      title: '统计',
      key: 'stats',
      width: 220,
      render: (_: unknown, analysis) => (
        <span data-testid={`test-case-analysis-stats-${analysis.id}`}>
          {analysis.stats?.case_count ?? 0} 条用例 / {analysis.stats?.step_count ?? 0} 个步骤
          <br />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            测试点 {analysis.stats?.test_point_count ?? 0} · 丢弃{' '}
            {analysis.stats?.discarded_count ?? 0}
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
            render: (_: unknown, analysis: TestCaseAnalysis) => (
              <Popconfirm
                title="删除生成记录会连带删除它产出的用例，确认？"
                okText="删除"
                cancelText="取消"
                onConfirm={() => removeAnalysis(analysis)}
              >
                <Button
                  size="small"
                  danger
                  data-testid={`test-case-analysis-delete-${analysis.id}`}
                >
                  删除
                </Button>
              </Popconfirm>
            ),
          },
        ]
      : []),
  ]

  const caseColumns: ColumnsType<TestCase> = [
    {
      title: '用例名称',
      key: 'title',
      render: (_: unknown, testCase) => (
        <span data-testid={`test-case-title-${testCase.id}`}>
          {testCase.title}
          {testCase.needs_review ? (
            <Typography.Text type="warning" style={{ marginLeft: 8, fontSize: 12 }}>
              待复核
            </Typography.Text>
          ) : null}
        </span>
      ),
    },
    {
      title: '所属测试点',
      key: 'test_point',
      width: 220,
      render: (_: unknown, testCase) =>
        testPointText(testCase.test_point_id, testCase.test_point_name),
    },
    {
      title: '类型',
      dataIndex: 'case_type',
      width: 80,
      render: (value: string) => caseTypeTag(value),
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      width: 80,
      render: (value: string) => casePriorityTag(value),
    },
    {
      title: '步骤',
      key: 'steps',
      width: 70,
      render: (_: unknown, testCase) => `${testCase.steps?.length ?? 0} 步`,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (status: string, testCase) => (
        <span data-testid={`test-case-status-${testCase.id}`}>{caseStatusTag(status)}</span>
      ),
    },
    {
      title: '来源',
      key: 'source',
      width: 120,
      render: (_: unknown, testCase) =>
        `${CASE_SOURCE_LABELS[testCase.source_type] ?? testCase.source_type}${
          testCase.analysis_id ? ` #${testCase.analysis_id}` : ''
        }`,
    },
    {
      title: '操作',
      key: 'actions',
      width: 250,
      render: (_: unknown, testCase) => (
        <Space size={4}>
          <Button
            size="small"
            data-testid={`test-case-detail-btn-${testCase.id}`}
            onClick={() => {
              setDrawerCase(testCase)
              setDrawerOpen(true)
            }}
          >
            详情
          </Button>
          {canWrite && testCase.status === 'pending' ? (
            <Button
              size="small"
              type="primary"
              data-testid={`test-case-review-btn-${testCase.id}`}
              onClick={() => {
                setDrawerCase(testCase)
                setDrawerOpen(true)
              }}
            >
              评审
            </Button>
          ) : null}
          {canWrite && testCase.needs_review ? (
            <Button
              size="small"
              type="primary"
              ghost
              data-testid={`test-case-ack-btn-${testCase.id}`}
              onClick={async () => {
                try {
                  await ackTestCase(projectId, testCase.id)
                  message.success('已确认复核')
                  await reload()
                } catch (error) {
                  message.error(errorMessage(error))
                }
              }}
            >
              确认复核
            </Button>
          ) : null}
          {canWrite ? (
            <>
              <Button
                size="small"
                data-testid={`test-case-edit-btn-${testCase.id}`}
                onClick={() => openEditCase(testCase)}
              >
                编辑
              </Button>
              <Popconfirm
                title="确认删除该用例？"
                okText="删除"
                cancelText="取消"
                onConfirm={() => removeCase(testCase)}
              >
                <Button size="small" danger data-testid={`test-case-delete-btn-${testCase.id}`}>
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
              data-testid="test-case-analysis-create-btn"
            >
              发起生成
            </Button>
          ) : null
        }
      >
        {!canWrite ? (
          <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
            只有项目管理员可以发起生成、评审与手工增删改，你可以查看测试用例。
          </Typography.Text>
        ) : null}
        <Table<TestCaseAnalysis>
          rowKey="id"
          columns={analysisColumns}
          dataSource={analyses}
          loading={loading}
          pagination={false}
          locale={{ emptyText: '还没有测试用例生成记录' }}
          data-testid="test-case-analysis-table"
        />
      </Card>

      <Card
        title="测试用例"
        size="small"
        extra={
          <Space>
            <Button
              onClick={doExport}
              loading={exporting}
              data-testid="test-case-export-btn"
            >
              导出 Excel
            </Button>
            {canWrite ? (
              <Button onClick={openCreateCase} data-testid="test-case-create-btn">
                手工新增
              </Button>
            ) : null}
          </Space>
        }
      >
        <Space wrap style={{ marginBottom: 12 }}>
          <Input
            allowClear
            placeholder="搜索用例名称 / 测试点"
            style={{ width: 220 }}
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            data-testid="test-case-keyword-input"
          />
          <Select
            allowClear
            placeholder="状态"
            style={{ width: 140 }}
            options={CASE_STATUS_OPTIONS}
            value={statusFilter}
            onChange={(value) => setStatusFilter(value)}
            data-testid="test-case-status-filter"
          />
          <Select
            allowClear
            placeholder="待复核"
            style={{ width: 140 }}
            options={[
              { value: true, label: '仅看待复核' },
              { value: false, label: '仅看无需复核' },
            ]}
            value={needsReviewFilter}
            onChange={(value) => setNeedsReviewFilter(value)}
            data-testid="test-case-needs-review-filter"
          />
          <Button onClick={() => void reload()} data-testid="test-case-refresh-btn">
            刷新
          </Button>
        </Space>
        <Table<TestCase>
          rowKey="id"
          columns={caseColumns}
          dataSource={filteredCases}
          loading={loading}
          pagination={false}
          scroll={{ x: 1200 }}
          locale={{ emptyText: '还没有测试用例' }}
          data-testid="test-case-table"
        />
      </Card>

      <Modal
        open={createOpen}
        title="发起测试用例生成"
        onCancel={() => {
          setCreateOpen(false)
          createForm.resetFields()
        }}
        onOk={submitCreate}
        confirmLoading={creating}
        okText="开始生成"
        cancelText="取消"
        okButtonProps={{ 'data-testid': 'test-case-submit-btn' }}
        width={640}
        destroyOnHidden
      >
        <Form form={createForm} layout="vertical" requiredMark={false}>
          <Form.Item
            name="template_id"
            label="模板"
            rules={[{ required: true, message: '请选择提示词模板' }]}
          >
            <Select
              placeholder={templates.length ? '选择测试用例模板' : '暂无可用模板'}
              disabled={templates.length === 0}
              options={templates.map((item) => ({
                value: item.id,
                label: `${item.name} · v${item.version_no}`,
              }))}
              data-testid="test-case-template-select"
            />
          </Form.Item>
          <Form.Item
            name="test_point_ids"
            label="测试点"
            extra="留空表示全部评审通过的测试点；指定后只处理这些点（任一不满足会整体拒绝）"
          >
            <Select
              mode="multiple"
              allowClear
              placeholder={pointOptions.length ? '选择要生成用例的测试点' : '暂无评审通过的测试点'}
              disabled={pointOptions.length === 0}
              showSearch
              optionFilterProp="label"
              options={pointOptions}
              data-testid="test-case-points-select"
            />
          </Form.Item>
        </Form>
        {templates.length === 0 ? (
          <Typography.Text type="secondary">
            请先在系统设置中启用 `task_type='test_case'` 的提示词模板。
          </Typography.Text>
        ) : null}
      </Modal>

      <Modal
        open={editOpen}
        title={editingCase ? '编辑测试用例' : '手工新增测试用例'}
        onCancel={() => {
          setEditOpen(false)
          setEditingCase(null)
        }}
        onOk={submitCase}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        okButtonProps={{ 'data-testid': 'test-case-edit-submit-btn' }}
        width={720}
        destroyOnHidden
      >
        <Form form={caseForm} layout="vertical" requiredMark={false}>
          <Form.Item
            name="test_point_id"
            label="所属测试点"
            rules={[{ required: true, message: '请选择所属测试点' }]}
          >
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="选择测试点"
              options={allPointOptions}
              data-testid="test-case-point-select"
            />
          </Form.Item>
          <Form.Item
            name="title"
            label="用例名称"
            rules={[{ required: true, message: '请输入用例名称' }]}
          >
            <Input maxLength={255} data-testid="test-case-title-input" />
          </Form.Item>
          <Form.Item name="case_type" label="用例类型">
            <Select options={CASE_TYPE_OPTIONS} data-testid="test-case-type-select" />
          </Form.Item>
          <Form.Item name="priority" label="优先级">
            <Select options={CASE_PRIORITY_OPTIONS} data-testid="test-case-priority-select" />
          </Form.Item>
          <Form.Item name="precondition" label="前置条件">
            <Input.TextArea rows={2} maxLength={1000} data-testid="test-case-precondition-input" />
          </Form.Item>
          <Form.Item label="操作步骤与预期结果">
            <TestCaseStepsEditor value={stepRows} onChange={setStepRows} />
          </Form.Item>
        </Form>
      </Modal>

      <TestCaseDrawer
        open={drawerOpen}
        projectId={projectId}
        testCase={drawerCase}
        canWrite={canWrite}
        onClose={() => setDrawerOpen(false)}
        onUpdated={(updated) => {
          setDrawerCase(updated)
          void reload()
        }}
      />
    </div>
  )
}
