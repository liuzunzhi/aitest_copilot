/** 推导结果抽屉的候选树渲染：Checkbox + 改名 + 出处 + 冲突提示。 */

import { Checkbox, Input, Select, Space, Tag, Tooltip, Typography } from 'antd'
import type { DataNode } from 'antd/es/tree'
import type { BaselineDeriveCandidate, BaselineModule } from '../api'

export interface DeriveNodeOptions {
  selected: Set<number>
  names: Record<number, string>
  reuseChoice: Record<number, number | undefined>
  existingModules: BaselineModule[]
  onToggle: (candidateId: number, checked: boolean) => void
  onRename: (candidateId: number, name: string) => void
  onReuseChoice: (candidateId: number, moduleId: number | undefined) => void
}

const TYPE_META: Record<string, { label: string; color: string }> = {
  module: { label: '模块', color: 'blue' },
  function: { label: '功能', color: 'geekblue' },
  feature_point: { label: '功能点', color: 'default' },
}

function chapterTag(candidate: BaselineDeriveCandidate) {
  if (!candidate.source_chapter_title) return null
  return <Tag>出处：{candidate.source_chapter_title}</Tag>
}

function confidenceText(candidate: BaselineDeriveCandidate) {
  if (candidate.confidence === null) return null
  return (
    <Typography.Text type="secondary">
      置信度 {Math.round(candidate.confidence * 100)}%
    </Typography.Text>
  )
}

function rationaleHint(candidate: BaselineDeriveCandidate) {
  if (!candidate.rationale) return null
  return (
    <Tooltip title={candidate.rationale}>
      <Typography.Text type="secondary" style={{ cursor: 'help' }}>
        依据
      </Typography.Text>
    </Tooltip>
  )
}

function moduleTitle(candidate: BaselineDeriveCandidate, options: DeriveNodeOptions) {
  const name = options.names[candidate.id] ?? candidate.name
  const conflict = options.existingModules.find((item) => item.name === name)
  const checked = options.selected.has(candidate.id)

  return (
    <Space wrap data-testid={`derive-node-${candidate.id}`}>
      <Checkbox
        checked={checked}
        data-testid={`derive-select-${candidate.id}`}
        onChange={(event) => options.onToggle(candidate.id, event.target.checked)}
      />
      <Tag color={TYPE_META.module.color}>模块</Tag>
      <Input
        size="small"
        style={{ width: 180 }}
        value={name}
        data-testid={`derive-name-${candidate.id}`}
        onChange={(event) => options.onRename(candidate.id, event.target.value)}
      />
      {chapterTag(candidate)}
      {confidenceText(candidate)}
      {rationaleHint(candidate)}
      {conflict && (
        <>
          <Tag color="red" data-testid={`derive-conflict-${candidate.id}`}>
            已存在同名模块
          </Tag>
          {checked && (
            <Select
              size="small"
              allowClear
              placeholder="复用已有模块"
              style={{ width: 170 }}
              value={options.reuseChoice[candidate.id]}
              data-testid={`derive-reuse-${candidate.id}`}
              onChange={(value) => options.onReuseChoice(candidate.id, value)}
              options={options.existingModules.map((item) => ({
                value: item.id,
                label: `${item.name}（#${item.id}）`,
              }))}
            />
          )}
        </>
      )}
    </Space>
  )
}

function simpleTitle(candidate: BaselineDeriveCandidate) {
  return (
    <Space wrap>
      <Tag color={TYPE_META[candidate.entity_type].color}>
        {TYPE_META[candidate.entity_type].label}
      </Tag>
      <span>{candidate.name}</span>
      {chapterTag(candidate)}
      {confidenceText(candidate)}
      {rationaleHint(candidate)}
    </Space>
  )
}

function buildNode(
  candidate: BaselineDeriveCandidate,
  options: DeriveNodeOptions,
): DataNode {
  const children = (candidate.children ?? []).map((child) =>
    buildNode(child, options),
  )
  return {
    key: `c-${candidate.id}`,
    title:
      candidate.entity_type === 'module'
        ? moduleTitle(candidate, options)
        : simpleTitle(candidate),
    children: children.length ? children : undefined,
  }
}

export function buildDeriveTreeData(
  candidates: BaselineDeriveCandidate[],
  options: DeriveNodeOptions,
): DataNode[] {
  return candidates.map((candidate) => buildNode(candidate, options))
}
