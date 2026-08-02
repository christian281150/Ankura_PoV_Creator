import { seidensticker } from '@/data/seidensticker';
import type { ProfileFixture } from '@/types/profile';

/**
 * Keep local development runnable before the Python API is available. Set
 * VITE_USE_PROFILE_FIXTURE=false to exercise the API from a dev server.
 * Vite excludes this branch from production builds because DEV is false.
 */
const useFixtureFallback = import.meta.env.DEV && import.meta.env.VITE_USE_PROFILE_FIXTURE !== 'false';

export async function loadProfile(entityId: string): Promise<ProfileFixture> {
  if (useFixtureFallback) return seidensticker;

  const response = await fetch(`/api/profiles/${encodeURIComponent(entityId)}`);
  if (!response.ok) throw new Error(`profile ${entityId}: ${response.status}`);
  return response.json() as Promise<ProfileFixture>;
}
