/** What the labs share around a task: its draft, market and datasets, its preview, adding it. */

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { useEffect, useMemo } from 'react'
import { toast } from 'sonner'
import { catalog } from '@/api/catalog'
import type { Scope } from '@/api/types'
import { DEFAULT_SCOPE, useScope } from '@/lib/scope'
import { useDebounced } from '@/lib/use-debounced'
import { type PickFrom, useDatasetPick } from '@/screens/data/dataset-pick'

export interface LabDraft {
  region: string
  delay: number
  universe: string
  datasetIds: string[]
  cores: number
  /** `null` until the user assigns them: a task always has simulations chosen on purpose. */
  simulations: number | null
  decay: number
  /** `null` until the user chooses: then the lab allows `vec_avg`. */
  vectorOperators: string[] | null
  /** Empty leaves the lab on its own four group neutralizations. */
  neutralizations: string[]
  visualization: boolean
}

export const LAB_DEFAULTS: LabDraft = {
  region: DEFAULT_SCOPE.region,
  delay: DEFAULT_SCOPE.delay,
  universe: DEFAULT_SCOPE.universe,
  datasetIds: [],
  cores: 4,
  simulations: null,
  decay: 0,
  vectorOperators: null,
  neutralizations: [],
  visualization: false,
}

export const MAX_SIMULATIONS = 100_000

/** A draft's market and datasets: dataset names, and the round trip to the Data Explorer to choose them. */
type LabMarket = Pick<LabDraft, 'region' | 'delay' | 'universe' | 'datasetIds'>

export function useLabMarket(
  draft: LabMarket,
  set: (change: Partial<LabMarket>) => void,
  from: PickFrom,
) {
  const navigate = useNavigate()
  const [, setDataScope] = useScope('data')
  const scope: Scope = {
    instrumentType: 'EQUITY',
    region: draft.region,
    delay: draft.delay,
    universe: draft.universe,
  }
  const chosen = draft.datasetIds.length > 0

  // Back from the Data Explorer with a finished pick for this lab.
  useEffect(() => {
    const pick = useDatasetPick.getState().take(from)
    if (pick)
      set({
        region: pick.scope.region,
        delay: pick.scope.delay,
        universe: pick.scope.universe,
        datasetIds: pick.ids,
      })
  }, [from, set])

  const datasets = useQuery({
    queryKey: ['catalog', 'datasets', scope, ''],
    queryFn: () => catalog.datasets(scope),
    enabled: chosen,
  })
  const names = useMemo(
    () => new Map((datasets.data ?? []).map((d) => [d.dataset_id, d.name ?? d.dataset_id])),
    [datasets.data],
  )

  const choose = () => {
    useDatasetPick.getState().start(scope, draft.datasetIds, from)
    setDataScope(scope)
    void navigate({ to: '/data' })
  }
  return { chosen, names, choose }
}

/**
 * A lab's free preview of `body`, asked once the form has been still for `wait` ms. `current`
 * is whether the plan answers the form as it is now rather than an earlier state of it.
 */
export function useLabPreview<Body, Plan>(
  lab: string,
  body: Body,
  preview: (body: Body) => Promise<Plan>,
  { enabled = true, wait = 300 }: { enabled?: boolean; wait?: number } = {},
) {
  const key = JSON.stringify(body)
  const settled = useDebounced(key, wait)
  const query = useQuery({
    queryKey: [lab, 'preview', settled],
    queryFn: () => preview(JSON.parse(settled) as Body),
    enabled: enabled && settled === key,
    placeholderData: keepPreviousData,
  })
  return { preview: query, current: settled === key && !query.isFetching }
}

/** Adds a task, then offers the way to it. */
export function useAddTask<Value = void>(
  add: (value: Value) => Promise<unknown>,
  done = 'Task Added',
) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: add,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['lab-tasks'] })
      void queryClient.invalidateQueries({ queryKey: ['today'] })
      toast.success(done, {
        action: { label: 'Open Tasks', onClick: () => void navigate({ to: '/tasks' }) },
      })
    },
  })
}

/** `vec_avg` until the user chooses vector operators. */
export function vectorOperatorsOf(draft: LabDraft, available: string[] | undefined): string[] {
  return draft.vectorOperators ?? (available?.includes('vec_avg') ? ['vec_avg'] : [])
}

/** The market and settings both labs send to preview a task. */
export function labBody(draft: LabDraft, vectorOperators: string[]) {
  return {
    region: draft.region,
    delay: draft.delay,
    universe: draft.universe,
    dataset_ids: draft.datasetIds,
    vector_operators: vectorOperators,
    neutralizations: draft.neutralizations,
    decay: draft.decay,
    cores: draft.cores,
    visualization: draft.visualization,
  }
}

export function simulationsValid(simulations: number | null, maxSimulations: number): boolean {
  return simulations !== null && simulations >= 1 && simulations <= maxSimulations
}
