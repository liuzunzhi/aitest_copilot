import { useCallback, useEffect, useState } from 'react'
import { App as AntdApp, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'

import { listBaselines } from '../api'
import type { Baseline } from '../api'
import { errorMessage } from '../api/client'

export default function ProjectBaselinesTab({ projectId }: { projectId: number }) {
  const { message } = AntdApp.useApp()
  const [baselines, setBaselines] = useState<Baseline[]>([])
  const [loading, setLoading] = useState(false)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      setBaselines(await listBaselines(projectId))
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [projectId, message])

  useEffect(() => {
    void reload()
  }, [reload])

  const columns: ColumnsType<Baseline> = [
    {
      title: '基线版本',
      dataIndex: 'version_no',
      width: 110,
      render: (value: number) => <Tag color="blue">V{value}</Tag>,
    },
    { title: '文档', dataIndex: 'document_name' },
    {
      title: '文档版本',
      dataIndex: 'document_version_no',
      width: 110,
      render: (value: number) => `V${value}`,
    },
    { title: '章节数', dataIndex: 'chapter_count', width: 100 },
    {
      title: '快照时间',
      dataIndex: 'created_at',
      width: 200,
      render: (value: string) => new Date(value).toLocaleString(),
    },
  ]

  return (
    <div>
      {baselines.length === 0 && !loading ? (
        <Typography.Text type="secondary">
          暂无基线。在文档页确认某个版本生效后会自动生成快照。
        </Typography.Text>
      ) : null}
      <Table<Baseline>
        rowKey="id"
        columns={columns}
        dataSource={baselines}
        loading={loading}
        pagination={false}
        style={{ marginTop: baselines.length === 0 && !loading ? 0 : 16 }}
        data-testid="baseline-table"
      />
    </div>
  )
}
