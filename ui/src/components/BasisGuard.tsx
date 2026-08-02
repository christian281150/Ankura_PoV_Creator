import type { EarningsBasis, PresentationBasis } from '@/types/profile';
import { BASIS_LABEL, EARNINGS_BASIS_LABEL } from '@/types/profile';
import { cn } from '@/lib/format';
import { useProfile } from '@/state/profileStore';

const REVENUE_OPTIONS: PresentationBasis[] = ['umsatzerloese', 'gesamtleistung'];
const EARNINGS_OPTIONS: EarningsBasis[] = ['reported', 'adjusted'];

/** Makes the V1 and V11 presentation-basis rules visible and auditable. */
export function BasisGuard() {
  const { revenueBasis, earningsBasis, adjustedEarningsAvailable, dispatch } = useProfile();
  const revenueViolating = revenueBasis !== 'umsatzerloese';

  return (
    <div className="space-y-3">
      <section
        className={cn(
          'border px-4 py-3',
          revenueViolating ? 'border-rust-600/50 bg-rust-100/60' : 'border-pine-600/40 bg-pine-100',
        )}
      >
        <p className={cn('label-caps', revenueViolating ? 'text-rust' : 'text-pine')}>Revenue basis</p>
        <div role="radiogroup" aria-label="Revenue series basis" className="mt-2 flex gap-2">
          {REVENUE_OPTIONS.map((basis) => (
            <label
              key={basis}
              className={cn(
                'flex cursor-pointer items-center gap-2 border px-2.5 py-1.5 text-sm',
                revenueBasis === basis ? 'border-ink bg-paper-raised font-medium text-ink' : 'border-rule bg-paper text-ink-2',
              )}
            >
              <input
                type="radio"
                name="revenue-basis"
                checked={revenueBasis === basis}
                onChange={() => dispatch({ type: 'setBasis', basis })}
                className="h-3 w-3 accent-pine-600"
              />
              <span className="font-mono text-xs">{BASIS_LABEL[basis]}</span>
            </label>
          ))}
        </div>
        <p className="mt-2 text-xs text-ink-2">
          {revenueViolating ? (
            <><span className="font-semibold text-rust">V1 fails.</span> A series on {BASIS_LABEL[revenueBasis]} cannot be labelled &ldquo;Revenue&rdquo;. Axis relabelled; export blocked.</>
          ) : (
            <>Axis reads &ldquo;Revenue&rdquo;. Umsatzerlöse per §275 Nr. 1, excluding Bestandsveränderung.</>
          )}
        </p>
      </section>

      <section className="border border-pine-600/40 bg-pine-100 px-4 py-3">
        <p className="label-caps text-pine">Earnings basis</p>
        <div role="radiogroup" aria-label="EBITDA series basis" className="mt-2 flex gap-2">
          {EARNINGS_OPTIONS.map((basis) => {
            const unavailable = basis === 'adjusted' && !adjustedEarningsAvailable;
            return (
              <label
                key={basis}
                className={cn(
                  'flex items-center gap-2 border px-2.5 py-1.5 text-sm',
                  unavailable ? 'cursor-not-allowed border-rule-hair bg-paper-sunk text-ink-3' : 'cursor-pointer',
                  !unavailable && earningsBasis === basis ? 'border-ink bg-paper-raised font-medium text-ink' : !unavailable && 'border-rule bg-paper text-ink-2',
                )}
              >
                <input
                  type="radio"
                  name="earnings-basis"
                  checked={earningsBasis === basis}
                  disabled={unavailable}
                  onChange={() => dispatch({ type: 'setEarningsBasis', basis })}
                  className="h-3 w-3 accent-pine-600 disabled:opacity-30"
                />
                <span className="font-mono text-xs">{EARNINGS_BASIS_LABEL[basis]}</span>
              </label>
            );
          })}
        </div>
        {!adjustedEarningsAvailable ? (
          <p className="mt-2 text-xs text-amber">⊘ no management-stated adjustments available</p>
        ) : (
          <p className="mt-2 text-xs text-ink-2">Adjusted EBITDA carries a mandatory reported-to-adjusted reconciliation footnote.</p>
        )}
      </section>
    </div>
  );
}
