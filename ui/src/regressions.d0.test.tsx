import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import App from '@/App';
import { seidensticker } from '@/data/seidensticker';
import { ActionBar } from '@/components/ActionBar';
import { SlotCard } from '@/components/SlotCard';
import { ProfileProvider, useProfile } from '@/state/profileStore';
import type { ContentBlock, ProfileFixture, SlotId } from '@/types/profile';

/**
 * Regression tests for AGENTS.md "Lane D - known bugs, fix before F1":
 *   D0.1 - a block must not be assignable to two slots at once
 *   D0.2 - deselecting a flagged block must not silently unblock export
 *   D0.3 - the sticky action bar must not overlap the last slot card at narrow widths
 *
 * These bugs were already addressed in commit 2a424c6 ("lane D: D0.1-D0.3 duplicate/
 * export/overlap fixes"). These tests lock the fix in: each was verified to fail
 * against a pre-2a424c6 checkout of the relevant file before being added here.
 */

async function renderApp() {
  const result = render(<App />);
  await screen.findByRole('button', { name: 'Export .pptx' });
  return result;
}

function makeBlock(id: string, title: string, eligibleSlots: SlotId[], overrides: Partial<ContentBlock> = {}): ContentBlock {
  return {
    id,
    title,
    kind: 'bullets',
    eligibleSlots,
    coverage: 1,
    confidence: 'high',
    source: 'test fixture',
    presentationBasis: 'n/a',
    unavailableReason: null,
    flags: [],
    footnotesAuto: [],
    provenance: [],
    ...overrides,
  };
}

const financialGateFixture: ProfileFixture = {
  entity: seidensticker.entity,
  canonicalLayout: {
    top_left: 'block.a',
    top_right: 'block.fin',
    bottom_left: 'block.b',
    bottom_right: 'block.c',
  },
  coverage: [],
  blocks: [
    makeBlock('block.a', 'Slot A filler', ['top_left']),
    makeBlock('block.b', 'Slot B filler', ['bottom_left']),
    makeBlock('block.c', 'Slot C filler', ['bottom_right']),
    makeBlock('block.fin', 'Financial series block', ['top_right'], {
      presentationBasis: 'umsatzerloese',
      series: [
        { fy: 2023, value: 100_000_000 },
        { fy: 2024, value: 110_000_000 },
      ],
    }),
    makeBlock('block.nonfin', 'Non-financial alt block', ['top_right']),
  ],
};

describe('D0.1 - a block cannot occupy two slots at once', () => {
  it('UI: disables the block in every other eligible slot with "already in <slot>"', async () => {
    // Already covered at the DOM level in App.test.tsx; re-asserted here so the
    // whole D0.1-D0.3 regression suite is self-contained in one file.
    const user = userEvent.setup();
    await renderApp();

    await user.click(screen.getByRole('button', { name: /Revenue split by geography/ }));
    const revenueSeries = screen.getByRole('radio', { name: /Revenue & EBITDA series/i });
    expect(revenueSeries).toBeDisabled();
    expect(screen.getByText(/already in Top-right/)).toBeInTheDocument();
  });

  it('state: rejects a direct dispatch that would duplicate a block into a second slot, bypassing the disabled UI control', async () => {
    const user = userEvent.setup();

    function AssignmentProbe() {
      const { assignment, dispatch } = useProfile();
      return (
        <div>
          <button
            type="button"
            onClick={() => dispatch({ type: 'assign', slot: 'bottom_right', blockId: 'fin.revenue_ebitda_series' })}
          >
            force-duplicate-assign
          </button>
          <pre data-testid="assignment">{JSON.stringify(assignment)}</pre>
        </div>
      );
    }

    render(
      <ProfileProvider fixture={seidensticker}>
        <AssignmentProbe />
      </ProfileProvider>,
    );

    const before = screen.getByTestId('assignment').textContent;
    expect(before).toContain('"top_right":"fin.revenue_ebitda_series"');
    expect(before).toContain('"bottom_right":"geo.revenue_split"');

    // fin.revenue_ebitda_series is already held by top_right; a dispatch that tries
    // to also place it in bottom_right must be a no-op at the reducer level, not
    // merely blocked by a disabled radio input.
    await user.click(screen.getByRole('button', { name: 'force-duplicate-assign' }));

    expect(screen.getByTestId('assignment').textContent).toBe(before);
  });
});

