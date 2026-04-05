#!/usr/bin/env node
/**
 * paper2manim MCP Server
 *
 * Gives Claude Code direct access to:
 *   - Workspace browsing (list/inspect projects)
 *   - Pipeline execution (run concepts, stream progress)
 *   - Environment diagnostics (doctor checks)
 *   - CLI slash-command introspection
 *   - Output file inspection (videos, code, storyboards)
 *   - Test suite execution, linting, and code formatting
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { spawn, execSync } from "node:child_process";
import { readFileSync, readdirSync, existsSync, statSync } from "node:fs";
import { join, resolve, basename } from "node:path";

// ── Resolve project root ────────────────────────────────────────────────────
const PROJECT_ROOT = resolve(
  process.env.PAPER2MANIM_ROOT ||
    new URL("..", import.meta.url).pathname
);
const OUTPUT_DIR = join(PROJECT_ROOT, "output");
const PYTHON =
  process.env.PAPER2MANIM_PYTHON ||
  process.env.PYTHON ||
  "python3";

// ── Helpers ─────────────────────────────────────────────────────────────────

/** Run the pipeline_runner.py with given JSON args and collect NDJSON output. */
function runPipelineRunner(args, { timeoutMs = 300_000 } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(
      PYTHON,
      [join(PROJECT_ROOT, "pipeline_runner.py"), JSON.stringify(args)],
      { cwd: PROJECT_ROOT, stdio: ["pipe", "pipe", "pipe"] }
    );

    const lines = [];
    let stderr = "";

    child.stdout.on("data", (chunk) => {
      const text = chunk.toString();
      for (const line of text.split("\n")) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        try {
          lines.push(JSON.parse(trimmed));
        } catch {
          lines.push({ type: "raw", text: trimmed });
        }
      }
    });

    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });

    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      reject(new Error(`Pipeline timed out after ${timeoutMs}ms`));
    }, timeoutMs);

    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({ exitCode: code, messages: lines, stderr: stderr.slice(0, 2000) });
    });

    child.on("error", (err) => {
      clearTimeout(timer);
      reject(err);
    });

    // If we need to send answers to questionnaire, auto-answer with defaults
    if (args.questionnaire_answers) {
      // Already provided, no stdin needed
    }
  });
}

/** Run a shell command and return stdout. */
function runCommand(cmd, { timeoutMs = 15_000, cwd = PROJECT_ROOT } = {}) {
  try {
    return execSync(cmd, {
      cwd,
      timeout: timeoutMs,
      encoding: "utf-8",
      stdio: ["pipe", "pipe", "pipe"],
    }).trim();
  } catch (e) {
    return `Error: ${e.message}`;
  }
}

/** Spawn a command and collect stdout+stderr with a timeout. Returns { exitCode, stdout, stderr }. */
function spawnWithTimeout(cmd, args, { timeoutMs = 60_000, cwd = PROJECT_ROOT } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, {
      cwd,
      stdio: ["pipe", "pipe", "pipe"],
      env: { ...process.env },
    });

    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk) => { stdout += chunk.toString(); });
    child.stderr.on("data", (chunk) => { stderr += chunk.toString(); });

    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      reject(new Error(`Command timed out after ${timeoutMs}ms`));
    }, timeoutMs);

    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({ exitCode: code, stdout, stderr });
    });

    child.on("error", (err) => {
      clearTimeout(timer);
      reject(err);
    });
  });
}

/** Truncate a string to maxLen, appending a note if truncated. */
function truncate(str, maxLen = 8_000) {
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen) + `\n\n... [truncated at ${maxLen} chars]`;
}

