/** SuperAlpha: preview a diversified basket of your own submitted Alphas, then submit
 * BRAIN's own real filter/scoring expressions over them as one SUPER simulation.
 *
 * The preview below and the actual submission are deliberately decoupled: BRAIN evaluates
 * `selection` itself, server-side, over the whole matching pool at submission time --
 * the local diversity-selected list here is an estimate of what a preset will roughly
 * capture, not a fixed list of IDs sent to BRAIN.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'
import { errorMessage } from '@/api/http'
import { DASH, fmt } from '@/lib/format'
import {
  Button,
  Empty,
  ErrorNotice,
  Fieldset,
  Input,
  Metric,
  Notice,
  Page,
  PageHeader,
  Panel,
  Segmented,
  Skeleton,
} from '@/ui/kit'
import { type Column, DataTable } from '@/ui/table'
import { COMBO_PRESETS, SELECTION_PRESETS, type SuperAlphaRequest, superalpha } from './api'

type Candidate = SuperAlphaRequest extends never ? never : Record<string, unknown>

const fixed = (v: number | null | undefined, places = 2) =>
  v == null || !Number.isFinite(v as number) ? DASH : (v as number).toFixed(places)

export function SuperAlphaScreen() {
  const client = useQueryClient()
  const [region, setRegion] = useState('GBR')
  const [delay, setDelay] = useState(1)
  const [universe, setUniverse] = useState('TOP700')
  const [neutralization, setNeutralization] = useState('SUBINDUSTRY')
  const [selectionName, setSelectionName] = useState<string>(SELECTION_PRESETS[0].value)
  const [comboName, setComboName] = useState<string>(COMBO_PRESETS[0].value)

  const body: SuperAlphaRequest = {
    region,
    delay,
    universe,
    neutralization,
    decay: 0,
    truncation: 0.08,
    selectionName,
    comboName,
  }

  const preview = useQuery({
    queryKey: ['superalpha', 'preview', body],
    queryFn: () => superalpha.preview(body),
    enabled: region.length > 0 && universe.length > 0,
    retry: false,
  })

  const submit = useMutation({
    mutationFn: () => superalpha.addTask(body),
    onSuccess: (data) => {
      void client.invalidateQueries({ queryKey: ['lab-tasks'] })
      toast.success(`SuperAlpha task added: ${data.name}`)
    },
    onError: (e) => toast.error('Could not submit SuperAlpha', { description: errorMessage(e) }),
  })

  const data = preview.data
  const columns: Column<Record<string, unknown>>[] = [
    {
      key: 'alphaId',
      header: 'Alpha',
      width: 'minmax(100px,1fr)',
      cell: (r) => <span className="font-mono">{String(r['alphaId'])}</span>,
    },
    {
      key: 'sharpe',
      header: 'Sharpe',
      width: '90px',
      align: 'right',
      cell: (r) => <span className="tabular-nums">{fixed(r['sharpe'] as number)}</span>,
    },
    {
      key: 'fitness',
      header: 'Fitness',
      width: '90px',
      align: 'right',
      cell: (r) => <span className="tabular-nums">{fixed(r['fitness'] as number)}</span>,
    },
    {
      key: 'turnover',
      header: 'Turnover',
      width: '90px',
      align: 'right',
      cell: (r) => <span className="tabular-nums">{fixed(r['turnover'] as number)}</span>,
    },
    {
      key: 'family',
      header: 'Structural Family',
      width: 'minmax(160px,2fr)',
      cell: (r) => (
        <span className="font-mono text-caption" title={String(r['family'])}>
          {String(r['family']).slice(0, 60)}
        </span>
      ),
    },
    {
      key: 'maxCorrToSelected',
      header: 'Max Corr',
      width: '90px',
      align: 'right',
      cell: (r) => (
        <span className="tabular-nums">{fixed(r['maxCorrToSelected'] as number, 3)}</span>
      ),
    },
  ]

  return (
    <Page>
      <PageHeader
        title="SuperAlpha"
        description="Combine your own submitted Alphas into one BRAIN-scored SUPER simulation."
      />

      <Panel title="Market">
        <div className="flex flex-wrap items-start gap-x-8 gap-y-4">
          <Fieldset legend="Region">
            <Input value={region} onChange={(e) => setRegion(e.target.value.toUpperCase())} />
          </Fieldset>
          <Fieldset legend="Delay">
            <Segmented
              label="Delay"
              items={[0, 1].map((v) => ({ value: v, label: v }))}
              value={delay}
              onChange={setDelay}
            />
          </Fieldset>
          <Fieldset legend="Universe">
            <Input value={universe} onChange={(e) => setUniverse(e.target.value.toUpperCase())} />
          </Fieldset>
          <Fieldset legend="Neutralization">
            <Input
              value={neutralization}
              onChange={(e) => setNeutralization(e.target.value.toUpperCase())}
            />
          </Fieldset>
        </div>
      </Panel>

      <Panel title="Selection & Combo">
        <div className="flex flex-wrap items-start gap-x-8 gap-y-4">
          <Fieldset legend="Selection preset">
            <Segmented
              label="Selection preset"
              items={SELECTION_PRESETS.map((p) => ({ value: p.value, label: p.label }))}
              value={selectionName}
              onChange={setSelectionName}
            />
          </Fieldset>
          <Fieldset legend="Combo preset">
            <Segmented
              label="Combo preset"
              items={COMBO_PRESETS.map((p) => ({ value: p.value, label: p.label }))}
              value={comboName}
              onChange={setComboName}
            />
          </Fieldset>
        </div>
        {data && (
          <div className="mt-3 flex flex-col gap-1 text-body-compact text-ink-subtle">
            <div>
              <span className="font-medium text-ink">Selection: </span>
              <span className="font-mono">{data.selection}</span>
            </div>
            <div>
              <span className="font-medium text-ink">Combo: </span>
              <span className="font-mono break-all">{data.combo}</span>
            </div>
          </div>
        )}
      </Panel>

      {preview.isError && <ErrorNotice error={preview.error} title="Could not preview" />}
      {data?.problems.map((p) => (
        <Notice key={p} tone="error" title={p} />
      ))}

      {preview.isPending ? (
        <Skeleton className="h-64" />
      ) : data && data.selectedCount > 0 ? (
        <Panel
          title="Diversity Preview"
          description="An estimate of what this preset would capture -- BRAIN evaluates the real expression itself at submission time, over the whole matching pool, not this exact list."
        >
          <div className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Metric boxed label="Eligible Alphas" value={fmt.int(data.eligibleCount)} />
            <Metric boxed label="Structural Families" value={fmt.int(data.familyCount)} />
            <Metric
              boxed
              label="Redundancy Removed"
              value={fmt.int(data.structuralRedundancyRemoved)}
            />
            <Metric boxed label="Median Pair Corr" value={fixed(data.medianPairCorr, 3)} />
          </div>
          <DataTable
            label="Diversity preview"
            rows={data.selected as Candidate[]}
            columns={columns}
            rowKey={(r) => String(r['alphaId'])}
          />
          <div className="mt-3">
            <Button onClick={() => submit.mutate()} disabled={submit.isPending}>
              {submit.isPending ? 'Submitting...' : 'Submit SuperAlpha'}
            </Button>
          </div>
        </Panel>
      ) : data ? (
        <Panel>
          <Empty title="No diversified candidates">
            Fewer than two candidates matched this preset in this market.
          </Empty>
        </Panel>
      ) : null}
    </Page>
  )
}
