/**
 * React hook for accessing and updating session state via AppContext.
 */

import { useSessionContext } from '../context/AppContext.js';
import { exportSessionToText } from '../lib/session.js';

export function useSession() {
  const { session, tokenUsage, commandHistory, updateSession, addTokenUsage, pushHistory } = useSessionContext();

  const exportSession = (filename?: string) => {
    const path = exportSessionToText(session);
    return path;
  };

  return {
    session,
    tokenUsage,
    commandHistory,
    updateSession,
    addTokenUsage,
    pushHistory,
    exportSession,
  };
}