/** List project directories in output/. */
function listProjects() {
  if (!existsSync(OUTPUT_DIR)) return [];
  return readdirSync(OUTPUT_DIR)
    .filter((d) => {
      const full = join(OUTPUT_DIR, d);
      return statSync(full).isDirectory();
    })
    .map((d) => {
      const full = join(OUTPUT_DIR, d);
      const statePath = join(full, "project_state.json");
      let state = {};
      if (existsSync(statePath)) {
        try {
          state = JSON.parse(readFileSync(statePath, "utf-8"));
        } catch {}
      }
      const summaryPath = join(full, "pipeline_summary.txt");
      const hasSummary = existsSync(summaryPath);
      // Pipeline saves final video as {slug}.mp4 — derive from state or scan for .mp4
      const slug = state.slug || "";
      let hasVideo = false;
      if (slug) {
        hasVideo = existsSync(join(full, `${slug}.mp4`));
      }
      if (!hasVideo) {
        // Fallback: check for any .mp4 directly in the project dir (not in segment_* subdirs)
        try {
          hasVideo = readdirSync(full).some(
            (f) => f.endsWith(".mp4") && !f.includes("stitched") && statSync(join(full, f)).isFile()
          );
        } catch {}
      }
      return {
        folder: d,
        path: full,
        concept: state.concept || d.replace(/_/g, " "),
        status: state.status || "unknown",
        updated_at: state.updated_at || null,
        stages_done: state.stages
          ? Object.entries(state.stages)
              .filter(([, v]) => v && v.done)
              .map(([k]) => k)
          : [],
        total_segments: state.total_segments || 0,
        has_summary: hasSummary,
        has_video: hasVideo,
      };
    });
}

/** Read a text file safely, truncated to maxLen. */
function readFileSafe(path, maxLen = 10_000) {
  if (!existsSync(path)) return null;
  const content = readFileSync(path, "utf-8");
  if (content.length > maxLen) {
    return content.slice(0, maxLen) + `\n\n... [truncated at ${maxLen} chars]`;
  }
  return content;
}

// ── MCP Server Setup ────────────────────────────────────────────────────────

const server = new McpServer({
  name: "paper2manim",
  version: "0.1.0",
});

// ── Tool: list_projects ─────────────────────────────────────────────────────

server.tool(
  "list_projects",
  "List all paper2manim projects in the output/ directory with their status, stages completed, and whether they have a final video.",
  {},
  async () => {
    const projects = listProjects();
    if (projects.length === 0) {
      return { content: [{ type: "text", text: "No projects found in output/." }] };
    }
    const summary = projects.map((p) => {
      const status = p.has_video ? "✓ has video" : p.status;
      const stages = p.stages_done.length > 0 ? p.stages_done.join(" → ") : "—";
      const segs = p.total_segments ? `${p.total_segments} segments` : "";
      const parts = [`  Concept: ${p.concept}`, `  Status: ${status}`];
      if (segs) parts.push(`  Segments: ${segs}`);
      if (p.stages_done.length > 0) parts.push(`  Stages: ${stages}`);
      parts.push(`  Video: ${p.has_video ? "yes" : "no"} | Summary: ${p.has_summary ? "yes" : "no"}`);
      return `${p.folder}\n${parts.join("\n")}`;
    });
    return {
      content: [{ type: "text", text: `Found ${projects.length} project(s):\n\n${summary.join("\n\n")}` }],
    };
  }
);

// ── Tool: inspect_project ───────────────────────────────────────────────────

server.tool(
  "inspect_project",
  "Inspect a specific project: view its storyboard, generated Manim code, pipeline summary, project state, and file listing.",
  { folder: z.string().describe("Project folder name (e.g. 'fourier_transform_4976')") },
  async ({ folder }) => {
    const projectDir = join(OUTPUT_DIR, folder);
    if (!existsSync(projectDir)) {
      return { content: [{ type: "text", text: `Project not found: ${folder}` }] };
    }

    const parts = [];

    // Project state
    const state = readFileSafe(join(projectDir, "project_state.json"), 3000);
    if (state) parts.push(`── Project State ──\n${state}`);

    // Pipeline summary
    const summary = readFileSafe(join(projectDir, "pipeline_summary.txt"), 5000);
    if (summary) parts.push(`── Pipeline Summary ──\n${summary}`);

    // Storyboard
    const storyboard = readFileSafe(join(projectDir, "storyboard.json"), 5000);
    if (storyboard) parts.push(`── Storyboard ──\n${storyboard}`);

    // List all files
    const files = readdirSync(projectDir).map((f) => {
      const s = statSync(join(projectDir, f));
      const size = s.isDirectory() ? "dir" : `${(s.size / 1024).toFixed(1)}KB`;
      return `  ${f} (${size})`;
    });
    parts.push(`── Files ──\n${files.join("\n")}`);

    // Show generated Manim code for up to 3 segments (stored in segment_N/segment_N.py)
    const segDirs = readdirSync(projectDir)
      .filter((f) => f.match(/^segment_\d+$/) && statSync(join(projectDir, f)).isDirectory())
      .sort((a, b) => {
        const na = parseInt(a.replace("segment_", ""));
        const nb = parseInt(b.replace("segment_", ""));
        return na - nb;
      })
      .slice(0, 3);
    for (const segDir of segDirs) {
      const pyFile = join(projectDir, segDir, `${segDir}.py`);
      if (existsSync(pyFile)) {
        const code = readFileSafe(pyFile, 3000);
        if (code) parts.push(`── ${segDir}/${segDir}.py ──\n${code}`);
      }
    }

    return { content: [{ type: "text", text: parts.join("\n\n") }] };
  }
);

