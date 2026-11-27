import { Descriptions, Modal, Typography } from 'antd'

import type { ChapterLink } from '../api'
import { linkSourceTag, linkStatusTag, linkTypeTag } from './incrementalMeta'

interface Props {
  /** 为 `null` 时弹窗关闭。 */
  link: ChapterLink | null
  onClose: () => void
}

/**
 * 引用关系详情弹窗（12.5 期 · 可解释性）。
 *
 * 用户诉求：「AI 分析的结果必须支持查看细节……展示大模型给出的分析理由
 * （rationale）和置信度（confidence），让用户能根据理由判断是否采纳。」
 *
 * **对所有来源的边都可用**：规则边与人工边没有 `rationale`，显示「无」。
 * 只给 AI 边加按钮会让表格里有的行有、有的行没有，界面不整齐。
 */
export default function ChapterLinkDetailModal({ link, onClose }: Props) {
  return (
    <Modal
      title="引用关系详情"
      open={link !== null}
      onCancel={onClose}
      footer={null}
      width={560}
    >
      <div data-testid="chapter-link-detail-modal">
        {link ? (
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="源章节">
              {link.from_chapter_title ?? `章节 #${link.from_chapter_id}`}
            </Descriptions.Item>
            <Descriptions.Item label="目标">
              {link.to_chapter_id !== null
                ? (link.to_chapter_title ?? `章节 #${link.to_chapter_id}`)
                : `实体「${link.entity}」`}
            </Descriptions.Item>
            <Descriptions.Item label="关系类型">
              {linkTypeTag(link.link_type)}
            </Descriptions.Item>
            <Descriptions.Item label="来源">
              {linkSourceTag(link.source)}
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              {linkStatusTag(link.status)}
            </Descriptions.Item>
            <Descriptions.Item label="置信度">
              {link.confidence === null ? '无' : link.confidence.toFixed(2)}
            </Descriptions.Item>
            <Descriptions.Item label="分析理由">
              <Typography.Paragraph
                style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}
                data-testid="chapter-link-detail-rationale"
              >
                {link.rationale ?? '无'}
              </Typography.Paragraph>
            </Descriptions.Item>
          </Descriptions>
        ) : null}
      </div>
    </Modal>
  )
}
