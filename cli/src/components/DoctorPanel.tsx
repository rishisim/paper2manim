/**
 * DoctorPanel — Diagnoses paper2manim installation.
 * Checks Python, Manim, FFmpeg, API keys, Node.js version, venv.
 */

import React, { useState, useEffect } from 'react';
import { Box, Text, useInput } from 'ink';
import { execSync, spawnSync } from 'node:child_process';
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
    results.push(runCheck('Node.js ≥18', () => {
      const version = process.version;
      const major = parseInt(version.slice(1));
      return { ok: major >= 18, message: version };
    }));

    // Python
    results.push(runCheck('Python', () => {
      const python = process.env['PAPER2MANIM_PYTHON'] ?? 'python3';
      const r = spawnSync(python, ['--version'], { encoding: 'utf8', timeout: 3000 });
      const version = (r.stdout || r.stderr || '').trim();
      return { ok: r.status === 0, message: version || 'Not found' };
    }));

    // Manim
    results.push(runCheck('Manim', () => {
      const python = process.env['PAPER2MANIM_PYTHON'] ?? 'python3';
      const r = spawnSync(python, ['-c', 'import manim; print(manim.__version__)'], {
        encoding: 'utf8', timeout: 5000,
      });
      const version = (r.stdout || '').trim();
      return { ok: r.status === 0, message: version || 'Not installed' };
    }));

    // FFmpeg
    results.push(runCheck('FFmpeg', () => {
      const r = spawnSync('ffmpeg', ['-version'], { encoding: 'utf8', timeout: 3000 });
      const firstLine = (r.stdout || '').split('\n')[0] ?? '';
      return { ok: r.status === 0, message: firstLine || 'Not found' };
    }));

    // LaTeX (for Manim math rendering)
    results.push(runCheck('LaTeX (pdflatex)', () => {
      const r = spawnSync('pdflatex', ['--version'], { encoding: 'utf8', timeout: 3000 });
      const firstLine = (r.stdout || '').split('\n')[0] ?? '';
      return { ok: r.status === 0, message: firstLine.slice(0, 40) || 'Not found' };
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

    // ~/.paper2manim settings dir
    results.push(runCheck('Settings dir (~/.paper2manim)', () => {
      const { existsSync } = require('node:fs');
      const { join } = require('node:path');
      const { homedir } = require('node:os');
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