// ── Tool: read_project_file ─────────────────────────────────────────────────

server.tool(
  "read_project_file",
  "Read any file from a project directory (code, storyboard, summary, logs, etc.).",
  {
    folder: z.string().describe("Project folder name"),
    filename: z.string().describe("File to read (e.g. 'segment_1/segment_1.py', 'storyboard.json', 'pipeline_summary.txt')"),
  },
  async ({ folder, filename }) => {
    const filePath = join(OUTPUT_DIR, folder, filename);
    // Prevent path traversal
    if (!resolve(filePath).startsWith(resolve(OUTPUT_DIR))) {
      return { content: [{ type: "text", text: "Access denied: path traversal detected." }] };
    }
    const content = readFileSafe(filePath, 30_000);
    if (content === null) {
      return { content: [{ type: "text", text: `File not found: ${folder}/${filename}` }] };
    }
    return { content: [{ type: "text", text: content }] };
  }
);

// ── Tool: run_doctor ────────────────────────────────────────────────────────

server.tool(
  "run_doctor",
  "Run environment diagnostics: check Python, Node.js, Manim, FFmpeg, LaTeX, API keys, and venv status.",
  {},
  async () => {
    const checks = [];

    // Python
    const pyVersion = runCommand(`${PYTHON} --version`);
    checks.push(`Python: ${pyVersion}`);

    // Node
    const nodeVersion = runCommand("node --version");
    checks.push(`Node.js: ${nodeVersion}`);

    // Manim
    const manimVersion = runCommand(`${PYTHON} -c "import manim; print(manim.__version__)"`, { timeoutMs: 10_000 });
    checks.push(`Manim: ${manimVersion}`);

    // FFmpeg
    const ffmpeg = runCommand("ffmpeg -version 2>&1 | head -1");
    checks.push(`FFmpeg: ${ffmpeg}`);

    // LaTeX
    const latex = runCommand("pdflatex --version 2>&1 | head -1");
    checks.push(`LaTeX: ${latex}`);

    // API keys
    const hasAnthropic = !!process.env.ANTHROPIC_API_KEY;
    const hasGemini = !!process.env.GEMINI_API_KEY;
    checks.push(`ANTHROPIC_API_KEY: ${hasAnthropic ? "set" : "MISSING"}`);
    checks.push(`GEMINI_API_KEY: ${hasGemini ? "set" : "MISSING"}`);

    // Virtual env
    const venv = process.env.VIRTUAL_ENV || "none";
    checks.push(`Virtual env: ${venv}`);

    // CLI build
    const cliBuilt = existsSync(join(PROJECT_ROOT, "cli", "dist", "cli.js"));
    checks.push(`CLI built: ${cliBuilt ? "yes" : "no (run: cd cli && npm run build)"}`);

    // Output dir
    const projectCount = listProjects().length;
    checks.push(`Output projects: ${projectCount}`);

    return { content: [{ type: "text", text: `paper2manim Doctor\n${"─".repeat(40)}\n${checks.join("\n")}` }] };
  }
);

// ── Tool: run_pipeline ──────────────────────────────────────────────────────

