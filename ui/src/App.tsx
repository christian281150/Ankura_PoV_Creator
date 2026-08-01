import { SLOT_ORDER } from '@/types/profile';
import { seidensticker } from '@/data/seidensticker';
import { ProfileProvider } from '@/state/profileStore';
import { EntityBar } from '@/components/EntityBar';
import { SlotCard } from '@/components/SlotCard';
import { FlagPanel } from '@/components/FlagPanel';
import { BasisGuard } from '@/components/BasisGuard';
import { PreviewPane } from '@/components/PreviewPane';
import { CoverageRail } from '@/components/CoverageRail';
import { ActionBar } from '@/components/ActionBar';

const SLOT_NEIGHBOUR: Record<string, Partial<Record<'ArrowUp' | 'ArrowDown' | 'ArrowLeft' | 'ArrowRight', string>>> = {
  top_left: { ArrowRight: 'top_right', ArrowDown: 'bottom_left' },
  top_right: { ArrowLeft: 'top_left', ArrowDown: 'bottom_right' },
  bottom_left: { ArrowUp: 'top_left', ArrowRight: 'bottom_right' },
  bottom_right: { ArrowUp: 'top_right', ArrowLeft: 'bottom_left' },
};

export default function App() {
  return (
    <ProfileProvider fixture={seidensticker}>
      <a href="#slots" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:bg-pine focus:px-3 focus:py-2 focus:text-white">
        Skip to slot assignment
      </a>

      <div className="flex min-h-screen flex-col">
        <EntityBar />

        <main className="flex-1 px-4 py-6 pb-24 sm:px-8 sm:pb-6">
          <div className="mb-5 flex items-baseline justify-between border-b border-rule pb-3">
            <div>
              <h2 className="text-xl font-semibold text-ink">Slot assignment</h2>
              <p className="mt-0.5 font-mono text-micro text-ink-3">
                Screen 5 of 7 · fixed four-box skeleton · blocks swap within a slot, slots do not change
              </p>
            </div>
            <p className="font-mono text-micro text-ink-3">step 5 / 7</p>
          </div>

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_400px]">
            <div
              id="slots"
              className="grid grid-cols-1 gap-4 lg:grid-cols-2"
              onKeyDown={(event) => {
                const trigger = (event.target as HTMLElement).closest<HTMLElement>('[data-slot-trigger]');
                const currentSlot = trigger?.dataset.slotTrigger;
                const nextSlot = currentSlot && SLOT_NEIGHBOUR[currentSlot]?.[event.key as keyof typeof SLOT_NEIGHBOUR.top_left];
                if (!trigger || !nextSlot) return;
                event.preventDefault();
                document.querySelector<HTMLButtonElement>(`[data-slot-trigger="${nextSlot}"]`)?.focus();
              }}
            >
              {SLOT_ORDER.map((slot) => (
                <SlotCard key={slot} slot={slot} />
              ))}
            </div>

            <aside className="space-y-5">
              <PreviewPane />
              <BasisGuard />
              <FlagPanel />
              <CoverageRail />
            </aside>
          </div>
        </main>

        <ActionBar />
      </div>
    </ProfileProvider>
  );
}
