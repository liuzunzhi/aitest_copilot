import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  App as AntdApp,
  Button,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'

import {
  activateVersion,
  downloadVersion,
  listChapters,
  listDocuments,
  listVersions,
  uploadDocument,
  voidVersion,
} from '../api'
import type { Chapter, DocVersion, DocumentItem } from '../api'
import { errorMessage } from '../api/client'
import ChapterLinkDrawer from './ChapterLinkDrawer'
import { ChapterNodes } from './chapterNodes'

const VERSION_STATUS_LABELS: Record<string, string> = {
  pending: '待确认',
  active: '已生效',
  archived: '已归档',
  void: '已作废',
}

const VERSION_STATUS_COLORS: Record<string, string> = {
  pending: 'orange',
  active: 'green',
  archived: 'blue',
  void: 'default',
}

export default function ProjectDocumentsTab({
  projectId,
  canWrite,
  onChanged,
}: {
  projectId: number
  canWrite: boolean
  onChanged: () => void
}) {
  const { message } = AntdApp.useApp()
  const fileRef = useRef<HTMLInputElement>(null)
  const versionFileRef = useRef<HTMLInputElement>(null)

  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadingVersion, setUploadingVersion] = useState(false)

  const [versionDoc, setVersionDoc] = useState<DocumentItem | null>(null)
  const [versions, setVersions] = useState<DocVersion[]>([])

  const [chapterTitle, setChapterTitle] = useState<string | null>(null)
  const [chapters, setChapters] = useState<Chapter[]>([])

  const [linkVersion, setLinkVersion] = useState<{ documentId: number; versionId: number } | null>(
    null,
  )

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      setDocuments(await listDocuments(projectId))
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [projectId, message])

  useEffect(() => {
    void reload()
  }, [reload])

  async function pickFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setUploading(true)
    try {
      const result = await uploadDocument(projectId, file)
      message.success(`已上传 ${result.document.name}，解析出 ${result.version.chapter_count} 个章节`)
      await reload()
      onChanged()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setUploading(false)
    }
  }

  async function pickVersionFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || !versionDoc) return
    setUploadingVersion(true)
    try {
      const result = await uploadDocument(projectId, file, versionDoc.id)
      message.success(`已上传 V${result.version.version_no}，待确认后才会生成基线`)
      await refreshVersions(versionDoc)
      onChanged()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setUploadingVersion(false)
    }
  }

  async function openVersions(doc: DocumentItem) {
    setVersionDoc(doc)
    try {
      setVersions(await listVersions(projectId, doc.id))
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  async function refreshVersions(doc: DocumentItem) {
    setVersions(await listVersions(projectId, doc.id))
    await reload()
    onChanged()
  }

  async function activate(doc: DocumentItem, version: DocVersion) {
    try {
      const result = await activateVersion(projectId, doc.id, version.id)
      message.success(`已生效，生成基线 V${result.baseline.version_no}`)
      await refreshVersions(doc)
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  async function discard(doc: DocumentItem, version: DocVersion) {
    try {
      await voidVersion(projectId, doc.id, version.id)
      message.success('版本已作废')
      await refreshVersions(doc)
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  async function openChapters(doc: DocumentItem, version: DocVersion) {
    try {
      const tree = await listChapters(projectId, doc.id, version.id)
      setChapters(tree)
      setChapterTitle(`${doc.name} · V${version.version_no} 章节结构`)
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  async function download(doc: DocumentItem, version: DocVersion) {
    try {
      const { blob, fileName } = await downloadVersion(projectId, doc.id, version.id)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = fileName
      anchor.click()
      URL.revokeObjectURL(url)
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  const documentColumns: ColumnsType<DocumentItem> = [
    { title: '文档名', dataIndex: 'name' },
    { title: '版本数', dataIndex: 'version_count', width: 90 },
    { title: '待确认', dataIndex: 'pending_count', width: 90 },
    {
      title: '生效版本',
      dataIndex: 'active_version',
      width: 180,
      render: (version: DocVersion | null) =>
        version ? (
          <Space size={4}>
            <Tag color="green">V{version.version_no}</Tag>
            <Typography.Text type="secondary">{version.chapter_count} 章</Typography.Text>
          </Space>
        ) : (
          <Typography.Text type="secondary">未生效</Typography.Text>
        ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 220,
      render: (_: unknown, doc) => (
        <Space size={8}>
          <Button size="small" data-testid={`versions-${doc.id}`} onClick={() => openVersions(doc)}>
            版本
          </Button>
          <Button
            size="small"
            data-testid={`download-${doc.id}`}
            disabled={!doc.active_version}
            onClick={() => doc.active_version && download(doc, doc.active_version)}
          >
            下载
          </Button>
        </Space>
      ),
    },
  ]

  const versionColumns: ColumnsType<DocVersion> = [
    {
      title: '版本',
      dataIndex: 'version_no',
      width: 80,
      render: (value: number) => `V${value}`,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (status: string) => (
        <Tag color={VERSION_STATUS_COLORS[status] ?? 'default'}>
          {VERSION_STATUS_LABELS[status] ?? status}
        </Tag>
      ),
    },
    { title: '章节数', dataIndex: 'chapter_count', width: 90 },
    {
      title: '上传时间',
      dataIndex: 'created_at',
      render: (value: string) => new Date(value).toLocaleString(),
    },
    {
      title: '操作',
      key: 'actions',
      width: 280,
      render: (_: unknown, version) =>
        versionDoc ? (
          <Space size={8}>
            <Button
              size="small"
              data-testid={`chapters-${version.id}`}
              onClick={() => openChapters(versionDoc, version)}
            >
              章节
            </Button>
            <Button
              size="small"
              data-testid={`chapter-link-btn-${version.id}`}
              onClick={() =>
                setLinkVersion({ documentId: versionDoc.id, versionId: version.id })
              }
            >
              引用图
            </Button>
            {version.status === 'pending' && canWrite ? (
              <>
                <Button
                  size="small"
                  type="primary"
                  data-testid={`activate-${version.id}`}
                  onClick={() => activate(versionDoc, version)}
                >
                  确认生效
                </Button>
                <Popconfirm
                  title="作废后不可恢复，确认作废？"
                  okText="作废"
                  cancelText="取消"
                  okButtonProps={{ 'data-testid': `void-ok-${version.id}` }}
                  onConfirm={() => discard(versionDoc, version)}
                >
                  <Button size="small" danger data-testid={`void-${version.id}`}>
                    作废
                  </Button>
                </Popconfirm>
              </>
            ) : null}
          </Space>
        ) : null,
    },
  ]

  const chapterSummary = useMemo(() => chapters.length, [chapters])

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button
          type="primary"
          data-testid="upload-doc"
          loading={uploading}
          disabled={!canWrite}
          onClick={() => fileRef.current?.click()}
        >
          上传文档
        </Button>
        <Typography.Text type="secondary">支持 .md / .docx / .txt，单个不超过 10MB</Typography.Text>
        <input
          ref={fileRef}
          type="file"
          accept=".md,.docx,.txt"
          data-testid="doc-file-input"
          style={{ display: 'none' }}
          onChange={pickFile}
        />
      </Space>

      <Table<DocumentItem>
        rowKey="id"
        columns={documentColumns}
        dataSource={documents}
        loading={loading}
        pagination={false}
        data-testid="document-table"
      />

      <Modal
        open={versionDoc !== null}
        title={versionDoc ? `${versionDoc.name} · 版本历史` : ''}
        footer={null}
        width={760}
        onCancel={() => setVersionDoc(null)}
        destroyOnHidden
      >
        <Space style={{ marginBottom: 12 }}>
          <Button
            size="small"
            data-testid="upload-version"
            loading={uploadingVersion}
            disabled={!canWrite}
            onClick={() => versionFileRef.current?.click()}
          >
            上传新版本
          </Button>
          <Typography.Text type="secondary">同一文档多次上传即多版本，确认后各自生成基线</Typography.Text>
          <input
            ref={versionFileRef}
            type="file"
            accept=".md,.docx,.txt"
            data-testid="version-file-input"
            style={{ display: 'none' }}
            onChange={pickVersionFile}
          />
        </Space>
        <Table<DocVersion>
          rowKey="id"
          columns={versionColumns}
          dataSource={versions}
          pagination={false}
          data-testid="version-table"
        />
      </Modal>

      <Modal
        open={chapterTitle !== null}
        title={chapterTitle ?? ''}
        footer={null}
        width={640}
        onCancel={() => setChapterTitle(null)}
        destroyOnHidden
      >
        <Typography.Text type="secondary">共 {chapterSummary} 个一级章节</Typography.Text>
        <div data-testid="chapter-tree" style={{ marginTop: 12 }}>
          <ChapterNodes nodes={chapters} />
        </div>
      </Modal>

      <ChapterLinkDrawer
        open={linkVersion !== null}
        projectId={projectId}
        documentId={linkVersion?.documentId ?? 0}
        versionId={linkVersion?.versionId ?? 0}
        canWrite={canWrite}
        onClose={() => setLinkVersion(null)}
      />
    </div>
  )
}
