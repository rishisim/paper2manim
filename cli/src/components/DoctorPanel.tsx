/**
 * DoctorPanel — Diagnoses paper2manim installation.
 * Checks Python, Manim, FFmpeg, API keys, Node.js version, venv.
 */

import React, { useState, useEffect } from 'react';
import { Box, Text, useInput } from 'ink';
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { homedir } from 'node:os';
import { useAppContext } from '../context/AppContext.js';

interface CheckResult {
  name: string;
  status: 'ok' | 'fail' | 'warn' | 'checking';
  message: string;
}

interface DoctorPanelProps {
  onBack: () => void;
}

function runCheck(name: string, fn: () => { ok: boolean; message: string }): CheckResult {
  try {
    const result = fn();
    return { name, status: result.ok ? 'ok' : 'fail', message: result.message };
  } catch (e: unknown) {
    return { name, status: 'fail', message: String(e instanceof Error ? e.message : e) };
  }
}

export function DoctorPanel({ onBack }: DoctorPanelProps) {
  const { themeColors } = useAppContext();
  const [checks, setChecks] = useState<CheckResult[]>([]);
  const [done, setDone] = useState(false);

  useEffect(() => {
    const results: CheckResult[] = [];

    // Node.js version
    // M8: Use process.versions.node (always numeric, no 'v' prefix) instead of process.version.slice(1)
    results.push(runCheck('Node.js ≥18', () => {
      const nodeVer = process.versions.node;
      const major = parseInt(nodeVer.split('.')[0] ?? '0', 10);
      return { ok: major >= 18, message: `v${nodeVer}` };
    }));

    // M7: Helper — spawnSync with timeout, treating timed-out processes (status===null, error set) as failures
    const syncCheck = (cmd: string, args: string[], timeoutMs = 5000): { ok: boolean; out: string } => {
      const r = spawnSync(cmd, args, { encoding: 'utf8', timeout: timeoutMs, stdio: 'pipe' });
      const ok = r.status === 0 && r.error == null;
      const out = ((r.stdout || '') + (r.stderr || '')).trim();
      return { ok, out: out || (r.error ? String(r.error.message) : 'Not found') };
    };

    // Python
    results.push(runCheck('Python', () => {
      const python = process.env['PAPER2MANIM_PYTHON'] ?? 'python3';
      const { ok, out } = syncCheck(python, ['--version']);
      return { ok, message: out };
    }));

    // Manim
    results.push(runCheck('Manim', () => {
      const python = process.env['PAPER2MANIM_PYTHON'] ?? 'python3';
      const { ok, out } = syncCheck(python, ['-c', 'import manim; print(manim.__version__)']);
      return { ok, message: ok ? out : 'Not installed — run: pip install manim' };
    }));

    // FFmpeg
    results.push(runCheck('FFmpeg', () => {
      const { ok, out } = syncCheck('ffmpeg', ['-version']);
      const firstLine = out.split('\n')[0] ?? '';
      return { ok, message: firstLine || 'Not found' };
    }));

    // LaTeX (for Manim math rendering)
    results.push(runCheck('LaTeX (pdflatex)', () => {
      const { ok, out } = syncCheck('pdflatex', ['--version']);
      const firstLine = out.split('\n')[0] ?? '';
      return { ok, message: (firstLine.slice(0, 40) || 'Not found') + (ok ? '' : ' (optional)') };
    }));

    // ANTHROPIC_API_KEY
    results.push(runCheck('ANTHROPIC_API_KEY', () => {
      const key = process.env['ANTHROPIC_API_KEY'];
      return {
        ok: !!key,
        message: key ? `${key.slice(0, 8)}...${key.slice(-4)}` : 'Not set',
      };
    }));

    // GEMINI_API_KEY
    results.push(runCheck('GEMINI_API_KEY', () => {
      const key = process.env['GEMINI_API_KEY'] ?? process.env['GOOGLE_API_KEY'];
      return {
        ok: !!key,
        message: key ? `${key.slice(0, 8)}...${key.slice(-4)}` : 'Not set',
      };
    }));

    // ~/.paper2manim settings dir — M6: use top-level ESM imports (not require)
    results.push(runCheck('Settings dir (~/.paper2manim)', () => {
      const dir = join(homedir(), '.paper2manim');
      return { ok: existsSync(dir), message: existsSync(dir) ? dir : 'Not created yet' };
    }));

    setChecks(results);
    setDone(true);
  }, []);

  useInput((_input, key) => {
    if (key.escape || _input === 'q') onBack();
  });

  const statusIcon = (status: CheckResult['status']) => {
    switch (status) {
      case 'ok': return '✓';
      case 'fail': return '✗';
      case 'warn': return '⚠';
      case 'checking': return '…';
    }
  };

  const statusColor = (status: CheckResult['status']) => {
    switch (status) {
      case 'ok': return themeColors.success;
      case 'fail': return themeColors.error;
      case 'warn': return themeColors.warn;
      case 'checking': return themeColors.dim;
    }
  };

  return (
    <Box flexDirection="column" paddingX={1}>
      <Text bold color={themeColors.primary}>Doctor — Installation Diagnostics</Text>
      <Text color={themeColors.dim}>Checking your paper2manim environment…</Text>
      <Box marginTop={1} flexDirection="column">
        {checks.map(check => (
          <Box key={check.name}>
            <Text color={statusColor(check.status)} bold>{statusIcon(check.status)}</Text>
            <Text color={themeColors.text}>{' '}{check.name.padEnd(30)}</Text>
            <Text color={themeColors.dim}>{check.message}</Text>
          </Box>
        ))}
        {!done && <Text color={themeColors.dim}>  Checking…</Text>}
      </Box>
      {done && (
        <Box marginTop={1}>
          <Text color={themeColors.dim}>
            {checks.filter(c => c.status === 'ok').length}/{checks.length} checks passed · Press Esc to go back
          </Text>
        </Box>
      )}
    </Box>
  );
}
