/**
 * Session lifecycle management for paper2manim.
 * Sessions are stored at ~/.paper2manim/sessions/<id>.json
 */

import { existsSync, readFileSync, writeFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { nanoid } from 'nanoid';
import { getSessionsDir, getExportsDir } from './settings.js';
import type { Session, SessionCheckpoint, PermissionMode } from './types.js';

export function createSession(name?: string, permissionMode: PermissionMode = 'default'): Session {
  return {
    id: nanoid(12),
    name: name ?? null,
    startedAt: new Date().toISOString(),
    concept: '',
    stage: null,
    checkpoints: [],
    tokenUsage: { input: 0, output: 0, cacheRead: 0 },
    permissionMode,
  };
}

export function saveSession(session: Session): void {
  const dir = getSessionsDir();
  const path = join(dir, `${session.id}.json`);
  try {
    writeFileSync(path, JSON.stringify(session, null, 2) + '\n', 'utf8');
  } catch { /* ignore */ }
}

export function loadSession(idOrName: string): Session | null {
  const dir = getSessionsDir();
  if (!existsSync(dir)) return null;

  try {
    const files = readdirSync(dir).filter(f => f.endsWith('.json'));

    // Try by ID first
    const byId = join(dir, `${idOrName}.json`);
    if (existsSync(byId)) {
      return JSON.parse(readFileSync(byId, 'utf8')) as Session;
    }

    // Try by name
    for (const file of files) {
      try {
        const session = JSON.parse(readFileSync(join(dir, file), 'utf8')) as Session;
        if (session.name === idOrName) return session;
      } catch { /* skip bad files */ }
    }
  } catch { /* ignore */ }

  return null;
}

export function listSessions(): Session[] {
  const dir = getSessionsDir();
  if (!existsSync(dir)) return [];

  try {
    const files = readdirSync(dir).filter(f => f.endsWith('.json'));
    const sessions: Session[] = [];
    for (const file of files) {
      try {
        const session = JSON.parse(readFileSync(join(dir, file), 'utf8')) as Session;
        sessions.push(session);
      } catch { /* skip */ }
    }
    return sessions.sort((a, b) =>
      new Date(b.startedAt).getTime() - new Date(a.startedAt).getTime()
    );
  } catch {
    return [];
  }
}

export function getMostRecentSession(): Session | null {
  const sessions = listSessions();
  return sessions[0] ?? null;
}

export function saveCheckpoint(session: Session, checkpoint: SessionCheckpoint): Session {
  const updated: Session = {
    ...session,
    checkpoints: [...session.checkpoints, checkpoint],
    stage: checkpoint.stage,
    concept: checkpoint.concept || session.concept,
  };
  saveSession(updated);
  return updated;
}

export function exportSessionToText(session: Session): string {
  const dir = getExportsDir();
  const lines: string[] = [
    `# paper2manim Session Export`,
    `Session ID: ${session.id}`,
    session.name ? `Name: ${session.name}` : '',
    `Started: ${session.startedAt}`,
    `Concept: ${session.concept}`,
    `Final Stage: ${session.stage ?? 'n/a'}`,
    `Permission Mode: ${session.permissionMode}`,
    ``,
    `## Token Usage`,
    `  Input:  ${session.tokenUsage.input.toLocaleString()}`,
    `  Output: ${session.tokenUsage.output.toLocaleString()}`,
    `  Cache:  ${session.tokenUsage.cacheRead.toLocaleString()}`,
  ].filter(l => l !== undefined);

  const content = lines.join('\n') + '\n';
  const filename = `${session.id}-${new Date().toISOString().replace(/[:.]/g, '-')}.txt`;
  const path = join(dir, filename);
  try {
    writeFileSync(path, content, 'utf8');
  } catch { /* ignore */ }
  return path;
}
