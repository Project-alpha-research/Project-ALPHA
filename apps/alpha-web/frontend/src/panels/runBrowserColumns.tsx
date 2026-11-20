// The Run Browser's columns: what each stored run shows. A rule-test run shows its evidence word in
// "Reading"; an old run shows its letter as "graded X under the old rules", muted. There is no result column.

import type { ColumnDef } from '@tanstack/react-table'

import type { RunListItem } from '../api/types'
import { fmtTime, shortId } from '../util/format'
import { openRunDetail } from './actions'
import { runWord } from './readingModel'
import { researchGateWatermark } from './researchGateModel'

export function runBrowserColumns(): ColumnDef<RunListItem, unknown>[] {
  return [
    {
      header: 'Run',
      accessorKey: 'run_id',
      cell: (c) => shortId(c.row.original.run_id),
      meta: { className: 'id' },
    },
    {
      header: 'Kind',
      accessorKey: 'kind',
      cell: (c) => <span className="chip kind">{c.row.original.kind}</span>,
    },
    {
      header: 'Command',
      accessorKey: 'command',
      // a rule test (`alpha test`) reads as what it is, not as the engine command it ran
      cell: (c) => (c.row.original.rule_test_labels ? 'rule test' : c.row.original.command ?? '—'),
      meta: { className: 'mono' },
    },
    {
      header: 'Label',
      accessorKey: 'label',
      cell: (c) => {
        // spec §15 / ADR-0026: relay the permanent research-gate override marker on the row
        const watermark = researchGateWatermark(c.row.original)
        return (
          <>
            {c.row.original.label ?? '—'}
            {watermark ? (
              <span
                className="chip warn rg-watermark"
                title="Launched under an owner research-gate override (spec §15, ADR-0026)"
              >
                {watermark}
              </span>
            ) : null}
          </>
        )
      },
      meta: { className: 'mono' },
    },
    {
      header: 'Reading',
      accessorKey: 'evidence',
      cell: (c) => {
        const word = runWord(c.row.original.evidence, c.row.original.verdict)
        return word ? <span className={word.old ? 'muted' : undefined}>{word.text}</span> : <span className="muted">—</span>
      },
    },
    {
      header: 'Updated',
      accessorKey: 'mtime',
      cell: (c) => fmtTime(c.row.original.mtime),
      meta: { className: 'num' },
    },
    {
      id: 'open',
      header: '',
      cell: (c) => (
        <button
          className="btn"
          onClick={(e) => {
            e.stopPropagation()
            openRunDetail(c.row.original.run_id)
          }}
        >
          open ⏎
        </button>
      ),
      enableSorting: false,
    },
  ]
}
