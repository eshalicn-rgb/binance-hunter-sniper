with open('notify.py', 'r', encoding='utf-8') as f:
    c = f.read()

# Fix prepump header - remove duplicate symbol
c = c.replace(
    '<b>\u25c8 PRE-PUMP COIL \xc2\xb7 {} ({})</b>'.format('{}', '{}'),
    '<b>\u25c8 PRE-PUMP COIL \\xc2\\xb7 {}</b>'
)

with open('notify.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Done fixing prepump header')