server.tool(
  "run_pipeline",
  "Run the full paper2manim pipeline for a concept. Returns all pipeline updates (plan, TTS, code, render, concat stages). This is a long-running operation.",
  {
    concept: z.string().describe("The concept to generate a video for (e.g. 'fourier transform')"),
    video_length: z.enum(["Short (1-2 min)", "Medium (3-5 min)", "Long (5-10 min)"]).default("Medium (3-5 min)").describe("Video length"),
    target_audience: z.enum(["High school student", "Undergraduate", "Graduate / Professional", "General audience"]).default("Undergraduate").describe("Target audience"),
    visual_style: z.enum(["Geometric intuition", "Step-by-step derivation", "Real-world applications", "Let the AI decide"]).default("Let the AI decide").describe("Visual approach"),
    skip_audio: z.boolean().default(false).describe("Skip TTS audio generation"),
    is_lite: z.boolean().default(false).describe("Use lite planner (Gemini) instead of pro (Claude)"),
    max_retries: z.number().default(3).describe("Max retries per segment"),
  },
  async ({ concept, video_length, target_audience, visual_style, skip_audio, is_lite, max_retries }) => {
    const args = {
      concept,
      max_retries,
      is_lite,
      skip_audio,
      questionnaire_answers: {
        video_length,
        target_audience,
        visual_style,
        pacing: "Balanced",
      },
    };

    try {
      const result = await runPipelineRunner(args, { timeoutMs: 600_000 });

      // Summarize the NDJSON messages
      const stages = [];
      let finalVideo = null;
      let error = null;
      const updates = result.messages.filter((m) => m.type === "pipeline");

      for (const msg of result.messages) {
        if (msg.type === "pipeline" && msg.update) {
          const u = msg.update;
          if (u.final && u.video_path) finalVideo = u.video_path;
          if (u.error) error = u.error;
          if (u.stage && u.status) {
            stages.push(`[${u.stage}] ${u.status}`);
          }
        } else if (msg.type === "error") {
          error = msg.message;
        }
      }

      const summary = [
        `Pipeline completed (exit code: ${result.exitCode})`,
        `Total updates: ${updates.length}`,
        finalVideo ? `Final video: ${finalVideo}` : "No final video produced",
        error ? `Error: ${error}` : null,
        "",
        "── Stage Log ──",
        ...stages.slice(-30), // Last 30 updates
      ]
        .filter(Boolean)
        .join("\n");

      if (result.stderr) {
        return {
          content: [{ type: "text", text: summary + `\n\n── Stderr (last 2000 chars) ──\n${result.stderr}` }],
        };
      }
      return { content: [{ type: "text", text: summary }] };
    } catch (e) {
      return { content: [{ type: "text", text: `Pipeline failed: ${e.message}` }] };
    }
  }
);

// ── Tool: run_plan_only ─────────────────────────────────────────────────────

server.tool(
  "run_plan_only",
  "Run ONLY the planning stage for a concept (no TTS, no code gen, no rendering). Returns the storyboard JSON. Fast and cheap — good for previewing what the pipeline would produce.",
  {
    concept: z.string().describe("The concept to plan a video for"),
    is_lite: z.boolean().default(false).describe("Use lite planner (Gemini) instead of pro (Claude)"),
  },
  async ({ concept, is_lite }) => {
    // We run the planner directly via Python
    const script = `
import json, sys, os
sys.path.insert(0, ${JSON.stringify(PROJECT_ROOT)})
${is_lite
      ? `from agents.planner import plan_segmented_storyboard_lite
result = plan_segmented_storyboard_lite(${JSON.stringify(concept)}, {"video_length": "Medium (3-5 min)", "target_audience": "Undergraduate", "visual_style": "Let the AI decide", "pacing": "Balanced"})`
      : `from agents.planner_math2manim import run_math2manim_planner
result = run_math2manim_planner(${JSON.stringify(concept)}, {"video_length": "Medium (3-5 min)", "target_audience": "Undergraduate", "visual_style": "Let the AI decide", "pacing": "Balanced"})`}
print(json.dumps(result, indent=2, default=str))
`;

    try {
      const output = runCommand(`${PYTHON} -c ${JSON.stringify(script)}`, {
        timeoutMs: 120_000,
      });
      return { content: [{ type: "text", text: `Storyboard for "${concept}":\n\n${output}` }] };
    } catch (e) {
      return { content: [{ type: "text", text: `Planning failed: ${e.message}` }] };
    }
  }
);

