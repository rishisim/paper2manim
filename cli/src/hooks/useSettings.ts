/**
 * React hook for accessing and updating settings via AppContext.
 */

import { useSettingsContext } from '../context/AppContext.js';
import type { Settings } from '../lib/types.js';

export function useSettings() {
  const { settings, updateSetting } = useSettingsContext();
  return { settings, updateSetting };
}

export function useSetting<K extends keyof Settings>(key: K): [Settings[K], (value: Settings[K]) => void] {
  const { settings, updateSetting } = useSettingsContext();
  return [settings[key], (value: Settings[K]) => updateSetting(key, value)];
}
