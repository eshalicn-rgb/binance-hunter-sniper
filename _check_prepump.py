#!/usr/bin/env python3
import json, requests
r = requests.get('http://127.0.0.1:3245/api/results')
j = r.json()
# show prepump-related keys
for k in j['backtest_all'].keys():
    if 'prepump' in k.lower() or 'coiled' in k.lower():
        print(k, ':', json.dumps(j['backtest_all'][k])[:200])