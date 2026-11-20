import re
t = open('.env', encoding='utf-8', errors='ignore').read()
m = re.search(r'^BINANCE_API_KEY=(.+)$', t, re.M)
k = m.group(1).strip().strip('"').strip("'") if m else ''
print('env_key_len', len(k))
print('starts_with_RSDcSYSf', k.startswith('RSDcSYSf'))
print('first2', k[:2])