// ── Tool: test_manim_code ───────────────────────────────────────────────────

server.tool(
  "test_manim_code",
  "Test-render a Manim script. Writes the code to a temp file and runs `manim render` on it. Returns success/failure and any error output.",
  {
    code: z.string().describe("Manim Python code to test"),
    quality: z.enum(["low", "medium", "high"]).default("low").describe("Render quality (low is fastest for testing)"),
  },
  async ({ code, quality }) => {
    const qualityFlag = { low: "-ql", medium: "-qm", high: "-qh" }[quality];
    const tmpFile = join(PROJECT_ROOT, ".mcp_test_scene.py");

    const { writeFileSync, unlinkSync } = await import("node:fs");
    writeFileSync(tmpFile, code);

    try {
      const result = runCommand(
        `${PYTHON} -m manim render ${qualityFlag} --disable_caching "${tmpFile}" 2>&1`,
        { timeoutMs: 120_000 }
      );
      return {
        content: [{ type: "text", text: `Manim render result:\n\n${result}` }],
      };
    } catch (e) {
      return { content: [{ type: "text", text: `Render failed: ${e.message}` }] };
    } finally {
      try { unlinkSync(tmpFile); } catch {}
    }
  }
);

// ── Tool: list_slash_commands ────────────────────────────────────────────────

server.tool(
  "list_slash_commands",
  "List all slash commands available in the paper2manim CLI, grouped by category.",
  {},
  async () => {
    // Parse commands.ts to extract command definitions
    const commandsPath = join(PROJECT_ROOT, "cli", "src", "lib", "commands.ts");
    if (!existsSync(commandsPath)) {
      return { content: [{ type: "text", text: "commands.ts not found — CLI source not available." }] };
    }
    const source = readFileSync(commandsPath, "utf-8");

    // Extract command blocks
    const commands = [];
    const regex = /name:\s*'([^']+)'.*?aliases:\s*\[([^\]]*)\].*?description:\s*'([^']*)'.*?category:\s*'([^']*)'/gs;
    let match;
    while ((match = regex.exec(source)) !== null) {
      commands.push({
        name: match[1],
        aliases: match[2].replace(/'/g, "").split(",").map((s) => s.trim()).filter(Boolean),
        description: match[3],
        category: match[4],
      });
    }

    if (commands.length === 0) {
      return { content: [{ type: "text", text: "Could not parse commands from commands.ts." }] };
    }

    // Group by category
    const byCategory = {};
    for (const cmd of commands) {
      (byCategory[cmd.category] ||= []).push(cmd);
    }

    const lines = [];
    for (const [cat, cmds] of Object.entries(byCategory)) {
      lines.push(`\n── ${cat.toUpperCase()} ──`);
      for (const cmd of cmds) {
        const aliases = cmd.aliases.length > 0 ? ` (${cmd.aliases.join(", ")})` : "";
        lines.push(`  /${cmd.name}${aliases} — ${cmd.description}`);
      }
    }

    return {
      content: [{ type: "text", text: `paper2manim Slash Commands (${commands.length} total)\n${lines.join("\n")}` }],
    };
  }
);

// ── Tool: get_pipeline_config ───────────────────────────────────────────────

server.tool(
  "get_pipeline_config",
  "Show current pipeline configuration: models, timeouts, tool budgets, environment overrides, and settings.",
  {},
  async () => {
    const parts = [];

    // Models
    parts.push("── Models ──");
    parts.push(`  Planning (Pro): claude-opus-4-6`);
    parts.push(`  Planning (Lite): gemini-3.1-pro-preview`);
    parts.push(`  Code gen: claude-opus-4-6 (complex) / claude-sonnet-4-6 (simple)`);
    parts.push(`  TTS: gemini-2.5-flash-preview-tts`);
    parts.push(`  Model override: ${process.env.PAPER2MANIM_MODEL_OVERRIDE || "none"}`);
    parts.push(`  Max turns: ${process.env.PAPER2MANIM_MAX_TURNS || "default"}`);

    // Settings file
    const settingsPath = join(
      process.env.HOME || "",
      ".paper2manim",
      "settings.json"
    );
    if (existsSync(settingsPath)) {
      const settings = readFileSafe(settingsPath, 2000);
      parts.push(`\n── User Settings (~/.paper2manim/settings.json) ──\n${settings}`);
    } else {
      parts.push("\n── User Settings ──\n  No settings file found.");
    }

    // .env check
    const envPath = join(PROJECT_ROOT, ".env");
    if (existsSync(envPath)) {
      parts.push("\n── .env ──\n  Present (keys redacted)");
    }

    return { content: [{ type: "text", text: parts.join("\n") }] };
  }
);

