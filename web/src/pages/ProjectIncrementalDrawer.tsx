import { Alert, Descriptions, Drawer, Space, Table, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'

import type { DiscardedConclusion, IncrementalAnalysis, IncrementalConclusion } from '../api'
import IncrementalApply from './IncrementalApply'
import IncrementalSecondPass from './IncrementalSecondPass'
import {
  DISCARD_LABELS,
  GRANULARITY_LABEL,
  TEMPLATE_LABEL,
  TARGET_LABELS,
  labelTag,
  secondPassStatusTag,
  statusTag,
} from './incrementalMeta'

interface Props {
  open: boolean
  analysis: IncrementalAnalysis | null
  conclusions: IncrementalConclusion[]
  loading: boolean
  /** 触发第二遍与裁决限项目管理员。 */
  canWrite: boolean
  onClose: () => void
  /** 第二遍跑完后刷新父级持有的分析详情。 */
  onRefresh: () => void
}

/** 一次分析的详情抽屉：元信息 + 局部结论 + 丢弃明细 + 第二遍区块。 */
export default function ProjectIncrementalDrawer({
  open,
  analysis,
  conclusions,
  loading,
  canWrite,
  onClose,
  onRefresh,
}: Props) {
  const conclusionColumns: ColumnsType<IncrementalConclusion> = [
    { title: '章节', dataIndex: 'chapter_title' },
    {
      title: '目标',
      dataIndex: 'target_id',
      width: 130,
      render: (targetId: number, row) =>
        `${TARGET_LABELS[row.target_type] ?? row.target_type} #${targetId}`,
    },
    {
      title: '标签',
      dataIndex: 'label_type',
      width: 90,
      render: (labelType: string) => labelTag(labelType),
    },
    {
      title: '置信度',
      dataIndex: 'confidence',
      width: 90,
      render: (value: number | null) => (value === null ? '—' : value.toFixed(2)),
    },
    { title: '理由', dataIndex: 'rationale', render: (value: string | null) => value ?? '—' },
  ]

  const discardedColumns: ColumnsType<DiscardedConclusion> = [
    { title: '章节', dataIndex: 'chapter_title' },
    {
      title: '目标',
      dataIndex: 'target_id',
      width: 130,
      render: (targetId: number, row) =>
        `${TARGET_LABELS[row.target_type] ?? row.target_type} #${targetId}`,
    },
    {
      title: '原标签',
      dataIndex: 'label_type',
      width: 90,
      render: (labelType: string) => labelTag(labelType),
    },
    { title: '丢弃原因', dataIndex: 'code', render: (code: string) => DISCARD_LABELS[code] ?? code },
  ]

  const stats = analysis?.stats

  return (
    <Drawer
      title={analysis ? `分析记录 #${analysis.id}` : '分析记录'}
      width={820}
      open={open}
      onClose={onClose}
      loading={loading}
    >
      {analysis ? (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Descriptions size="small" column={2} bordered>
            <Descriptions.Item label="状态">{statusTag(analysis.status)}</Descriptions.Item>
            <Descriptions.Item label="切分粒度">
              {analysis.split_granularity === 'chapter'
                ? GRANULARITY_LABEL
                : analysis.split_granularity}
            </Descriptions.Item>
            <Descriptions.Item label="模板">
              {analysis.template_name ?? TEMPLATE_LABEL}
            </Descriptions.Item>
            <Descriptions.Item label="供应商">{analysis.provider}</Descriptions.Item>
            <Descriptions.Item label="基线快照">
              {analysis.baseline_revision_version ?? '—'}
            </Descriptions.Item>
            <Descriptions.Item label="文档版本">
              {analysis.document_name ?? '—'} · V{analysis.document_version_no ?? '—'}
            </Descriptions.Item>
            <Descriptions.Item label="章节数">{stats?.chapter_count ?? 0}</Descriptions.Item>
            <Descriptions.Item label="结论 / 丢弃">
              {stats?.conclusion_count ?? 0} / {stats?.discarded_count ?? 0}
            </Descriptions.Item>
            <Descriptions.Item label="发起时间">
              {new Date(analysis.created_at).toLocaleString()}
            </Descriptions.Item>
            <Descriptions.Item label="结束时间">
              {analysis.finished_at ? new Date(analysis.finished_at).toLocaleString() : '—'}
            </Descriptions.Item>
            <Descriptions.Item label="第二遍">
              {secondPassStatusTag(analysis.second_pass_status)}
            </Descriptions.Item>
            <Descriptions.Item label="第二遍结束时间">
              {analysis.second_pass_finished_at
                ? new Date(analysis.second_pass_finished_at).toLocaleString()
                : '—'}
            </Descriptions.Item>
          </Descriptions>

          {analysis.status === 'failed' ? (
            <Alert
              type="error"
              showIcon
              data-testid="incremental-failure-alert"
              message={analysis.error_message ?? analysis.error_code ?? '分析失败'}
              description={
                stats?.failed_chapter_title
                  ? `失败章节：${stats.failed_chapter_title}；已完成章节的结论已保留。`
                  : '已完成章节的结论已保留，可先排查模板或模型返回。'
              }
            />
          ) : null}

          <div>
            <Typography.Title level={5} style={{ marginTop: 0 }}>
              局部结论
            </Typography.Title>
            <Table<IncrementalConclusion>
              size="small"
              rowKey="id"
              columns={conclusionColumns}
              dataSource={conclusions}
              pagination={false}
              loading={loading}
              locale={{ emptyText: '本次分析没有可落库的结论' }}
              data-testid="incremental-conclusion-table"
            />
          </div>

          {stats?.discarded?.length ? (
            <div>
              <Typography.Title level={5} style={{ marginTop: 0 }}>
                丢弃明细
              </Typography.Title>
              <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
                丢弃的结论只留痕，不写业务表；其中「新增」由第二遍统一处理。
              </Typography.Paragraph>
              <Table<DiscardedConclusion>
                size="small"
                rowKey={(row) => `${row.chapter_id}-${row.target_type}-${row.target_id}-${row.code}`}
                columns={discardedColumns}
                dataSource={stats.discarded}
                pagination={false}
                data-testid="incremental-discarded-table"
              />
            </div>
          ) : null}

          <IncrementalSecondPass
            projectId={analysis.project_id}
            analysis={analysis}
            canWrite={canWrite}
            onChanged={onRefresh}
          />

          <IncrementalApply
            projectId={analysis.project_id}
            analysis={analysis}
            canWrite={canWrite}
            onChanged={onRefresh}
          />
        </Space>
      ) : null}
    </Drawer>
  )
}
