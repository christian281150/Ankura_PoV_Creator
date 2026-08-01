import type { ContentBlock, SlotId } from '@/types/profile';

const CONFIDENCE_WEIGHT = { high: 1, medium: 0.7, low: 0.4 } as const;

/** Dropdown ordering is coverage × confidence, descending (AGENTS.md §P7). */
export function rank(block: ContentBlock): number {
  return block.coverage * CONFIDENCE_WEIGHT[block.confidence];
}

export function eligibleFor(blocks: ContentBlock[], slot: SlotId): ContentBlock[] {
  return blocks
    .filter((b) => b.eligibleSlots.includes(slot))
    .sort((a, b) => {
      // Unavailable blocks always sort last but are never hidden.
      if (!!a.unavailableReason !== !!b.unavailableReason) return a.unavailableReason ? 1 : -1;
      return rank(b) - rank(a);
    });
}

export function isSelectable(block: ContentBlock): boolean {
  if (block.unavailableReason) return false;
  return !block.flags.some((f) => f.severity === 'blocking' && !f.note);
}

export function unresolvedFlags(blocks: ContentBlock[]): number {
  return blocks.reduce(
    (n, b) => n + b.flags.filter((f) => f.severity !== 'advisory' && !f.note).length,
    0,
  );
}


