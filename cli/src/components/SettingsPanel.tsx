import React, { useMemo, useState } from 'react';
import { Box, Text, useInput } from 'ink';
import { existsSync, readFileSync } from 'node:fs';
import { useAppContext } from '../context/AppContext.js';
import { getSettingsPath, loadSettings, saveSettings, type SettingsScope } from '../lib/settings.js';
import { PERMISSION_MODES, type EffectiveSettingRow, type Settings, type ThemeName } from '../lib/types.js';

const TABS: { label: string; scope: SettingsScope }[] = [
  { label: 'User', scope: 'user' },
  { label: 'Project', scope: 'project' },
  { label: 'Local', scope: 'local' },
];

const EDITABLE_KEYS: (keyof Settings)[] = [
  'model',
  'theme',
  'defaultMode',
  'quality',
];

const DISPLAY_KEYS: (keyof Settings)[] = [
  'model',
  'theme',
  'defaultMode',
  'quality',
  'outputStyle',
  'editorMode',
  'promptColor',
  'statusLine',
  'disableAllHooks',
];

const THEME_OPTIONS: ThemeName[] = ['dark', 'light', 'minimal', 'colorblind', 'ansi'];
const QUALITY_OPTIONS: Array<'low' | 'medium' | 'high'> = ['low', 'medium', 'high'];
const MODEL_OPTIONS = ['openai-default', 'anthropic-legacy', 'gpt-5.4', 'gpt-5.3-codex', 'gpt-5.4-mini'];

interface SettingsPanelProps {
  onBack: () => void;
}

function readScopeSettings(path: string): Partial<Settings> {
  if (!existsSync(path)) return {};
  try {
    return JSON.parse(readFileSync(path, 'utf8') || '{}') as Partial<Settings>;
  } catch {
    return {};
  }
}

function nextValue<T extends string>(values: readonly T[], current: string): T {
  const idx = values.indexOf(current as T);
  return values[(idx + 1) % values.length] ?? values[0]!;
}

export function SettingsPanel({ onBack }: SettingsPanelProps) {
  const { themeColors } = useAppContext();
  const [activeTab, setActiveTab] = useState(0);
  const [selectedRow, setSelectedRow] = useState(0);
  const [infoMessage, setInfoMessage] = useState<string>('');
  const [reloadToken, setReloadToken] = useState(0);

  const scope = TABS[Math.min(activeTab, TABS.length - 1)]!.scope;
  const scopePath = getSettingsPath(scope);
  const scopeSettings = useMemo(() => readScopeSettings(scopePath), [scopePath, reloadToken]);
  const effectiveSettings = useMemo(() => loadSettings(), [reloadToken]);

  const rows: EffectiveSettingRow[] = DISPLAY_KEYS.map(key => {
    const scopeValue = scopeSettings[key] !== undefined ? String(scopeSettings[key]) : '(inherit)';
    const effectiveValue = String(effectiveSettings[key]);
    return {
      key,
      scopeValue,
      effectiveValue,
      scopeOverride: scopeSettings[key] !== undefined,
    };
  });

  useInput((input, key) => {
    if (key.escape) {
      onBack();
      return;
    }
    if (key.leftArrow) {
      setActiveTab(t => Math.max(0, t - 1));
      setSelectedRow(0);
      return;
    }
    if (key.rightArrow) {
      setActiveTab(t => Math.min(TABS.length - 1, t + 1));
      setSelectedRow(0);
      return;
    }
    if (key.upArrow) {
      setSelectedRow(r => Math.max(0, r - 1));
      return;
    }
    if (key.downArrow) {
      setSelectedRow(r => Math.min(rows.length - 1, r + 1));
      return;
    }
    if (!key.return) return;

    const row = rows[selectedRow];
    if (!row || !EDITABLE_KEYS.includes(row.key)) {
      setInfoMessage('This row is read-only in the panel.');
      return;
    }

    let next: string;
    switch (row.key) {
      case 'theme':
        next = nextValue(THEME_OPTIONS, row.scopeOverride ? row.scopeValue : row.effectiveValue);
        break;
      case 'quality':
        next = nextValue(QUALITY_OPTIONS, row.scopeOverride ? row.scopeValue : row.effectiveValue);
        break;
      case 'defaultMode':
        next = nextValue(PERMISSION_MODES, row.scopeOverride ? row.scopeValue : row.effectiveValue);
        break;
      case 'model':
        next = nextValue(MODEL_OPTIONS, row.scopeOverride ? row.scopeValue : row.effectiveValue);
        break;
      default:
        next = row.effectiveValue;
    }

    saveSettings(scope, { [row.key]: next } as Partial<Settings>);
    setReloadToken(prev => prev + 1);
    setInfoMessage(`Saved ${row.key}=${next} to ${scope}.`);
  });

  return (
    <Box flexDirection="column" paddingX={1}>
      <Text bold color={themeColors.primary}>Settings</Text>
      <Text color={themeColors.dim}>← → scope · ↑↓ row · Enter cycle value · Esc back</Text>

      <Box flexDirection="row" marginTop={1} marginBottom={1}>
        {TABS.map((tab, idx) => (
          <Box key={tab.scope} marginRight={2}>
            <Text
              color={idx === activeTab ? themeColors.primary : themeColors.dim}
              bold={idx === activeTab}
              underline={idx === activeTab}
            >
              {tab.label}
            </Text>
            {idx === activeTab && (
              <Text color={themeColors.dim}> ({scopePath.replace(process.env['HOME'] ?? '', '~')})</Text>
            )}
          </Box>
        ))}
      </Box>

      <Box marginBottom={1}>
        <Text color={themeColors.dim}>Legend: </Text>
        <Text color={themeColors.success}>override</Text>
        <Text color={themeColors.dim}> means this scope sets a value. </Text>
        <Text color={themeColors.warn}>inherit</Text>
        <Text color={themeColors.dim}> means it falls back to lower scopes.</Text>
      </Box>

      <Box flexDirection="column">
        {rows.map((row, idx) => {
          const selected = idx === selectedRow;
          const editable = EDITABLE_KEYS.includes(row.key);
          return (
            <Box key={row.key} paddingLeft={selected ? 0 : 2}>
              {selected && <Text color={themeColors.primary} bold>▸ </Text>}
              <Text bold={selected}>{row.key.padEnd(14)}</Text>
              <Text color={row.scopeOverride ? themeColors.success : themeColors.warn}>
                {row.scopeOverride ? 'override' : 'inherit '}
              </Text>
              <Text color={themeColors.dim}> scope=</Text>
              <Text color={themeColors.muted}>{row.scopeValue}</Text>
              <Text color={themeColors.dim}>  effective=</Text>
              <Text color={themeColors.text}>{row.effectiveValue}</Text>
              {editable && <Text color={themeColors.primary}>  (Enter to cycle)</Text>}
            </Box>
          );
        })}
      </Box>

      <Box marginTop={1}>
        <Text color={themeColors.dim}>
          Advanced: you can still edit {scopePath.replace(process.env['HOME'] ?? '', '~')} manually for unsupported keys.
        </Text>
      </Box>
      {infoMessage && (
        <Box marginTop={1}>
          <Text color={themeColors.success}>{infoMessage}</Text>
        </Box>
      )}
    </Box>
  );
}
