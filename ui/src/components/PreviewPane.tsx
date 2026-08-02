import { BASIS_LABEL, EARNINGS_BASIS_LABEL } from '@/types/profile';
import { SLOT_ORDER } from '@/types/profile';
import { eurM, fyLabel, pct } from '@/lib/format';
import { useProfile } from '@/state/profileStore';

function Sparks({ series }: { series: { fy: number; value: number }[] }) {
  const max = Math.max(...series.map((d) => d.value));
  return (
    <div className="flex h-16 items-end gap-1" aria-hidden>
      {series.map((d) => (
        <div key={d.fy} className="flex flex-1 flex-col items-center gap-1">
          <div
            className="w-full bg-pine-600"
            style={{ height: `${(d.value / max) * 52}px` }}
            title={`${fyLabel(d.fy)} €${eurM(d.value)}m`}
          />
          <span className="font-mono text-[8px] text-ink-3">{String(d.fy).slice(2)}</span>
        </div>
      ))}
    </div>
  );
}

/** Live preview of the four-box slide. Headline recomputes from the chosen basis. */
export function PreviewPane() {
  const { assignment, blockById, revenueBasis, earningsBasis, earningsBlock, footnotes } = useProfile();

  const fin = blockById(assignment.top_right);
  const series = fin?.series;
  const last = series?.at(-1);
  const prev = series?.at(-2);
  const growth = last && prev ? last.value / prev.value - 1 : null;

  return (
    <section className="border border-rule bg-paper-raised">
      <div className="border-b border-rule-hair px-4 py-3">
        <p className="label-caps mb-1">Live preview</p>
        <h3 className="text-base font-semibold leading-snug text-pine">
          {series && last && growth !== null ? (
            <>
              At a glance: 107-year-old shirt &amp; blouse specialist,{' '}
              {revenueBasis === 'umsatzerloese' ? 'revenue' : BASIS_LABEL[revenueBasis]}{' '}
              {pct(growth)} to €{eurM(last.value)}m in {fyLabel(last.fy)}; {EARNINGS_BASIS_LABEL[earningsBasis]}
            </>
          ) : (
            'At a glance: no financial series assigned'
          )}
        </h3>
      </div>

      <div className="grid grid-cols-2 divide-x divide-y divide-rule-hair">
        {SLOT_ORDER.map((slot) => {
          const b = blockById(assignment[slot]);
          return (
            <div key={slot} className="min-h-[104px] p-3">
              <p className="label-caps mb-2">{b?.title ?? '—'}</p>
              {b?.series ? (
                <>
                  <p className="mb-1 font-mono text-micro text-ink-3">
                    Axis: {b.id === earningsBlock?.id ? EARNINGS_BASIS_LABEL[earningsBasis] : b.title} in €m
                  </p>
                  <Sparks series={b.series} />
                </>
              ) : (
                <div className="space-y-1.5" aria-hidden>
                  <div className="h-1 w-11/12 bg-rule-hair" />
                  <div className="h-1 w-9/12 bg-rule-hair" />
                  <div className="h-1 w-10/12 bg-rule-hair" />
                  <div className="h-1 w-6/12 bg-rule-hair" />
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="border-t border-rule-hair px-4 py-3">
        <p className="label-caps mb-1.5">Footnotes · auto-generated</p>
        <ol className="space-y-1">
          {footnotes.length === 0 && <li className="text-xs text-ink-3">None</li>}
          {footnotes.map((f, i) => (
            <li key={f} className="text-xs leading-snug text-ink-2">
              <span className="font-mono text-micro text-ink-3">{i + 1}.</span> {f}
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
