from notify import card_signal, card_prepump

print('=== SIGNAL CARD ===')
sig = card_signal('MORPHOUSDT', 'BUY', 65, source='first-move', price=2.234,
                  vol=7.13, mom=0.36, imb=-0.17,
                  ta_bias='NEUTRAL', ta_score=41, flags='+1.32',
                  tf='5m', plan={'entry':2.251,'stop':2.220,'tp1':2.282,'tp2':2.344,'trail_arm':2.27270,'trail_dist':0.011255,'rr':3.0})
print(sig)
print()
print('=== PRE-PUMP CARD ===')
pre = card_prepump('MORPHOUSDT', 78, ['vol spike'], direction='BUY', price=2.229,
                   tf='1m', mom=2.22,imb=0.6,spread=0.12,bid_liq=85000,ask_liq=87000,
                   structure='UPTREND 85',need_vol=2.5,need_mom=1.5,
                   plan={'entry':2.23,'stop':2.18,'tp1':2.25,'tp2':2.28,'trail_arm':2.24,'trail_dist':0.05,'rr':2.5})
print(pre)
print()
print('=== CHECKS ===')
print('Signal header correct:', '◆ SIGNAL · MORPHOUSDT' in sig)
print('Signal TV link:', '<a href=' in sig and 'MORPHOUSDT</a>' in sig)
print('Prepump header:', 'PRE-PUMP COIL · MORPHOUSDT' in pre)
print('Prepump duplicate:', 'MORPHOUSDT (MORPHOUSDT)' not in pre)
print('Prepump TV link:', '<a href=' in pre and 'MORPHOUSDT</a>' in pre)
