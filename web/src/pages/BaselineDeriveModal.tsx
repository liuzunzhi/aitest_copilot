/** 「从文档推导基线」：选文档 / 版本 / 模板，同步跑模型。 */

import { useCallback, useEffect, useState } from 'react'
import { Alert, Form, Modal, Select, Typography, message } from 'antd'
import {
  listAvailablePromptTemplates,
  listDocuments,
  listVersions,
  runBaselineDerive,
} from '../api'
import type {
  AvailablePromptTemplate,
  BaselineDeriveDetail,
  DocVersion,
  DocumentItem,
} from '../api'
import { errorMessage } from '../api/client'

interface Props {
  open: boolean
  projectId: number
  onClose: () => void
  onDerived: (detail: BaselineDeriveDetail) => void
}

export default function BaselineDeriveModal({
  open,
  projectId,
  onClose,
  onDerived,
}: Props) {
  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [versions, setVersions] = useState<DocVersion[]>([])
  const [templates, setTemplates] = useState<AvailablePromptTemplate[]>([])
  const [documentId, setDocumentId] = useState<number | undefined>()
  const [versionId, setVersionId] = useState<number | undefined>()
  const [templateId, setTemplateId] = useState<number | undefined>()
  const [loading, setLoading] = useState(false)

  const reset = useCallback(() => {
    setDocumentId(undefined)
    setVersionId(undefined)
    setTemplateId(undefined)
    setVersions([])
  }, [])

  useEffect(() => {
    if (!open) return
    reset()
    Promise.all([
      listDocuments(projectId),
      listAvailablePromptTemplates('document_parse'),
    ])
      .then(([docs, items]) => {
        setDocuments(docs)
        setTemplates(items)
        setTemplateId(items[0]?.id)
      })
      .catch((error) => message.error(errorMessage(error)))
  }, [open, projectId, reset])

  const changeDocument = useCallback(
    async (value: number | undefined) => {
      setDocumentId(value)
      setVersionId(undefined)
      setVersions([])
      if (!value) return
      try {
        const list = await listVersions(projectId, value)
        const active = list.filter((item) => item.status === 'active')
        setVersions(active)
        setVersionId(active[0]?.id)
      } catch (error) {
        message.error(errorMessage(error))
      }
    },
    [projectId],
  )

  const submit = useCallback(async () => {
    if (!documentId || !versionId || !templateId) {
      message.warning('请选择需求文档、版本和提示词模板')
      return
    }
    setLoading(true)
    try {
      const detail = await runBaselineDerive(projectId, {
        document_id: documentId,
        document_version_id: versionId,
        template_id: templateId,
      })
      message.success('推导完成，请确认候选')
      onClose()
      onDerived(detail)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [documentId, onClose, onDerived, projectId, templateId, versionId])

  return (
    <Modal
      open={open}
      title="从文档推导基线"
      okText="开始推导"
      cancelText="取消"
      confirmLoading={loading}
      onOk={() => void submit()}
      onCancel={() => {
        if (!loading) onClose()
      }}
      maskClosable={!loading}
      closable={!loading}
      destroyOnClose
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="推导结果是候选草稿，确认采纳后才会进入基线结构。"
      />
      <Form layout="vertical">
        <Form.Item label="需求文档" required>
          <Select
            placeholder="选择项目内的文档"
            data-testid="derive-document"
            value={documentId}
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
            data-testid="derive-version"
            value={versionId}
            disabled={!documentId}
            onChange={(value) => setVersionId(value)}
            options={versions.map((item) => ({
              value: item.id,
              label: `v${item.version_no}`,
            }))}
          />
        </Form.Item>
        <Form.Item label="提示词模板" required>
          <Select
            placeholder="选择文档推导模板"
            data-testid="derive-template"
            value={templateId}
            onChange={(value) => setTemplateId(value)}
            options={templates.map((item) => ({
              value: item.id,
              label: item.name,
            }))}
          />
        </Form.Item>
      </Form>
      {loading && (
        <Typography.Text type="secondary">
          正在调用模型分析文档，可能需要 1–2 分钟…
        </Typography.Text>
      )}
    </Modal>
  )
}
