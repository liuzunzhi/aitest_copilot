/** 推导结果抽屉：候选树 + 勾选 + 改名 / 复用 + 采纳。 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Drawer,
  Empty,
  Space,
  Tag,
  Tree,
  Typography,
  message,
} from 'antd'
import {
  adoptBaselineDerive,
  listBaselineModules,
} from '../api'
import type {
  BaselineDeriveCandidate,
  BaselineDeriveDetail,
  BaselineModule,
  DeriveAdoptItem,
} from '../api'
import { errorMessage } from '../api/client'
import { buildDeriveTreeData } from './baselineDeriveNodes'

interface Props {
  open: boolean
  projectId: number
  detail: BaselineDeriveDetail | null
  onClose: () => void
  onAdopted: () => void
}

const REASON_LABEL: Record<string, string> = {
  empty_content: '空章节',
  no_structured_content: '无结构化内容',
}

export default function BaselineDeriveDrawer({
  open,
  projectId,
  detail,
  onClose,
  onAdopted,
}: Props) {
  const [existingModules, setExistingModules] = useState<BaselineModule[]>([])
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [names, setNames] = useState<Record<number, string>>({})
  const [reuseChoice, setReuseChoice] = useState<
    Record<number, number | undefined>
  >({})
  const [loading, setLoading] = useState(false)

  const pendingModules = useMemo<BaselineDeriveCandidate[]>(() => {
    if (!detail) return []
    return detail.candidates.filter(
      (item) => item.entity_type === 'module' && item.status === 'pending',
    )
  }, [detail])

  useEffect(() => {
    if (!open || !detail) return
    const ids = detail.candidates
      .filter((item) => item.entity_type === 'module' && item.status === 'pending')
      .map((item) => item.id)
    setSelected(new Set(ids))
    setNames(
      Object.fromEntries(
        detail.candidates
          .filter((item) => item.entity_type === 'module')
          .map((item) => [item.id, item.name]),
      ),
    )
    setReuseChoice({})

    listBaselineModules(projectId, { status: 'active', page_size: 200 })
      .then((page) => setExistingModules(page.items))
      .catch((error) => message.error(errorMessage(error)))
  }, [open, detail, projectId])

  const toggle = useCallback((candidateId: number, checked: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (checked) next.add(candidateId)
      else next.delete(candidateId)
      return next
    })
  }, [])

  const rename = useCallback((candidateId: number, name: string) => {
    setNames((prev) => ({ ...prev, [candidateId]: name }))
  }, [])

  const chooseReuse = useCallback(
    (candidateId: number, moduleId: number | undefined) => {
      setReuseChoice((prev) => ({ ...prev, [candidateId]: moduleId }))
    },
    [],
  )

  const adopt = useCallback(async () => {
    if (!detail) return
    const items: DeriveAdoptItem[] = pendingModules.map((candidate) => {
      if (!selected.has(candidate.id)) {
        return { candidate_id: candidate.id, action: 'skip' }
      }
      const target = reuseChoice[candidate.id]
      if (target) {
        return {
          candidate_id: candidate.id,
          action: 'reuse',
          existing_entity_id: target,
        }
      }
      return {
        candidate_id: candidate.id,
        action: 'create',
        name: (names[candidate.id] ?? candidate.name).trim(),
      }
    })
    if (!items.length) {
      message.info('没有待决策的候选')
      return
    }
    setLoading(true)
    try {
      const result = await adoptBaselineDerive(projectId, detail.id, items)
      message.success(`已采纳，新建 ${result.adopted_count} 个实体`)
      onAdopted()
      onClose()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [
    detail,
    names,
    onAdopted,
    onClose,
    pendingModules,
    projectId,
    reuseChoice,
    selected,
  ])

  const treeData = useMemo(
    () =>
      detail
        ? buildDeriveTreeData(detail.candidates, {
            selected,
            names,
            reuseChoice,
            existingModules,
            onToggle: toggle,
            onRename: rename,
            onReuseChoice: chooseReuse,
          })
        : [],
    [detail, existingModules, names, chooseReuse, rename, reuseChoice, selected, toggle],
  )

  const stats = detail?.stats
  const skipped = stats?.skipped_chapters ?? []

  return (
    <Drawer
      open={open}
      width={760}
      title="推导结果"
      onClose={onClose}
      data-testid="derive-drawer"
      footer={
        <Space style={{ float: 'right' }}>
          <Button data-testid="derive-close" onClick={onClose}>
            关闭
          </Button>
          <Button
            type="primary"
            loading={loading}
            disabled={!pendingModules.length}
            data-testid="derive-adopt"
            onClick={() => void adopt()}
          >
            采纳所选
          </Button>
        </Space>
      }
    >
      {!detail ? (
        <Empty />
      ) : (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          {detail.status === 'failed' && (
            <Alert
              type="error"
              showIcon
              message="推导失败"
              description={detail.error_message ?? detail.error_code ?? '未知错误'}
            />
          )}
          {detail.status === 'succeeded' && stats && (
            <Space wrap>
              <Tag color="blue">模块 {stats.module_count}</Tag>
              <Tag color="geekblue">功能 {stats.function_count}</Tag>
              <Tag>功能点 {stats.feature_point_count}</Tag>
              <Tag>已处理章节 {stats.processed_count}/{stats.chapter_count}</Tag>
              {skipped.length > 0 && (
                <Tag color="orange">
                  跳过 {skipped.length} 章：
                  {Array.from(
                    new Set(skipped.map((item) => REASON_LABEL[item.reason] ?? item.reason)),
                  ).join('、')}
                </Tag>
              )}
            </Space>
          )}
          {pendingModules.length === 0 ? (
            <Empty description="没有待决策的候选" />
          ) : (
            <>
              <Space>
                <Button
                  size="small"
                  data-testid="derive-select-all"
                  onClick={() => setSelected(new Set(pendingModules.map((item) => item.id)))}
                >
                  全选
                </Button>
                <Button
                  size="small"
                  data-testid="derive-select-none"
                  onClick={() => setSelected(new Set())}
                >
                  全不选
                </Button>
                <Typography.Text type="secondary">
                  未勾选的模块按「跳过」处理；子级功能 / 功能点跟随模块。
                </Typography.Text>
              </Space>
              <Tree
                key={detail.id}
                treeData={treeData}
                defaultExpandAll
                selectable={false}
                data-testid="derive-tree"
              />
            </>
          )}
        </Space>
      )}
    </Drawer>
  )
}
