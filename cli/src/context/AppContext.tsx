/**
 * Global application context — shared state for settings, session, permissions, and UI toggles.
 *
 * Split into two providers:
 *   SettingsContext — rarely changes (settings, theme, model, permission mode)
 *   SessionContext  — changes per-event (token usage, stage, checkpoints)
 */

import React, { createContext, useContext, useState, useCallback, type ReactNode } from 'react';
import type {
  Settings,
  Session,
  TokenUsage,
  PermissionMode,
  ThemeName,
} from '../lib/types.js';
import { PERMISSION_MODES, DEFAULT_SETTINGS } from '../lib/types.js';
import { saveSettings } from '../lib/settings.js';
import { saveSession } from '../lib/session.js';
import { getThemeColors, type ThemeColors } from '../lib/theme.js';

// ── Settings Context ─────────────────────────────────────────────────────────

interface SettingsContextValue {
  settings: Settings;
  themeColors: ThemeColors;
  permissionMode: PermissionMode;
  currentModel: string;
  promptColor: string;
  verboseMode: boolean;
  thinkingVisible: boolean;
  quality: 'low' | 'medium' | 'high';
  gitBranch: string | null;
  updateSetting: <K extends keyof Settings>(key: K, value: Settings[K]) => void;
  setPermissionMode: (mode: PermissionMode) => void;
  cyclePermissionMode: () => void;
  setCurrentModel: (model: string) => void;
  setPromptColor: (color: string) => void;
  setVerboseMode: (v: boolean | ((prev: boolean) => boolean)) => void;
  setThinkingVisible: (v: boolean | ((prev: boolean) => boolean)) => void;
  setQuality: (q: 'low' | 'medium' | 'high') => void;
  setGitBranch: (branch: string | null) => void;
}

const SettingsContext = createContext<SettingsContextValue | null>(null);

// ── Session Context ──────────────────────────────────────────────────────────

interface SessionContextValue {
  session: Session;
  tokenUsage: TokenUsage;
  commandHistory: string[];
  updateSession: (partial: Partial<Session>) => void;
  addTokenUsage: (delta: { input: number; output: number; cacheRead?: number }) => void;
  pushHistory: (entry: string) => void;
}

const SessionContext = createContext<SessionContextValue | null>(null);

// ── Provider ─────────────────────────────────────────────────────────────────

interface AppContextProviderProps {
  settings: Settings;
  session: Session;
  gitBranch: string | null;
  children: ReactNode;
}

export function AppContextProvider({ settings: initialSettings, session: initialSession, gitBranch: initialBranch, children }: AppContextProviderProps) {
  // Settings state
  const [settings, setSettings] = useState<Settings>(initialSettings);
  const [permissionMode, setPermissionModeState] = useState<PermissionMode>(initialSettings.defaultMode);
  const [currentModel, setCurrentModelState] = useState<string>(initialSettings.model);
  const [promptColor, setPromptColorState] = useState<string>(initialSettings.promptColor);
  const [verboseMode, setVerboseModeState] = useState<boolean>(initialSettings.outputStyle === 'verbose');
  const [thinkingVisible, setThinkingVisibleState] = useState<boolean>(false);
  const [quality, setQualityState] = useState<'low' | 'medium' | 'high'>(initialSettings.quality);
  const [gitBranch, setGitBranchState] = useState<string | null>(initialBranch);

  const themeColors = getThemeColors(settings.theme);

  const updateSetting = useCallback(<K extends keyof Settings>(key: K, value: Settings[K]) => {
    setSettings(prev => {
      const next = { ...prev, [key]: value };
      // Persist to user scope
      saveSettings('user', { [key]: value });
      return next;
    });

    // Sync derived state
    if (key === 'model') setCurrentModelState(value as string);
    if (key === 'promptColor') setPromptColorState(value as string);
    if (key === 'defaultMode') setPermissionModeState(value as PermissionMode);
    if (key === 'quality') setQualityState(value as 'low' | 'medium' | 'high');
  }, []);

  const setPermissionMode = useCallback((mode: PermissionMode) => {
    setPermissionModeState(mode);
  }, []);

  const cyclePermissionMode = useCallback(() => {
    setPermissionModeState(current => {
      const idx = PERMISSION_MODES.indexOf(current);
      return PERMISSION_MODES[(idx + 1) % PERMISSION_MODES.length]!;
    });
  }, []);

  const setCurrentModel = useCallback((model: string) => {
    setCurrentModelState(model);
    saveSettings('user', { model });
  }, []);

  const setPromptColor = useCallback((color: string) => {
    setPromptColorState(color);
    saveSettings('user', { promptColor: color });
  }, []);

  const setVerboseMode = useCallback((v: boolean | ((prev: boolean) => boolean)) => {
    setVerboseModeState(v);
  }, []);

  const setThinkingVisible = useCallback((v: boolean | ((prev: boolean) => boolean)) => {
    setThinkingVisibleState(v);
  }, []);

  const setQuality = useCallback((q: 'low' | 'medium' | 'high') => {
    setQualityState(q);
    saveSettings('user', { quality: q });
  }, []);

  const setGitBranch = useCallback((branch: string | null) => {
    setGitBranchState(branch);
  }, []);

  // Session state
  const [session, setSession] = useState<Session>(initialSession);
  const [tokenUsage, setTokenUsage] = useState<TokenUsage>(initialSession.tokenUsage);
  const [commandHistory, setCommandHistory] = useState<string[]>([]);

  const updateSession = useCallback((partial: Partial<Session>) => {
    setSession(prev => {
      const next = { ...prev, ...partial };
      saveSession(next);
      return next;
    });
  }, []);

  const addTokenUsage = useCallback((delta: { input: number; output: number; cacheRead?: number }) => {
    setTokenUsage(prev => ({
      input: prev.input + delta.input,
      output: prev.output + delta.output,
      cacheRead: prev.cacheRead + (delta.cacheRead ?? 0),
    }));
  }, []);

  const pushHistory = useCallback((entry: string) => {
    setCommandHistory(prev => {
      const filtered = prev.filter(h => h !== entry);
      return [...filtered, entry].slice(-100); // keep last 100 entries
    });
  }, []);

  const settingsValue: SettingsContextValue = {
    settings,
    themeColors,
    permissionMode,
    currentModel,
    promptColor,
    verboseMode,
    thinkingVisible,
    quality,
    gitBranch,
    updateSetting,
    setPermissionMode,
    cyclePermissionMode,
    setCurrentModel,
    setPromptColor,
    setVerboseMode,
    setThinkingVisible,
    setQuality,
    setGitBranch,
  };

  const sessionValue: SessionContextValue = {
    session,
    tokenUsage,
    commandHistory,
    updateSession,
    addTokenUsage,
    pushHistory,
  };

  return (
    <SettingsContext.Provider value={settingsValue}>
      <SessionContext.Provider value={sessionValue}>
        {children}
      </SessionContext.Provider>
    </SettingsContext.Provider>
  );
}

// ── Hooks ────────────────────────────────────────────────────────────────────

export function useSettingsContext(): SettingsContextValue {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error('useSettingsContext must be used inside AppContextProvider');
  return ctx;
}

export function useSessionContext(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error('useSessionContext must be used inside AppContextProvider');
  return ctx;
}

/** Combined convenience hook */
export function useAppContext() {
  return {
    ...useSettingsContext(),
    ...useSessionContext(),
  };
}
