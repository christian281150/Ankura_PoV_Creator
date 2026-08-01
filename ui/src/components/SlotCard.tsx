import { useId, useState } from 'react';
import type { ContentBlock, SlotId } from '@/types/profile';
import { SLOT_LABEL } from '@/types/profile';
import { cn } from '@/lib/format';
import { eligibleFor, isSelectable, rank } from '@/lib/scoring';
import { useProfile } from '@/state/profileStore';
import { Badge } from '@/components/ui/Badge';

const GUTTER = { high: 'gutter-high', medium: 'gutter-medium', low: 'gutter-low' } as const;

function BlockOption({
  block,
  selected,
  onSelect,
  name,
}: {
  block: ContentBlock;
  selected: boolean;
  onSelect: () => void;
  name: string;
}) {
  const selectable = isSelectable(block);
  const blockingFlag = block.flags.find((f) => f.severity === 'blocking');

  return (
    <label
      className={cn(
        'flex cursor-pointer items-start gap-2.5 border px-2.5 py-2 transition-colors',
        selected
          ? 'border-pine-600 bg-pine-100'
          : selectable
            ? 'border-rule-hair bg-paper-raised hover:border-rule'
            : 'cursor-not-allowed border-rule-hair bg-paper-sunk',
        selectable && GUTTER[block.confidence],
      )}
    >
      <input
        type="radio"
        name={name}
        checked={selected}
        disabled={!selectable}
        onChange={onSelect}
        className="mt-1 h-3 w-3 shrink-0 accent-pine-600 disabled:opacity-30"
      />
      <span className="min-w-0 flex-1">
        <span
          className={cn(
            'block text-sm font-medium',
            selectable ? 'text-ink' : 'text-ink-3 line-through decoration-ink-4',
          )}
        >
          {block.title}
        </span>
        <span className="mt-0.5 block font-mono text-micro text-ink-3">
          {block.id} · {block.source}
        </span>

        {block.unavailableReason && (
          <span className="mt-1 block text-xs text-amber">⊘ {block.unavailableReason}</span>
        )}
        {!block.unavailableReason && blockingFlag && (
          <span className="mt-1 block text-xs text-rust">
            ⚠ {blockingFlag.rule} blocks selection — {blockingFlag.message}
          </span>
        )}
      </span>

      {!block.unavailableReason && (
        <span className="shrink-0 pt-0.5 text-right font-mono text-micro text-ink-3">
          {rank(block).toFixed(2).replace(/^0/, '')}
        </span>
      )}
    </label>
  );
}

export function SlotCard({ slot }: { slot: SlotId }) {
  const { fixture, assignment, dispatch, isCanonical, layoutLocked, notes } = useProfile();
  const [open, setOpen] = useState(false);
  const [showSources, setShowSources] = useState(false);
  const groupName = useId();

  const options = eligibleFor(fixture.blocks, slot);
  const current = fixture.blocks.find((b) => b.id === assignment[slot]);
  const canonical = isCanonical(slot);

  const openCount =
    current?.flags.filter((f) => f.severity !== 'advisory' && !notes[`${current.id}:${f.rule}`])
      .length ?? 0;

  return (
    <section
      className={cn(
        'flex flex-col border bg-paper-raised',
        canonical ? 'border-rule' : 'border-amber-600',
        current ? GUTTER[current.confidence] : 'gutter-none',
      )}
      aria-label={`${SLOT_LABEL[slot]} slot`}
    >
      <header
        className={cn(
          'flex items-center justify-between px-3 py-1.5',
          canonical ? 'bg-pine text-white' : 'bg-amber-600 text-white',
        )}
      >
        <h2 className="font-mono text-micro uppercase tracking-[0.14em]">{SLOT_LABEL[slot]}</h2>
        <span className="font-mono text-micro tracking-[0.08em] opacity-80">
          {canonical ? 'canonical' : 'non-standard'}
        </span>
      </header>

      <div className="flex-1 px-3 py-3">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          disabled={layoutLocked}
          className="flex w-full items-center justify-between border border-rule bg-paper px-2.5 py-2 text-left disabled:opacity-60"
        >
          <span className="min-w-0">
            <span className="block truncate text-sm font-medium text-ink">
              {current?.title ?? 'No block assigned'}
            </span>
            <span className="block font-mono text-micro text-ink-3">
              {current ? `${current.id} · coverage ${current.coverage.toFixed(2).replace(/^0/, '')}` : '—'}
            </span>
          </span>
          <span aria-hidden className="ml-2 shrink-0 font-mono text-xs text-ink-3">
            {open ? '▲' : '▼'}
          </span>
        </button>

        {open && (
          <div role="radiogroup" aria-label={`Blocks for ${SLOT_LABEL[slot]}`} className="mt-2 space-y-1.5">
            {options.map((b) => (
              <BlockOption
                key={b.id}
                block={b}
                name={groupName}
                selected={b.id === assignment[slot]}
                onSelect={() => {
                  dispatch({ type: 'assign', slot, blockId: b.id });
                  setOpen(false);
                }}
              />
            ))}
          </div>
        )}

        {!canonical && (
          <p className="mt-3 border border-amber-600/40 bg-amber-100 px-2.5 py-2 text-xs text-amber">
            Canonical for §267 {fixture.entity.sizeClass} is{' '}
            <span className="font-mono">{fixture.canonicalLayout[slot]}</span>. Deviation recorded in
            profile metadata.
          </p>
        )}
      </div>

      <footer className="border-t border-rule-hair px-3 py-2">
        <div className="flex items-center justify-between">
          <button
            type="button"
            onClick={() => setShowSources((v) => !v)}
            aria-expanded={showSources}
            disabled={!current || current.provenance.length === 0}
            className="label-caps hover:text-ink disabled:hover:text-ink-3"
          >
            {current?.provenance.length ?? 0} source
            {(current?.provenance.length ?? 0) === 1 ? '' : 's'}
            {current && current.provenance.length > 0 && (
              <span aria-hidden className="ml-1">{showSources ? '▲' : '▼'}</span>
            )}
          </button>
        {openCount > 0 ? (
          <Badge tone="rust">
            {openCount} note{openCount === 1 ? '' : 's'} required
          </Badge>
          ) : (
            <Badge tone="pine">clear</Badge>
          )}
        </div>

        {showSources && current && (
          <ul className="mt-2 space-y-1 border-t border-rule-hair pt-2">
            {current.provenance.map((p, i) => (
              <li key={`${p.doc}-${p.sheet}-${i}`} className="font-mono text-micro leading-relaxed text-ink-3">
                <span className="text-ink-2">{p.doc}</span>
                {' · '}
                {p.sheet}
                {' · row '}
                {p.row}
                {p.stdId && <span className="text-pine-600"> · {p.stdId}</span>}
                {p.page === null && <span className="text-amber"> · page n/a</span>}
              </li>
            ))}
          </ul>
        )}
      </footer>
    </section>
  );
}
