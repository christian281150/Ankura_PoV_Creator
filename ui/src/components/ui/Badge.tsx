import { cn } from '@/lib/format';

type Tone = 'pine' | 'amber' | 'rust' | 'neutral';

const TONE: Record<Tone, string> = {
  pine: 'bg-pine-100 text-pine border-pine-600/40',
  amber: 'bg-amber-100 text-amber border-amber-600/40',
  rust: 'bg-rust-100 text-rust border-rust-600/40',
  neutral: 'bg-paper-sunk text-ink-2 border-rule',
};

export function Badge({ tone = 'neutral', children }: { tone?: Tone; children: React.ReactNode }) {
  return (
    <span
      className={cn(
        'inline-flex items-center border px-1.5 py-0.5 font-mono text-micro uppercase tracking-[0.1em]',
        TONE[tone],
      )}
    >
      {children}
    </span>
  );
}
