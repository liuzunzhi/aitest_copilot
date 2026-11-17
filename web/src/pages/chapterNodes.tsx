import type { ReactNode } from 'react'

import { Typography } from 'antd'

import type { Chapter } from '../api'

/** 章节树渲染（纯展示，深度靠缩进表达）。 */
export function ChapterNodes({ nodes, depth = 0 }: { nodes: Chapter[]; depth?: number }): ReactNode {
  return (
    <>
      {nodes.map((node) => (
        <div key={node.id} data-testid="chapter-node" style={{ paddingLeft: depth * 16 }}>
          <Typography.Text strong={depth === 0}>{node.title}</Typography.Text>
          <Typography.Text type="secondary"> · {node.char_count} 字</Typography.Text>
          {node.children.length > 0 ? (
            <ChapterNodes nodes={node.children} depth={depth + 1} />
          ) : null}
        </div>
      ))}
    </>
  )
}
