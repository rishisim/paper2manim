/**
 * SettingsPanel — Tabbed settings UI (User / Project / Local).
 * Mirrors Claude Code CLI's /config interface.
 */

import React, { useState } from 'react';
import { Box, Text, useInput } from 'ink';
import { useAppContext } from '../context/AppContext.js';
import { loadSettings, saveSettings, getSettingsPath, type SettingsScope } from '../lib/settings.js';
import { existsSync, readFileSync } from 'node:fs';
import type { Settings } from '../lib/types.js';

const TABS: { label: string; scope: SettingsScope }[] = [
  { label: 'User', scope: 'user' },
  { label: 'Project', scope: 'project' },
  { label: 'Local', scope: 'local' },
];

const EDITABLE_KEYS: (keyof Settings)[] = [
  'model', 'theme', 'defaultMode', 'outputStyle', 'editorMode',
  'quality', 'statusLine', 'disableAllHooks', 'promptColor',
];

interface SettingsPanelProps {
  onBack: () => void;
}

export function SettingsPanel({ onBack }: SettingsPanelProps) {
  const { themeColors, updateSetting } = useAppContext();
  const [activeTab, setActiveTab] = useState(0);
  const [selectedRow, setSelectedRow] = useState(0);

  const scope = TABS[Math.min(activeTab, TABS.length - 1)]!.scope;
  const scopePath = getSettingsPath(scope);
  // C5: Wrap in try-catch — a bad settings file must not crash the component
  let scopeSettings: Partial<Settings> = {};
  let settingsLoadError: string | null = null;
  if (existsSync(scopePath)) {
    try {
      scopeSettings = JSON.parse(readFileSync(scopePath, 'utf8') || '{}') as Partial<Settings>;
    } catch (err) {
      settingsLoadError = String(err);
    }
  }

  const rows = EDITABLE_KEYS.map(key => ({
    key,
    value: scopeSettings[key] !== undefined ? String(scopeSettings[key]) : '(not set)',
    hasValue: scopeSettings[key] !== undefined,
  }));

  useInput((_input, key) => {
    if (key.escape) { onBack(); return; }

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
  });

  return (
    <Box flexDirection="column" paddingX={1}>
      <Text bold color={themeColors.primary}>Settings</Text>
      <Text color={themeColors.dim}>← → switch scopes · ↑↓ navigate · Esc back</Text>

      {/* Tab bar */}
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

      {/* C5: Show load error instead of crashing */}
      {settingsLoadError && (
        <Box marginBottom={1}>
          <Text color={themeColors.warn}>[WARN] Could not read settings file: {settingsLoadError}</Text>
        </Box>
      )}

      {/* Settings rows */}
      <Box flexDirection="column">
        {rows.map((row, idx) => {
          const isSelected = idx === selectedRow;
          return (
            <Box key={row.key} paddingLeft={isSelected ? 0 : 2}>
              {isSelected && <Text color={themeColors.primary} bold>▸ </Text>}
              <Text color={themeColors.text} bold={isSelected}>{row.key}</Text>
              <Text color={themeColors.dim}>{': '}</Text>
              <Text color={row.hasValue ? themeColors.success : themeColors.dim}>
                {row.value}
              </Text>
            </Box>
          );
        })}
      </Box>

      <Box marginTop={1}>
        <Text color={themeColors.dim}>
          Edit {scopePath.replace(process.env['HOME'] ?? '', '~')} directly to modify these settings.
        </Text>
      </Box>
    </Box>
  );
}
