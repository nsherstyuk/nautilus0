import itertools

sl_values = [0.8, 1.0, 1.2, 1.6]
tp_values = [0.6, 0.8, 1.0, 1.2, 1.5]
trailing_values = [0.4, 0.5]
threshold_values = [0.65, 0.68]

print(f"Total combinations: {len(sl_values) * len(tp_values) * len(trailing_values) * len(threshold_values)}")
print()

count = 0
for sl, tp, trail, thresh in itertools.product(sl_values, tp_values, trailing_values, threshold_values):
    skip = False
    
    # Current filters
    if sl < tp * 0.5:
        skip = True
    if sl > tp * 1.8:
        skip = True
    if tp < sl * 0.6:
        skip = True
    
    if not skip:
        count += 1
        print(f"SL={sl}, TP={tp}, TR={trail}, TH={thresh}")

print(f"\nTotal after current filtering: {count}")
