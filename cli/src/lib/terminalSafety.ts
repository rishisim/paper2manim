const RESET_SEQUENCES = [
  '\x1b[?1000l', // mouse tracking
  '\x1b[?1002l',
  '\x1b[?1003l',
  '\x1b[?1005l',
  '\x1b[?1006l',
  '\x1b[?1015l',
  '\x1b[?1049l', // alt screen
  '\x1b[?25h',   // cursor visible
  '\x1b[>4;0m',  // disable modifyOtherKeys / enhanced keyboard variants when supported
];

let installed = false;

export function resetTerminalModes(): void {
  if (!process.stdout.isTTY) return;
  try {
    process.stdout.write(RESET_SEQUENCES.join(''));
  } catch {
    // Ignore closed or non-writable stdout during shutdown.
  }
}

export function installTerminalSafetyHooks(): void {
  if (installed) return;
  installed = true;

  resetTerminalModes();

  const cleanup = () => {
    resetTerminalModes();
  };

  process.on('exit', cleanup);
  process.on('SIGINT', () => {
    cleanup();
    process.exit(130);
  });
  process.on('SIGTERM', () => {
    cleanup();
    process.exit(143);
  });
  process.on('uncaughtException', (error) => {
    cleanup();
    throw error;
  });
}
