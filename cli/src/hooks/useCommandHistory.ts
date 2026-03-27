/**
 * useCommandHistory — Read command history from AppContext.
 * History is managed in the SessionContext and shared across components.
 */

import { useSessionContext } from '../context/AppContext.js';

export function useCommandHistory() {
  const { commandHistory, pushHistory } = useSessionContext();
  return { commandHistory, pushHistory };
}
