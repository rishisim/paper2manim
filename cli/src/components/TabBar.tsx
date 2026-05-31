import React from 'react';
import { Box, Text } from 'ink';
import { useAppContext } from '../context/AppContext.js';

export type TabId = 'overview' | 'code' | 'activity' | 'timeline' | 'summary';

export interface TabDef {
  id: TabId;
  label: string;
  badge?: string;
  badgeColor?: string;
}

interface TabBarProps {
  tabs: TabDef[];
  activeTab: TabId;
  onSelect?: (tabId: TabId) => void;
}

/**
 * Compute the X ranges for each tab label so mouse clicks can be mapped.
 * Returns array of {id, startX, endX} (1-indexed columns).
 */
export function getTabClickRegions(tabs: TabDef[]): Array<{ id: TabId; startX: number; endX: number }> {
  const regions: Array<{ id: TabId; startX: number; endX: number }> = [];
  let x = 2; // paddingLeft=1 + 1 for 1-indexed
  for (let i = 0; i < tabs.length; i++) {
    const tab = tabs[i]!;
    const text = `${i + 1}:${tab.label}`;
    const badgeLen = tab.badge ? tab.badge.length + 1 : 0;
    const totalLen = text.length + badgeLen;
    regions.push({ id: tab.id, startX: x, endX: x + totalLen - 1 });
    x += totalLen + 1; // +1 for marginRight gap
  }
  return regions;
}

export function TabBar({ tabs, activeTab }: TabBarProps) {
  const { themeColors } = useAppContext();

  return (
    <Box paddingLeft={1} marginBottom={0}>
      {tabs.map((tab, idx) => {
        const isActive = tab.id === activeTab;
        const shortcut = idx + 1;
        return (
          <Box key={tab.id} marginRight={1}>
            <Text
              color={isActive ? themeColors.text : themeColors.muted}
              bold={isActive}
              underline={isActive}
            >
              {shortcut}:{tab.label}
            </Text>
            {tab.badge && (
              <Text color={tab.badgeColor ?? themeColors.warn}> {tab.badge}</Text>
            )}
          </Box>
        );
      })}
    </Box>
  );
}
