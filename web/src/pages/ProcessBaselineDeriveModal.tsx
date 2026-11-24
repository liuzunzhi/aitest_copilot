import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  App as AntdApp,
  Button,
  Form,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'

import {
  createProcessScenarios,
  listAvailablePromptTemplates,
  listDocuments,
  listVersions,
  runProcessDerive,
} from '../api'
import type {
  AvailablePromptTemplate,
  DocVersion,
  DocumentItem,
  ProcessDerivedScenario,
  ProcessScenarioCreate,
} from '../api'
import { errorMessage } from '../api/client'

interface Props {
  open: boolean
  projectId: number
  onClose: () => void
  /** 采纳成功后回传（父级据此刷新场景表）。 */
  onAdopted: (count: number) => void
}

/**
 * 「从文档反推流程基线」弹窗。
 *
 * **照抄 04 的 `BaselineDeriveModal.tsx` 改写**：选文档 → 选**生效**版本 →
 * 选模板 → 「开始反推」→ 候选表（**勾选**）→「采纳为场景」。
 *
 * 三条刻意的口径：
 *
 * 1. **候选默认全不勾**（PRD 1.4 原则二：高风险行为人工确认）——
 *    09 期的扫描清单同理。
 * 2. **反推是同步接口**：一次可能跑几十秒，所以按钮要有 loading，
 *    用户知道在等（与 04 的推导同一策略）。
 * 3. **反推只出候选、不写表**：采纳走 `POST /scenarios` 批量落库。
 */
