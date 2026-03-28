import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Box, Text, useInput, useApp } from 'ink';
import { execSync } from 'node:child_process';
import { resolve } from 'node:path';
import { colors } from '../lib/theme.js';
import { spawnRunner } from '../lib/process.js';
import type { Project } from '../lib/types.js';

interface WorkspaceDashboardProps {
  onResume: (concept: string, dir: string) => void;
  onBack: () => void;
}

type SubScreen = 'list' | 'actions' | 'summary' | 'confirm-delete' | 'confirm-cleanup';

export function WorkspaceDashboard({ onResume, onBack }: WorkspaceDashboardProps) {
  const { exit } = useApp();
  const [projects, setProjects] = useState<Project[]>([]);
  const [placeholderCount, setPlaceholderCount] = useState(0);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [subScreen, setSubScreen] = useState<SubScreen>('list');
  const [summaryText, setSummaryText] = useState<string | null>(null);
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(true);
  const procRef = useRef<ReturnType<typeof spawnRunner> | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchProjects = useCallback(() => {
    if (procRef.current && !procRef.current.killed) {
      procRef.current.stdout?.removeAllListeners();
      procRef.current.removeAllListeners();
      procRef.current.kill();
    }
    setLoading(true);
    const proc = spawnRunner(JSON.stringify({ mode: 'workspace', workspace_action: 'list' }));
    procRef.current = proc;
    let buffer = '';

    proc.stdout?.on('data', (chunk: Buffer) => {
      buffer += chunk.toString();
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const msg = JSON.parse(line);
          if (msg.type === 'workspace_projects') {
            setProjects(msg.projects ?? []);
            setPlaceholderCount(msg.placeholder_count ?? 0);
            setLoading(false);
          }
        } catch { /* ignore */ }
      }
    });

    proc.on('close', () => {
      if (buffer.trim()) {
        try {
          const msg = JSON.parse(buffer.trim());
          if (msg.type === 'workspace_projects') {
            setProjects(msg.projects ?? []);
            setPlaceholderCount(msg.placeholder_count ?? 0);
          }
        } catch { /* ignore */ }
      }
      setLoading(false);
    });
  }, []);

  useEffect(() => {
    fetchProjects();
    return () => {
      if (procRef.current && !procRef.current.killed) {
        procRef.current.stdout?.removeAllListeners();
        procRef.current.removeAllListeners();
        procRef.current.kill();
      }
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [fetchProjects]);

  const deleteProject = useCallback((dir: string) => {
    const proc = spawnRunner(JSON.stringify({ mode: 'workspace', workspace_action: 'delete', target_dir: dir }));
    proc.on('close', () => {
      setMessage('Project deleted.');
      setSubScreen('list');
      setSelectedIdx(0);
      fetchProjects();
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setMessage(''), 2000);
    });
  }, [fetchProjects]);

  const cleanupPlaceholders = useCallback(() => {
    const proc = spawnRunner(JSON.stringify({ mode: 'workspace', workspace_action: 'cleanup' }));
    proc.on('close', () => {
      setMessage('Stale entries cleaned.');
      setSubScreen('list');
      fetchProjects();
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setMessage(''), 2000);
    });
  }, [fetchProjects]);

  const viewSummary = useCallback((dir: string) => {
    const proc = spawnRunner(JSON.stringify({ mode: 'workspace', workspace_action: 'view_summary', target_dir: dir }));
    let buffer = '';
    proc.stdout?.on('data', (chunk: Buffer) => {
      buffer += chunk.toString();
    });
    proc.on('close', () => {
      try {
        const msg = JSON.parse(buffer.trim());
        if (msg.type === 'workspace_summary') {
          setSummaryText(msg.text);
          setSubScreen('summary');
        }
      } catch {
        setSummaryText(null);
        setSubScreen('summary');
      }
    });
  }, []);

  useInput((input, key) => {
    if (subScreen === 'list') {
      if (key.upArrow) {
        setSelectedIdx(prev => Math.max(0, prev - 1));
      } else if (key.downArrow) {
        setSelectedIdx(prev => Math.min(projects.length - 1, prev + 1));
      } else if (key.return && projects.length > 0) {
        setSubScreen('actions');
      } else if (input === 'x' && placeholderCount > 0) {
        setSubScreen('confirm-cleanup');
      } else if (input === 'q' || key.escape) {
        onBack();
      }
    } else if (subScreen === 'actions') {
      const project = projects[selectedIdx];
      if (!project) { setSubScreen('list'); return; }

      if (input === 'r') {
        onResume(project.concept, project.dir);
      } else if (input === 'v') {
        viewSummary(project.dir);
      } else if (input === 'd') {
        setSubScreen('confirm-delete');
      } else if (input === 'c' || key.escape) {
        setSubScreen('list');
      }
    } else if (subScreen === 'summary') {
      if (key.return || key.escape || input === 'q') {
        setSubScreen('actions');
      }
    } else if (subScreen === 'confirm-delete') {
      const project = projects[selectedIdx];
      if (input === 'y' && project) {
        deleteProject(project.dir);
      } else {
        setSubScreen('actions');
      }
    } else if (subScreen === 'confirm-cleanup') {
      if (input === 'y') {
        cleanupPlaceholders();
      } else {
        setSubScreen('list');
      }
    }
  });

  if (loading) {
    return (
      <Box flexDirection="column" paddingX={1}>
        <Text bold>Project Workspace</Text>
        <Text color={colors.dim}>Loading projects...</Text>
      </Box>
    );
  }

  // ── Summary sub-screen ──────────────────────────────────────────
  if (subScreen === 'summary') {
    return (
      <Box flexDirection="column" paddingX={1}>
        <Text bold>Pipeline Summary</Text>
        <Box marginTop={1}>
          <Text>{summaryText ?? 'No pipeline summary found for this project yet.'}</Text>
        </Box>
        <Box marginTop={1}>
          <Text color={colors.dim}>Press <Text bold>Enter</Text> to go back</Text>
        </Box>
      </Box>
    );
  }

  // ── Confirm delete ──────────────────────────────────────────────
  if (subScreen === 'confirm-delete') {
    const project = projects[selectedIdx];
    return (
      <Box flexDirection="column" paddingX={1}>
        <Text color="red" bold>Delete project "{project?.concept}"?</Text>
        <Text color={colors.dim}>This will permanently remove all files.</Text>
        <Box marginTop={1}>
          <Text>Press <Text bold>y</Text> to confirm, any other key to cancel</Text>
        </Box>
      </Box>
    );
  }

  // ── Confirm cleanup ─────────────────────────────────────────────
  if (subScreen === 'confirm-cleanup') {
    return (
      <Box flexDirection="column" paddingX={1}>
        <Text color="yellow" bold>Clean {placeholderCount} stale workspace entries?</Text>
        <Box marginTop={1}>
          <Text>Press <Text bold>y</Text> to confirm, any other key to cancel</Text>
        </Box>
      </Box>
    );
  }

  // ── Actions sub-screen ──────────────────────────────────────────
  if (subScreen === 'actions') {
    const project = projects[selectedIdx];
    return (
      <Box flexDirection="column" paddingX={1}>
        <Text bold>{project?.concept}</Text>
        <Text color={colors.dim}>{project?.folder}</Text>
        <Box marginTop={1} flexDirection="column">
          <Text><Text bold color={colors.primary}>v</Text> View summary</Text>
          <Text><Text bold color={colors.primary}>r</Text> Resume pipeline</Text>
          <Text><Text bold color="red">d</Text> Delete project</Text>
          <Text><Text bold color={colors.dim}>c</Text> Cancel</Text>
        </Box>
      </Box>
    );
  }

  // ── Main project list ───────────────────────────────────────────
  return (
    <Box flexDirection="column" paddingX={1}>
      <Text bold>Project Workspace</Text>
      <Text color={colors.dim}>Resume or delete existing video projects.</Text>

      {projects.length === 0 ? (
        <Box marginTop={1}>
          <Text color="yellow">No projects found in the workspace yet.</Text>
        </Box>
      ) : (
        <Box flexDirection="column" marginTop={1}>
          {projects.map((p, idx) => {
            const isSelected = idx === selectedIdx;
            const pointer = isSelected ? '▸' : ' ';
            const pct = p.progress_total > 0
              ? Math.round(100 * p.progress_done / p.progress_total)
              : 0;
            const statusText = p.status === 'completed'
              ? '✓ Completed'
              : `${pct}% — ${p.progress_desc}`;
            const statusColor = p.status === 'completed' ? colors.success : 'yellow';

            return (
              <Box key={p.dir}>
                <Text color={isSelected ? colors.primary : colors.dim} bold={isSelected}>
                  {pointer} {String(idx + 1).padStart(2)}.{' '}
                </Text>
                <Text bold={isSelected}>{p.concept}</Text>
                <Text color={colors.dim}>  </Text>
                <Text color={statusColor}>{statusText}</Text>
                <Text color={colors.dim}>  {p.updated_at}</Text>
              </Box>
            );
          })}
        </Box>
      )}

      {placeholderCount > 0 && (
        <Box marginTop={1}>
          <Text color={colors.dim}>
            {placeholderCount} stale entries hidden — press <Text bold>x</Text> to clean
          </Text>
        </Box>
      )}

      {message && (
        <Box marginTop={1}>
          <Text color={colors.success}>{message}</Text>
        </Box>
      )}

      <Box marginTop={1}>
        <Text color={colors.dim}>
          <Text bold>↑↓</Text> navigate  <Text bold>Enter</Text> select  {placeholderCount > 0 && <><Text bold>x</Text> clean  </>}<Text bold>q</Text> back
        </Text>
      </Box>
    </Box>
  );
}
