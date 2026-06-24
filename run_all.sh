#!/bin/bash
TIMEFRAMES="15m 30m 1h 4h 1d"

while true; do
  for tf in $TIMEFRAMES; do
    python3 scanner.py -tf "$tf"
  done
  sleep 300  # 5 minutes between full cycles
done