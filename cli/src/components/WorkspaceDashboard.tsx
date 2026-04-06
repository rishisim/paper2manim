import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Box, Text, useInput, useApp } from 'ink';
import { execFileSync } from 'node:child_process';
import os from 'node:os';
import { useAppContext } from '../context/AppContext.js';
import { spawnRunner } from '../lib/process.js';
import { formatRelativeDate, formatDuration, renderProgressBar, formatCost } from '../lib/format.js';
import type { Project } from '../lib/types.js';
import { getProjectViewModel } from '../lib/welcome.js';

interface WorkspaceDashboardProps {
  onResume: (concept: string, dir: string) => void;
  onRerun: (concept: string, dir: string) => void;
  onBack: () => void;
}

type SubScreen = 'list' | 'actions' | 'summary' | 'confirm-delete' | 'confirm-cleanup' | 'confirm-rerun';

export function WorkspaceDashboard({ onResume, onRerun, onBack }: WorkspaceDashboardProps) {
  const { exit } = useApp();
  const { themeColors } = useAppContext();
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

  const flashMessage = useCallback((text: string) => {
    setMessage(text);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setMessage(''), 2000);
  }, []);

  const openVideo = useCallback((videoPath: string) => {
    try {
      const platform = os.platform();
      if (platform === 'darwin') {
        execFileSync('open', [videoPath]);
      } else if (platform === 'win32') {
        execFileSync('cmd', ['/c', 'start', '', videoPath]);
      } else {
        execFileSync('xdg-open', [videoPath]);
      }
      flashMessage('Opening video...');
    } catch {
      flashMessage('Could not open video player.');
    }
  }, [flashMessage]);

  const runPrimaryAction = useCallback((project: Project) => {
    const vm = getProjectViewModel(project);
    switch (vm.primaryAction) {
      case 'resume':
        onResume(project.concept, project.dir);
        break;
      case 'rerun':
        onRerun(project.concept, project.dir);
        break;
      case 'open_video':
        if (project.has_video && project.video_path) {
          openVideo(project.video_path);
        } else {
          setSubScreen('actions');
        }
        break;
      case 'view_summary':
        viewSummary(project.dir);
        break;
      default:
        setSubScreen('actions');
    }
  }, [onResume, onRerun, openVideo, viewSummary]);

  useInput((input, key) => {
    if (subScreen === 'list') {
      if (key.upArrow) {
        setSelectedIdx(prev => Math.max(0, prev - 1));
      } else if (key.downArrow) {
        setSelectedIdx(prev => Math.max(0, Math.min(projects.length - 1, prev + 1)));
      } else if (key.return && projects.length > 0) {
        const project = projects[selectedIdx];
        if (project) runPrimaryAction(project);
      } else if (input === 'a' && projects.length > 0) {
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
      } else if (input === 'n') {
        setSubScreen('confirm-rerun');
      } else if (input === 'o' && project.has_video && project.video_path) {
        openVideo(project.video_path);
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
    } else if (subScreen === 'confirm-rerun') {
      const project = projects[selectedIdx];
      if (input === 'y' && project) {
        onRerun(project.concept, project.dir);
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
        <Text color={themeColors.dim}>Loading projects...</Text>
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
          <Text color={themeColors.dim}>Press <Text bold>Enter</Text> to go back</Text>
        </Box>
      </Box>
    );
  }

  // ── Confirm delete ──────────────────────────────────────────────
  if (subScreen === 'confirm-delete') {
    const project = projects[selectedIdx];
    return (
      <Box flexDirection="column" paddingX={1}>
        <Text color={themeColors.error} bold>Delete project "{project?.concept}"?</Text>
        <Text color={themeColors.dim}>This will permanently remove all files.</Text>
        <Box marginTop={1}>
          <Text>Press <Text bold>y</Text> to confirm, any other key to cancel</Text>
        </Box>
      </Box>
    );
  }

  // ── Confirm re-run ──────────────────────────────────────────────
  if (subScreen === 'confirm-rerun') {
    const project = projects[selectedIdx];
    return (
      <Box flexDirection="column" paddingX={1}>
        <Text color={themeColors.warn} bold>Re-run "{project?.concept}" from scratch?</Text>
        <Text color={themeColors.dim}>This will discard cached stages and restart the full pipeline.</Text>
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
        <Text color={themeColors.warn} bold>Clean {placeholderCount} stale workspace entries?</Text>
        <Box marginTop={1}>
          <Text>Press <Text bold>y</Text> to confirm, any other key to cancel</Text>
        </Box>
      </Box>
    );
  }

  // ── Actions sub-screen ──────────────────────────────────────────
  if (subScreen === 'actions') {
    const project = projects[selectedIdx];
    const relDate = formatRelativeDate(project?.updated_at ?? '');
    const vm = project ? getProjectViewModel(project) : null;
    return (
      <Box flexDirection="column" paddingX={1}>
        <Text bold>{project?.concept}</Text>
        <Text color={themeColors.dim}>{project?.folder}  </Text>
        {vm && <Text color={vm.statusTone === 'success' ? themeColors.success : vm.statusTone === 'error' ? themeColors.error : themeColors.warn}>[{vm.statusLabel}]</Text>}

        {/* Detail metadata */}
        <Box marginTop={1} flexDirection="column">
          {(project?.total_segments ?? 0) > 0 && (
            <Text color={themeColors.muted}>  Segments   {project!.total_segments}</Text>
          )}
          {project?.total_time_secs != null && (
            <Text color={themeColors.muted}>  Duration   {formatDuration(project.total_time_secs)}</Text>
          )}
          {project?.estimated_cost_usd != null && project.estimated_cost_usd > 0 && (
            <Text color={themeColors.muted}>  Est. cost  <Text color={themeColors.warn}>{formatCost(project.estimated_cost_usd)}</Text></Text>
          )}
          {project?.has_video && (
            <Text color={themeColors.muted}>  Video      <Text color={themeColors.success}>{project.video_size_mb != null ? `${project.video_size_mb} MB` : 'available'}</Text></Text>
          )}
          <Text color={themeColors.muted}>  Updated    {relDate}</Text>
        </Box>

        {/* Actions */}
        <Box marginTop={1} flexDirection="column">
          <Text><Text bold color={themeColors.primary}>v</Text> View summary</Text>
          <Text><Text bold color={themeColors.primary}>r</Text> Resume pipeline</Text>
          {project?.has_video && project.video_path && (
            <Text><Text bold color={themeColors.primary}>o</Text> Open video</Text>
          )}
        </Box>
        <Box marginTop={1} flexDirection="column">
          <Text color={themeColors.warn}>Recovery</Text>
          <Text><Text bold color={themeColors.warn}>n</Text> Re-run from scratch</Text>
        </Box>
        <Box marginTop={1} flexDirection="column">
          <Text color={themeColors.error}>Danger zone</Text>
          <Text><Text bold color={themeColors.error}>d</Text> Delete project</Text>
          <Text><Text bold color={themeColors.dim}>c</Text> Cancel</Text>
        </Box>
      </Box>
    );
  }

  // ── Main project list ───────────────────────────────────────────
  return (
    <Box flexDirection="column" paddingX={1}>
      <Text bold>Project Workspace</Text>
      <Text color={themeColors.dim}>Resume, re-run, or manage existing video projects.</Text>

      {projects.length === 0 ? (
        <Box marginTop={1}>
          <Text color={themeColors.warn}>No projects found in the workspace yet.</Text>
        </Box>
      ) : (
        <Box flexDirection="column" marginTop={1}>
          {projects.map((p, idx) => {
            const isSelected = idx === selectedIdx;
            const pct = p.progress_total > 0
              ? Math.round(100 * p.progress_done / p.progress_total)
              : 0;
            const vm = getProjectViewModel(p);
            const isCompleted = vm.badge === 'completed';
            const statusColor = vm.statusTone === 'success'
              ? themeColors.success
              : vm.statusTone === 'error'
                ? themeColors.error
                : themeColors.warn;
            const relDate = formatRelativeDate(p.updated_at);

            // Build metadata line
            const metaParts: string[] = [];
            const segments = p.total_segments ?? 0;
            if (segments > 0) metaParts.push(`${segments} seg${segments !== 1 ? 's' : ''}`);
            if (p.total_time_secs != null) metaParts.push(formatDuration(p.total_time_secs));
            if (p.estimated_cost_usd != null && p.estimated_cost_usd > 0) metaParts.push(formatCost(p.estimated_cost_usd));
            if (p.has_video && p.video_size_mb != null) metaParts.push(`${p.video_size_mb} MB`);

            return (
              <Box key={p.dir} flexDirection="column">
                {/* Line 1: selector + concept + status + date */}
                <Box>
                  <Text color={isSelected ? themeColors.primary : themeColors.dim} bold={isSelected}>
                    {isSelected ? '\u276F' : ' '} {String(idx + 1).padStart(2)}.{' '}
                  </Text>
                  <Text bold={isSelected}>{p.concept}</Text>
                  <Text color={themeColors.dim}>  </Text>
                  <Text color={statusColor}>[{vm.statusLabel}]</Text>
                  <Text color={themeColors.dim}>  {vm.primaryActionLabel}</Text>
                  <Text color={themeColors.dim}>  {relDate}</Text>
                </Box>
                {/* Line 2: progress bar or metadata */}
                <Box paddingLeft={6}>
                  {!isCompleted && pct > 0 && pct < 100 ? (
                    <Text>
                      <Text color={themeColors.progressFill}>{renderProgressBar(pct, 12)}</Text>
                      <Text color={themeColors.dim}>{segments > 0 ? ` ${segments} segments` : ''}  {vm.secondaryText}</Text>
                    </Text>
                  ) : metaParts.length > 0 ? (
                    <Text color={themeColors.dim}>{vm.secondaryText}  {metaParts.join(' \u00B7 ')}</Text>
                  ) : null}
                </Box>
              </Box>
            );
          })}
        </Box>
      )}

      {placeholderCount > 0 && (
        <Box marginTop={1}>
          <Text color={themeColors.dim}>
            {placeholderCount} stale entries hidden — press <Text bold>x</Text> to clean
          </Text>
        </Box>
      )}

      {message && (
        <Box marginTop={1}>
          <Text color={themeColors.success}>{message}</Text>
        </Box>
      )}

      <Box marginTop={1}>
        <Text color={themeColors.dim}>
          <Text bold>{'\u2191\u2193'}</Text> navigate  <Text bold>Enter</Text> run suggested action  <Text bold>a</Text> all actions  {placeholderCount > 0 && <><Text bold>x</Text> clean  </>}<Text bold>q</Text> back
        </Text>
      </Box>
    </Box>
  );
}
