import { cn } from '@/lib/format';

/** Coverage meter. Amber below 0.7 — the threshold where a box needs a caveat. */
export function Meter({ value, label }: { value: number; label: string }) {
  const low = value < 0.7;
  return (
    <div className="flex items-center gap-3">
      <span className="w-32 shrink-0 font-mono text-micro uppercase tracking-[0.1em] text-ink-3">
        {label}
      </span>
      <span
        className="h-[6px] flex-1 bg-rule-hair"
        role="meter"
        aria-valuenow={Math.round(value * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${label} coverage`}
      >
        <span
          className={cn('block h-full', low ? 'bg-amber-600' : 'bg-pine-600')}
          style={{ width: `${value * 100}%` }}
        />
      </span>
      <span className="w-8 shrink-0 text-right font-mono text-micro text-ink-3">
        {value.toFixed(2).replace(/^0/, '')}
      </span>
    </div>
  );
}
