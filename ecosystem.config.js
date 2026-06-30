// Single source of truth for the whole stack.
//   pm2 start ecosystem.config.js
//
// signal-scanner: runs scanner.py with its built-in --loop so the process stays
// continuously "online" (no cron_restart / "stopped" flapping). The loop sleeps
// to the next wall-clock interval, so scans still land on round times.
//
// Logs: stdout+stderr go to real files (merge_logs) instead of /dev/null, so
// `pm2 logs` works. Size is capped by the pm2-logrotate module (configured in
// runpm2.sh): max_size + retain keep the files from growing unbounded.
module.exports = {
  apps: [
    {
      name: "signal-scanner",
      script: "scanner.py",
      interpreter: "python3",
      args: "-tf 30m --loop 15",     // scan every 15m, stay resident
      cwd: "/home/algo/crypto-scanner",
      autorestart: true,             // restart only on crash; normally never exits
      out_file: "/home/algo/crypto-scanner/logs/signal-scanner.log",
      error_file: "/home/algo/crypto-scanner/logs/signal-scanner.log",
      merge_logs: true,
    },
    {
      name: "xag-scanner",
      script: "xag-scanner.py",
      interpreter: "python3",
      args: "-tf 15m --loop 5",      // xag-scanner has its own internal loop
      cwd: "/home/algo/crypto-scanner",
      autorestart: true,
      out_file: "/home/algo/crypto-scanner/logs/xag-scanner.log",
      error_file: "/home/algo/crypto-scanner/logs/xag-scanner.log",
      merge_logs: true,
    },
    {
      name: "feed-server",
      script: "python3",
      args: "-m http.server 8880",
      cwd: "/home/algo/crypto-scanner/data",
      autorestart: true,
      out_file: "/home/algo/crypto-scanner/logs/feed-server.log",
      error_file: "/home/algo/crypto-scanner/logs/feed-server.log",
      merge_logs: true,
    },
  ],
};
