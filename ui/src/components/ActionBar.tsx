import { cn } from '@/lib/format';
import { useProfile } from '@/state/profileStore';

export function ActionBar() {
  const { dispatch, exportBlocked, openFlags, layoutLocked } = useProfile();

  return (
    <div className="sticky bottom-0 flex items-center gap-2 border-t border-rule bg-paper-raised px-8 py-3">
      <button
        type="button"
        onClick={() => dispatch({ type: 'resetCanonical' })}
        disabled={layoutLocked}
        className="border border-rule px-3 py-1.5 text-sm text-ink hover:bg-paper-sunk disabled:opacity-50"
      >
        Reset to canonical
      </button>
      <button
        type="button"
        onClick={() => dispatch({ type: 'toggleLock' })}
        aria-pressed={layoutLocked}
        className={cn(
          'border px-3 py-1.5 text-sm',
          layoutLocked ? 'border-pine-600 bg-pine-100 text-pine' : 'border-rule text-ink hover:bg-paper-sunk',
        )}
      >
        {layoutLocked ? 'Layout locked' : 'Lock layout'}
      </button>
      <button
        type="button"
        className="border border-rule px-3 py-1.5 text-sm text-ink hover:bg-paper-sunk"
      >
        Export JSON
      </button>

      <div className="flex-1" />

      {exportBlocked && (
        <p className="font-mono text-micro uppercase tracking-[0.1em] text-rust">
          {openFlags.length > 0
            ? `${openFlags.length} flag${openFlags.length === 1 ? '' : 's'} unresolved`
            : 'presentation basis fails V1'}
        </p>
      )}
      <button
        type="button"
        disabled={exportBlocked}
        title={exportBlocked ? 'Resolve all flags before exporting' : undefined}
        className={cn(
          'px-4 py-1.5 text-sm font-medium text-white',
          exportBlocked ? 'cursor-not-allowed bg-ink-4' : 'bg-pine hover:bg-pine-600',
        )}
      >
        Export .pptx
      </button>
    </div>
  );
}
