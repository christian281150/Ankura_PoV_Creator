import type { PresentationBasis } from '@/types/profile';
import { BASIS_LABEL } from '@/types/profile';
import { cn } from '@/lib/format';
import { useProfile } from '@/state/profileStore';

const OPTIONS: PresentationBasis[] = ['umsatzerloese', 'gesamtleistung'];

/**
 * Rule V1 made visible. The published POV charted Gesamtleistung under a
 * "Revenue in €m" axis for nine consecutive years. This control makes the
 * basis an explicit, labelled choice and relabels the axis to match.
 */
export function BasisGuard() {
  const { revenueBasis, dispatch } = useProfile();
  const violating = revenueBasis !== 'umsatzerloese';

  return (
    <section
      className={cn(
        'border px-4 py-3',
        violating ? 'border-rust-600/50 bg-rust-100/60' : 'border-pine-600/40 bg-pine-100',
      )}
    >
      <p className={cn('label-caps', violating ? 'text-rust' : 'text-pine')}>Presentation basis</p>

      <div role="radiogroup" aria-label="Revenue series basis" className="mt-2 flex gap-2">
        {OPTIONS.map((b) => (
          <label
            key={b}
            className={cn(
              'flex cursor-pointer items-center gap-2 border px-2.5 py-1.5 text-sm',
              revenueBasis === b
                ? 'border-ink bg-paper-raised font-medium text-ink'
                : 'border-rule bg-paper text-ink-2',
            )}
          >
            <input
              type="radio"
              name="basis"
              checked={revenueBasis === b}
              onChange={() => dispatch({ type: 'setBasis', basis: b })}
              className="h-3 w-3 accent-pine-600"
            />
            <span className="font-mono text-xs">{BASIS_LABEL[b]}</span>
          </label>
        ))}
      </div>

      <p className="mt-2 text-xs text-ink-2">
        {violating ? (
          <>
            <span className="font-semibold text-rust">V1 fails.</span> A series on{' '}
            {BASIS_LABEL[revenueBasis]} cannot be labelled &ldquo;Revenue&rdquo;. Axis relabelled;
            export blocked.
          </>
        ) : (
          <>Axis reads &ldquo;Revenue&rdquo;. Umsatzerlöse per §275 Nr. 1, excluding Bestandsveränderung.</>
        )}
      </p>
    </section>
  );
}
