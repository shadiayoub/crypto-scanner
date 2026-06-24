module.exports = {
  apps: [
    {
      name: "signal-scanner",
      script: "run_all.sh",
      cwd: "/home/algo/crypto-scanner",
      autorestart: true,
      out_file: "/dev/null",
      error_file: "/home/algo/crypto-scanner/logs/signal-scanner-error.log",
      merge_logs: true,
    },
    {
      name: "feed-server",
      script: "python3",
      args: "-m http.server 8080",
      cwd: "/home/algo/crypto-scanner/data",
      autorestart: true,
      out_file: "/dev/null",
      error_file: "/home/algo/crypto-scanner/logs/feed-server-error.log",
      merge_logs: true,
    },
  ],
};