pm2 start xag-scanner.py --name xag-scanner --interpreter python3 -- -tf 15m --loop 5
pm2 start scanner.py --name scanner --interpreter python3 -- -tf 15m --loop 5
pm2 start 5m-btc-scanner.py --name btc-state-scanner --interpreter python3 -- -tf 30m --loop 15