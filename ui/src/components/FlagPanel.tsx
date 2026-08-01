import { useProfile } from '@/state/profileStore';

const SEVERITY_COPY: Record<string, string> = {
  blocking: 'Blocks export',
  note_required: 'Note required before export',
  advisory: 'Advisory',
};

/**
 * Notes written here become slide footnotes. That is the whole point: the
 * footnote is a by-product of resolving a flag, not a separate authoring step.
 */
export function FlagPanel() {
  const { openFlags, notes, dispatch } = useProfile();

  if (openFlags.length === 0) {
    return (
      <section className="border border-pine-600/40 bg-pine-100 px-4 py-3">
        <p className="label-caps text-pine">Validation</p>
        <p className="mt-1 text-sm text-pine">
          All flags on assigned blocks resolved. Export unblocked.
        </p>
      </section>
    );
  }

  return (
    <section className="border border-rust-600/40 bg-rust-100/60">
      <header className="flex items-center justify-between border-b border-rust-600/30 px-4 py-2">
        <p className="label-caps text-rust">Validation — {openFlags.length} open</p>
        <p className="font-mono text-micro text-rust">notes become footnotes</p>
      </header>

      <ul className="divide-y divide-rust-600/20">
        {openFlags.map(({ block, rule, severity, message }) => {
          const key = `${block.id}:${rule}`;
          return (
            <li key={key} className="px-4 py-3">
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-xs font-semibold text-rust">{rule}</span>
                <span className="font-mono text-micro uppercase tracking-[0.1em] text-ink-3">
                  {SEVERITY_COPY[severity]}
                </span>
              </div>
              <p className="mt-1 text-sm text-ink">{message}</p>
              <p className="mt-0.5 font-mono text-micro text-ink-3">{block.id}</p>
              <label className="mt-2 block">
                <span className="sr-only">Note explaining {rule} on {block.title}</span>
                <input
                  type="text"
                  value={notes[key] ?? ''}
                  onChange={(e) =>
                    dispatch({ type: 'note', blockId: block.id, rule, note: e.target.value })
                  }
                  placeholder="Explain the movement — this becomes footnote text"
                  className="w-full border border-rule bg-paper-raised px-2 py-1.5 text-sm text-ink placeholder:text-ink-4"
                />
              </label>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
