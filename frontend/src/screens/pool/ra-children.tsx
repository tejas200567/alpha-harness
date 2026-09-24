/**
 * A region-agnostic parent has no PnL, checks or correlations of its own: BRAIN judges it by
 * its children, one per region. This lists them, and on request BRAIN's verdict on them.
 */

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useState } from 'react'
import { errorMessage, http } from '@/api/http'
import { fmt, isNum } from '@/lib/format'
import { Badge, Button, checkTone, Notice } from '@/ui/kit'

type RaChild = {
  alphaId: string
  region: string | null
  ratio: number | null
  failedChecks: string[]
  pyramids: string[]
}

type RaChildrenResponse = {
  parent: boolean
  children: string[]
  checked: boolean
  score: number | null
  verdict: { result?: string | null; value?: number | null; limit?: number | null } | null
  details: RaChild[]
}

const read = (alphaId: string, check: boolean) =>
  http.get<RaChildrenResponse>(`/api/alphas/${alphaId}/ra-children${check ? '?check=true' : ''}`)

export function RaChildren({ alphaId }: { alphaId: string }) {
  const [check, setCheck] = useState(false)
  const q = useQuery({
    queryKey: ['alpha', 'ra-children', alphaId, check],
    queryFn: () => read(alphaId, check),
    placeholderData: (previous) => previous,
    retry: false,
    staleTime: 60_000,
  })

  if (q.isError) {
    return (
      <Notice tone="warn" title="Region-agnostic children">
        {errorMessage(q.error)}
      </Notice>
    )
  }
  const d = q.data
  if (!d?.parent) return null

  const rows: RaChild[] = d.checked
    ? d.details
    : d.children.map((id) => ({
        alphaId: id,
        region: null,
        ratio: null,
        failedChecks: [],
        pyramids: [],
      }))

  return (
    <section className="flex flex-col gap-2 border-t border-hairline pt-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-col">
          <h3 className="text-title">Region-Agnostic Children</h3>
          <p className="text-body-compact text-ink-subtle">
            An RA parent has no PnL or correlations of its own: open a child for those. BRAIN
            submits the parent when two or more children pass.
          </p>
        </div>
        <Button
          size="sm"
          loading={q.isFetching}
          disabled={d.checked}
          onClick={() => setCheck(true)}
        >
          Check Children on BRAIN
        </Button>
      </div>
      {d.checked && d.verdict && (
        <div className="flex flex-wrap items-center gap-2 text-body">
          <Badge
            tone={checkTone((d.verdict.result ?? 'PENDING') as Parameters<typeof checkTone>[0])}
          >
            {d.verdict.result ?? 'PENDING'}
          </Badge>
          <span>MIN_SUBMITTABLE_CHILDREN</span>
          {isNum(d.verdict.value) && (
            <span className="num text-ink-subtle">
              {fmt.int(d.verdict.value)} / {isNum(d.verdict.limit) ? fmt.int(d.verdict.limit) : '—'}
            </span>
          )}
          {isNum(d.score) && (
            <span className="num text-ink-subtle">score {fmt.ratio(d.score)}</span>
          )}
        </div>
      )}
      <ul className="flex flex-col">
        {rows.map((c) => (
          <li
            key={c.alphaId}
            className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-hairline py-1.5 text-body"
          >
            <Link
              to="/alpha/$alphaId"
              params={{ alphaId: c.alphaId }}
              className="num text-link hover:underline"
            >
              {c.alphaId}
            </Link>
            {c.region && <span className="text-ink-muted">{c.region}</span>}
            {isNum(c.ratio) && (
              <span className="num text-ink-subtle">ratio {fmt.ratio(c.ratio)}</span>
            )}
            {c.failedChecks.length > 0 && (
              <span className="text-body-compact text-pnl-negative">
                {c.failedChecks.join(', ')}
              </span>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