// ── Tool: search_projects ───────────────────────────────────────────────────

server.tool(
  "search_projects",
  "Search across all projects for a pattern in generated code, storyboards, or summaries.",
  {
    pattern: z.string().describe("Text pattern to search for (case-insensitive)"),
    file_type: z.enum(["code", "storyboard", "summary", "all"]).default("all").describe("Which files to search"),
  },
  async ({ pattern, file_type }) => {
    const projects = listProjects();
    const regex = new RegExp(pattern, "gi");
    const results = [];

    for (const project of projects) {
      const files = readdirSync(project.path);
      for (const file of files) {
        const isCode = file.endsWith(".py");
        const isStoryboard = file === "storyboard.json";
        const isSummary = file === "pipeline_summary.txt";

        if (file_type === "code" && !isCode) continue;
        if (file_type === "storyboard" && !isStoryboard) continue;
        if (file_type === "summary" && !isSummary) continue;
        if (file_type === "all" && !isCode && !isStoryboard && !isSummary) continue;

        const content = readFileSafe(join(project.path, file), 20_000);
        if (!content) continue;

        const matches = content.match(regex);
        if (matches) {
          // Show context around first match
          const idx = content.search(regex);
          const start = Math.max(0, idx - 100);
          const end = Math.min(content.length, idx + 200);
          const snippet = content.slice(start, end);
          results.push(
            `${project.folder}/${file} (${matches.length} matches)\n  ...${snippet}...`
          );
        }
      }
    }

    if (results.length === 0) {
      return { content: [{ type: "text", text: `No matches for "${pattern}" in ${file_type} files.` }] };
    }
    return {
      content: [{ type: "text", text: `Found matches in ${results.length} file(s):\n\n${results.join("\n\n")}` }],
    };
  }
);

// ── Tool: run_tests ─────────────────────────────────────────────────────────

server.tool(
  "run_tests",
  "Run the project test suite. Supports Python (pytest) and TypeScript (tsc type-check). Returns pass/fail status and output.",
  {
    scope: z.enum(["all", "python", "typescript"]).default("all").describe("Which tests to run: all, python, or typescript"),
  },
  async ({ scope }) => {
    const results = [];

    // Python tests via pytest
    if (scope === "all" || scope === "python") {
      try {
        const py = await spawnWithTimeout(
          PYTHON,
          ["-m", "pytest", "tests/", "-x", "-v", "--tb=short"],
          { timeoutMs: 60_000 }
        );
        const passed = py.exitCode === 0;
        results.push(
          `── Python Tests (pytest) ── ${passed ? "PASSED" : "FAILED"}\n` +
          `Exit code: ${py.exitCode}\n\n` +
          truncate(py.stdout + (py.stderr ? `\nStderr:\n${py.stderr}` : ""))
        );
      } catch (e) {
        results.push(`── Python Tests ── ERROR\n${e.message}`);
      }
    }

    // TypeScript type-check via tsc --noEmit
    if (scope === "all" || scope === "typescript") {
      try {
        const ts = await spawnWithTimeout(
          "npx",
          ["tsc", "--noEmit"],
          { timeoutMs: 60_000, cwd: join(PROJECT_ROOT, "cli") }
        );
        const passed = ts.exitCode === 0;
        results.push(
          `── TypeScript Type-Check (tsc --noEmit) ── ${passed ? "PASSED" : "FAILED"}\n` +
          `Exit code: ${ts.exitCode}\n\n` +
          truncate(ts.stdout + (ts.stderr ? `\nStderr:\n${ts.stderr}` : ""))
        );
      } catch (e) {
        results.push(`── TypeScript Type-Check ── ERROR\n${e.message}`);
      }
    }

    return { content: [{ type: "text", text: results.join("\n\n") }] };
  }
);

