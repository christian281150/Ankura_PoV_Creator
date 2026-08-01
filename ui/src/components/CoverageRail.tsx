import { Meter } from '@/components/ui/Meter';
import { useProfile } from '@/state/profileStore';

export function CoverageRail() {
  const { fixture } = useProfile();
  return (
    <section className="border border-rule bg-paper-raised px-4 py-3">
      <p className="label-caps mb-3">Coverage by dimension</p>
      <div className="space-y-2">
        {fixture.coverage.map((c) => (
          <Meter key={c.label} label={c.label} value={c.score} />
        ))}
      </div>
      <p className="mt-3 border-t border-rule-hair pt-2 text-xs text-ink-3">
        Below .70 the box needs an explicit caveat. Gaps are printed on the slide, never filled.
      </p>
    </section>
  );
}