export default function ProcessBaselineDeriveModal({
  open,
  projectId,
  onClose,
  onAdopted,
}: Props) {
  const { message } = AntdApp.useApp()
  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [versions, setVersions] = useState<DocVersion[]>([])
  const [templates, setTemplates] = useState<AvailablePromptTemplate[]>([])
  const [documentId, setDocumentId] = useState<number | undefined>()
  const [versionId, setVersionId] = useState<number | undefined>()
  const [templateId, setTemplateId] = useState<number | undefined>()
  const [running, setRunning] = useState(false)
  const [adopting, setAdopting] = useState(false)
  const [candidates, setCandidates] = useState<ProcessDerivedScenario[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const reset = useCallback(() => {
    setDocumentId(undefined)
    setVersionId(undefined)
    setTemplateId(undefined)
    setVersions([])
    setCandidates([])
    setSelected(new Set())
  }, [])

  useEffect(() => {
    if (!open) return
    reset()
    Promise.all([
      listDocuments(projectId),
      listAvailablePromptTemplates('process_baseline'),
    ])
      .then(([docs, items]) => {
        setDocuments(docs)
        setTemplates(items)
        setTemplateId(items[0]?.id)
      })
      .catch((error) => message.error(errorMessage(error)))
  }, [open, projectId, reset, message])

  const changeDocument = useCallback(
    async (value: number | undefined) => {
      setDocumentId(value)
      setVersionId(undefined)
      setVersions([])
      setCandidates([])
      setSelected(new Set())
      if (!value) return
      try {
        const list = await listVersions(projectId, value)
        // **只有生效版本能反推**（非生效版本的正文不可信）。
        const active = list.filter((item) => item.status === 'active')
        setVersions(active)
        setVersionId(active[0]?.id)
      } catch (error) {
        message.error(errorMessage(error))
      }
    },
    [projectId, message],
  )

  const run = useCallback(async () => {
    if (!documentId || !versionId || !templateId) {
      message.warning('请选择需求文档、版本和提示词模板')
      return
    }
    setRunning(true)
    try {
      const result = await runProcessDerive(projectId, {
        document_id: documentId,
        document_version_id: versionId,
        template_id: templateId,
      })
      setCandidates(result.scenarios)
      // **默认全不勾**：反推出的候选是高风险行为，要人工确认后才落库。
      setSelected(new Set())
      message.success(
        `反推完成，得到 ${result.candidate_count} 个候选，请确认后采纳`,
      )
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setRunning(false)
    }
  }, [documentId, message, projectId, templateId, versionId])

  async function adopt() {
    const picked = candidates.filter((_, index) => selected.has(`c-${index}`))
    if (!picked.length) {
      message.warning('请先勾选要采纳的候选')
      return
    }
    const payload: ProcessScenarioCreate[] = picked.map((candidate) => ({
      name: candidate.name,
      description: candidate.description,
      precondition: candidate.precondition,
      source_type: 'document_derived',
      source_document_id: documentId ?? null,
      source_version_id: versionId ?? null,
      source_chapter_id: candidate.source_chapter_id,
      source_chapter_title: candidate.source_chapter_title,
      source_method: 'baseline_reverse',
      steps: candidate.steps.map((step) => ({
        action: step.action,
        expected: step.expected,
      })),
      links: candidate.links.map((link) => ({
        target_type: link.target_type,
        target_id: link.target_id,
      })),
    }))
    setAdopting(true)
    try {
      const result = await createProcessScenarios(projectId, payload)
      message.success(`已采纳 ${result.created} 个场景`)
      onAdopted(result.created)
      onClose()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setAdopting(false)
    }
  }

  const columns: ColumnsType<ProcessDerivedScenario> = [
    {
      title: '场景名称',
      dataIndex: 'name',
      render: (value: string, _candidate, index) => (
        <span data-testid={`process-baseline-derive-name-${index}`}>{value}</span>
      ),
    },
    {
      title: '前置条件',
      dataIndex: 'precondition',
      width: 200,
      render: (value: string | null) => value || '—',
    },
    {
      title: '步骤数',
      key: 'steps',
      width: 80,
      render: (_: unknown, candidate) => candidate.steps.length,
    },
    {
      title: '关联数',
      key: 'links',
      width: 80,
      render: (_: unknown, candidate) => candidate.links.length,
    },
    {
      title: '置信度',
      dataIndex: 'confidence',
      width: 90,
      render: (value: number | null) =>
        value === null || value === undefined ? '—' : value.toFixed(2),
    },
    {
      title: '来源章节',
      dataIndex: 'source_chapter_title',
      width: 180,
      render: (value: string | null) => value || '—',
    },
  ]

  const chapterTag = useMemo(() => {
    const titles = candidates
      .map((candidate) => candidate.source_chapter_title)
      .filter((title): title is string => Boolean(title))
    return [...new Set(titles)]
  }, [candidates])

  return (
    <Modal
      open={open}
      title="从文档反推流程基线"
      okText="开始反推"
      cancelText="取消"
      confirmLoading={running}
      onOk={() => void run()}
      onCancel={() => {
        if (!running) onClose()
      }}
      maskClosable={!running}
      closable={!running}
      okButtonProps={{ 'data-testid': 'process-baseline-derive-run-btn' }}
      width={960}
      destroyOnHidden
    >
      <Space
        direction="vertical"
        size={12}
        style={{ width: '100%' }}
        data-testid="process-baseline-derive-modal"
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="反推结果是候选草稿，确认采纳后才会进入场景列表。"
          description="候选默认全不勾选——反推出的场景是高风险行为，需要人工确认（PRD 1.4 原则二）。"
        />
        <Form layout="vertical">
          <Form.Item label="需求文档" required>
            <Select
              placeholder="选择项目内的文档"
              data-testid="process-baseline-derive-doc-select"
              value={documentId}
              disabled={running}
              onChange={(value) => void changeDocument(value)}
              options={documents.map((item) => ({
                value: item.id,
                label: item.name,
              }))}
            />
          </Form.Item>
          <Form.Item label="文档版本" required>
            <Select
              placeholder={documentId ? '选择生效版本' : '请先选择文档'}
              data-testid="process-baseline-derive-version-select"
              value={versionId}
              disabled={!documentId || running}
              onChange={(value) => setVersionId(value)}
              options={versions.map((item) => ({
                value: item.id,
                label: `v${item.version_no}`,
              }))}
            />
          </Form.Item>
          <Form.Item label="提示词模板" required>
            <Select
              placeholder="选择流程基线反推模板"
              data-testid="process-baseline-derive-template-select"
              value={templateId}
              disabled={running}
              onChange={(value) => setTemplateId(value)}
              options={templates.map((item) => ({
                value: item.id,
                label: `${item.name} · v${item.version_no}`,
              }))}
            />
          </Form.Item>
        </Form>
        {running ? (
          <Typography.Text type="secondary">
            正在调用模型分析文档，可能需要 1–2 分钟…
          </Typography.Text>
        ) : null}

        {candidates.length ? (
          <>
            <Space wrap>
              <Tag color="blue">候选 {candidates.length} 个</Tag>
              {chapterTag.map((title) => (
                <Tag key={title}>{title}</Tag>
              ))}
            </Space>
            <Table<ProcessDerivedScenario>
              rowKey={(_: unknown, index?: number) => `c-${index ?? 0}`}
              size="small"
              columns={columns}
              dataSource={candidates}
              pagination={false}
              scroll={{ y: 260 }}
              locale={{ emptyText: '没有反推出候选' }}
              data-testid="process-baseline-derive-table"
              rowSelection={{
                selectedRowKeys: [...selected],
                onChange: (keys) => setSelected(new Set(keys as string[])),
                getCheckboxProps: (_: unknown, index?: number) => ({
                  name: `c-${index ?? 0}`,
                  // 勾选框的 testid 落在真正的 <input> 上，e2e 直接点它。
                  'data-testid': `process-baseline-derive-check-${index ?? 0}`,
                }),
              }}
            />
            <Space>
              <Button
                type="primary"
                loading={adopting}
                disabled={!selected.size}
                onClick={() => void adopt()}
                data-testid="process-baseline-derive-confirm-btn"
              >
                采纳为场景
              </Button>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                勾选 {selected.size} / {candidates.length}
              </Typography.Text>
            </Space>
          </>
        ) : null}
      </Space>
    </Modal>
  )
}