describe('D0.2 - deselecting a flagged block must not silently unblock export', () => {
  it('keeps a block\'s open flags counted after it is swapped out of its slot', async () => {
    const user = userEvent.setup();
    await renderApp();

    // Canonical layout starts with 3 open flags: V5 + V6 on fin.revenue_ebitda_series
    // (top_right), V7 on geo.revenue_split (bottom_right).
    expect(screen.getByText('3 flags unresolved')).toBeInTheDocument();

    // Swap the flagged geo.revenue_split block out of bottom_right for an unflagged
    // alternative. A symptom-only fix would drop the flag count because the block
    // is no longer assigned anywhere; the real fix must not.
    await user.click(screen.getByRole('button', { name: /Revenue split by geography/ }));
    await user.click(screen.getByRole('radio', { name: /Footprint map/i }));

    expect(screen.getByText('3 flags unresolved')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Export .pptx' })).toBeDisabled();
  });

  it('requires at least one assigned block to carry a financial series, independent of flags', async () => {
    const user = userEvent.setup();
    render(
      <ProfileProvider fixture={financialGateFixture}>
        <SlotCard slot="top_right" />
        <ActionBar />
      </ProfileProvider>,
    );

    // Nothing is flagged in this fixture and all four slots start assigned, so
    // export starts unblocked.
    expect(screen.getByRole('button', { name: 'Export .pptx' })).not.toBeDisabled();

    // Deselect the only series-bearing block. There are zero flags anywhere in
    // this fixture, so a gate that only checked "any open flags" would wrongly
    // unblock export here. The dedicated financial-series requirement must catch it.
    await user.click(screen.getByRole('button', { name: /Financial series block/ }));
    await user.click(screen.getByRole('radio', { name: /Non-financial alt block/i }));

    const exportButton = screen.getByRole('button', { name: 'Export .pptx' });
    expect(exportButton).toBeDisabled();
    expect(screen.getByText('assign at least one financial series')).toBeInTheDocument();
  });

  it('requires all four slots to be assigned, independent of flags', () => {
    // The current UI always keeps every slot populated (canonical default, swap-only
    // dropdowns; there is no "clear slot" control), so this exercises the store's own
    // guarantee directly rather than through a click path the UI doesn't yet expose.
    const missingSlotFixture: ProfileFixture = {
      ...financialGateFixture,
      canonicalLayout: {
        ...financialGateFixture.canonicalLayout,
        bottom_right: null as unknown as string,
      },
    };

    render(
      <ProfileProvider fixture={missingSlotFixture}>
        <ActionBar />
      </ProfileProvider>,
    );

    const exportButton = screen.getByRole('button', { name: 'Export .pptx' });
    expect(exportButton).toBeDisabled();
    expect(screen.getByText('all four slots must be assigned')).toBeInTheDocument();
  });
});

describe('D0.3 - the action bar must not overlap the last slot card at narrow viewports', () => {
  it('main content reserves bottom clearance that matches the sticky action bar', async () => {
    await renderApp();

    // jsdom has no real layout engine, so this locks the specific Tailwind classes
    // the fix relies on rather than measuring pixels. Live-browser verification at
    // a 375px viewport (see session notes) confirmed the actual pre-fix defect:
    // the pre-fix action bar had no `flex-wrap`, so at narrow widths its buttons
    // and warning text overflowed horizontally -- the Export .pptx button's right
    // edge landed 40px past the viewport edge, effectively unreachable. Post-fix,
    // `flex-wrap` (with the warning text on `basis-full`) keeps everything on
    // screen, and `pb-24`/`sm:pb-6` on <main> reserve clearance so the now up-to
    // two-row bar never sits on top of the last thing scrolled into view above it.
    const main = document.querySelector('main');
    expect(main).not.toBeNull();
    expect(main?.className).toMatch(/\bpb-24\b/);
    expect(main?.className).toMatch(/\bsm:pb-6\b/);

    const actionBar = screen.getByRole('button', { name: 'Export .pptx' }).closest('div');
    expect(actionBar?.className).toMatch(/\bsticky\b/);
    expect(actionBar?.className).toMatch(/\bbottom-0\b/);
    expect(actionBar?.className).toMatch(/\bflex-wrap\b/);
  });
});