// ── Tool: lint ──────────────────────────────────────────────────────────────

server.tool(
  "lint",
  "Run linters on the codebase. Python uses ruff, TypeScript uses tsc --noEmit. Returns issues found.",
  {
    scope: z.enum(["all", "python", "typescript"]).default("all").describe("Which linter to run: all, python, or typescript"),
  },
  async ({ scope }) => {
    const results = [];

    // Python lint via ruff
    if (scope === "all" || scope === "python") {
      try {
        const py = await spawnWithTimeout(
          PYTHON,
          ["-m", "ruff", "check", "agents/", "utils/", "tests/", "pipeline_runner.py", "cli_launcher.py", "cli_fallback.py"],
          { timeoutMs: 30_000 }
        );
        const clean = py.exitCode === 0;
        results.push(
          `── Python Lint (ruff) ── ${clean ? "CLEAN" : "ISSUES FOUND"}\n` +
          `Exit code: ${py.exitCode}\n\n` +
          truncate(py.stdout + (py.stderr ? `\nStderr:\n${py.stderr}` : ""))
        );
      } catch (e) {
        results.push(`── Python Lint ── ERROR\n${e.message}`);
      }
    }

    // TypeScript lint via tsc --noEmit
    if (scope === "all" || scope === "typescript") {
      try {
        const ts = await spawnWithTimeout(
          "npx",
          ["tsc", "--noEmit"],
          { timeoutMs: 30_000, cwd: join(PROJECT_ROOT, "cli") }
        );
        const clean = ts.exitCode === 0;
        results.push(
          `── TypeScript Lint (tsc --noEmit) ── ${clean ? "CLEAN" : "ISSUES FOUND"}\n` +
          `Exit code: ${ts.exitCode}\n\n` +
          truncate(ts.stdout + (ts.stderr ? `\nStderr:\n${ts.stderr}` : ""))
        );
      } catch (e) {
        results.push(`── TypeScript Lint ── ERROR\n${e.message}`);
      }
    }

    return { content: [{ type: "text", text: results.join("\n\n") }] };
  }
);

// ── Tool: format_code ───────────────────────────────────────────────────────

server.tool(
  "format_code",
  "Auto-format Python code with ruff. Optionally target a specific file or directory; defaults to all Python source files.",
  {
    path: z.string().optional().describe("File or directory to format (relative to project root). Defaults to all Python source files."),
  },
  async ({ path }) => {
    const targets = path
      ? [path]
      : ["agents/", "utils/", "tests/", "pipeline_runner.py", "cli_launcher.py", "cli_fallback.py"];

    try {
      const fmt = await spawnWithTimeout(
        PYTHON,
        ["-m", "ruff", "format", ...targets],
        { timeoutMs: 30_000 }
      );

      // Also run ruff check --fix for auto-fixable lint issues
      const fix = await spawnWithTimeout(
        PYTHON,
        ["-m", "ruff", "check", "--fix", ...targets],
        { timeoutMs: 30_000 }
      );

      const parts = [];
      parts.push(
        `── ruff format ── Exit code: ${fmt.exitCode}\n` +
        truncate(fmt.stdout + (fmt.stderr ? `\nStderr:\n${fmt.stderr}` : "") || "(no output — files already formatted)")
      );
      parts.push(
        `── ruff check --fix ── Exit code: ${fix.exitCode}\n` +
        truncate(fix.stdout + (fix.stderr ? `\nStderr:\n${fix.stderr}` : "") || "(no auto-fixable issues)")
      );

      const allClean = fmt.exitCode === 0 && fix.exitCode === 0;
      return {
        content: [{ type: "text", text: `Format result: ${allClean ? "SUCCESS" : "COMPLETED WITH ISSUES"}\n\n${parts.join("\n\n")}` }],
      };
    } catch (e) {
      return { content: [{ type: "text", text: `Format failed: ${e.message}` }] };
    }
  }
);

// ── Start Server ────────────────────────────────────────────────────────────

const transport = new StdioServerTransport();
await server.connect(transport);
