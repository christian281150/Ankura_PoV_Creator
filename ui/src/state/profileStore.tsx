import { createContext, useContext, useMemo, useReducer, type ReactNode } from 'react';
import type { ContentBlock, PresentationBasis, ProfileFixture, RuleId, SlotId } from '@/types/profile';
import { SLOT_ORDER } from '@/types/profile';

/**
 * Single reducer for the whole slot-assignment screen. Deliberately no external
 * state library: the state is one object, transitions are few and auditable,
 * and an internal tool does not need the bundle cost.
 */

interface State {
  fixture: ProfileFixture;
  assignment: Record<SlotId, string | null>;
  /** Blocks whose non-advisory flags must be resolved before export. */
  flaggedBlockIds: string[];
  /** Written notes, keyed `${blockId}:${rule}`. Presence resolves a flag. */
  notes: Record<string, string>;
  /** In-progress flag notes, shown in the preview but not yet resolving a flag. */
  draftNotes: Record<string, string>;
  revenueBasis: PresentationBasis;
  layoutLocked: boolean;
}

type Action =
  | { type: 'assign'; slot: SlotId; blockId: string }
  | { type: 'draftNote'; blockId: string; rule: RuleId; note: string }
  | { type: 'note'; blockId: string; rule: RuleId; note: string }
  | { type: 'setBasis'; basis: PresentationBasis }
  | { type: 'resetCanonical' }
  | { type: 'toggleLock' };

function reducer(state: State, action: Action): State {
  if (state.layoutLocked && (action.type === 'assign' || action.type === 'resetCanonical')) {
    return state;
  }
  switch (action.type) {
    case 'assign':
      if (Object.entries(state.assignment).some(([slot, id]) => slot !== action.slot && id === action.blockId)) {
        return state;
      }
      return {
        ...state,
        assignment: { ...state.assignment, [action.slot]: action.blockId },
        flaggedBlockIds: state.fixture.blocks.some(
          (block) => block.id === action.blockId && block.flags.some((flag) => flag.severity !== 'advisory'),
        ) && !state.flaggedBlockIds.includes(action.blockId)
          ? [...state.flaggedBlockIds, action.blockId]
          : state.flaggedBlockIds,
      };
    case 'note': {
      const key = `${action.blockId}:${action.rule}`;
      const notes = { ...state.notes };
      const draftNotes = { ...state.draftNotes };
      if (action.note.trim()) notes[key] = action.note.trim();
      else delete notes[key];
      delete draftNotes[key];
      return { ...state, notes, draftNotes };
    }
    case 'draftNote': {
      const key = `${action.blockId}:${action.rule}`;
      const draftNotes = { ...state.draftNotes };
      if (action.note) draftNotes[key] = action.note;
      else delete draftNotes[key];
      return { ...state, draftNotes };
    }
    case 'setBasis':
      return { ...state, revenueBasis: action.basis };
    case 'resetCanonical':
      return { ...state, assignment: { ...state.fixture.canonicalLayout } };
    case 'toggleLock':
      return { ...state, layoutLocked: !state.layoutLocked };
  }
}

interface Store extends State {
  dispatch: React.Dispatch<Action>;
  blockById: (id: string | null) => ContentBlock | undefined;
  /** Flags still lacking a note, across the four assigned blocks only. */
  openFlags: { block: ContentBlock; rule: RuleId; severity: string; message: string }[];
  isCanonical: (slot: SlotId) => boolean;
  allSlotsAssigned: boolean;
  hasFinancialSeries: boolean;
  exportBlocked: boolean;
  footnotes: string[];
}

const Ctx = createContext<Store | null>(null);

export function ProfileProvider({ fixture, children }: { fixture: ProfileFixture; children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, {
    fixture,
    assignment: { ...fixture.canonicalLayout },
    flaggedBlockIds: fixture.blocks
      .filter((block) => Object.values(fixture.canonicalLayout).includes(block.id))
      .filter((block) => block.flags.some((flag) => flag.severity !== 'advisory'))
      .map((block) => block.id),
    notes: {},
    draftNotes: {},
    revenueBasis: 'umsatzerloese',
    layoutLocked: false,
  });

  const value = useMemo<Store>(() => {
    const blockById = (id: string | null) =>
      id ? state.fixture.blocks.find((b) => b.id === id) : undefined;

    const assigned = SLOT_ORDER.map((s) => blockById(state.assignment[s])).filter(
      (b): b is ContentBlock => Boolean(b),
    );

    const flagBlocks = state.flaggedBlockIds
      .map((id) => blockById(id))
      .filter((block): block is ContentBlock => Boolean(block));

    const openFlags = flagBlocks.flatMap((block) =>
      block.flags
        .filter((f) => f.severity !== 'advisory' && !state.notes[`${block.id}:${f.rule}`])
        .map((f) => ({ block, rule: f.rule, severity: f.severity, message: f.message })),
    );

    // V1: a series labelled "Revenue" must be stated on Umsatzerlöse.
    const basisViolation = state.revenueBasis !== 'umsatzerloese';
    const allSlotsAssigned = SLOT_ORDER.every((slot) => state.assignment[slot] !== null);
    const hasFinancialSeries = assigned.some((block) => Boolean(block.series?.length));

    const footnotes = [
      ...assigned.flatMap((b) => b.footnotesAuto),
      ...Object.entries(state.notes).map(([, note]) => note),
      ...Object.entries(state.draftNotes).map(([, note]) => note),
    ];

    return {
      ...state,
      dispatch,
      blockById,
      openFlags,
      isCanonical: (slot: SlotId) => state.assignment[slot] === state.fixture.canonicalLayout[slot],
      allSlotsAssigned,
      hasFinancialSeries,
      exportBlocked: openFlags.length > 0 || basisViolation || !allSlotsAssigned || !hasFinancialSeries,
      footnotes,
    };
  }, [state]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useProfile(): Store {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useProfile must be used within ProfileProvider');
  return ctx;
}
