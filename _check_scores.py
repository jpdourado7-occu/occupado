import os, sys
os.environ['DATABASE_URL'] = 'postgresql://postgres:REDACTED@hopper.proxy.rlwy.net:26482/railway'
sys.path.insert(0, r'C:\Users\jpdou\Desktop\Occupado')
from dotenv import load_dotenv
load_dotenv(r'C:\Users\jpdou\Desktop\Occupado\.env')

from app import VDV_FUTURE_BOOKINGS as B, VDV_FUTURE_SCORES as S

print(f"Total bookings: {len(B)}")
print(f"Min: {min(S):.1f}%  Max: {max(S):.1f}%  Mean: {sum(S)/len(S):.1f}%")
print(f"High >=70: {sum(1 for s in S if s>=70)}")
print(f"Med  40-69: {sum(1 for s in S if 40<=s<70)}")
print(f"Low  <40:   {sum(1 for s in S if s<40)}")

from collections import defaultdict
ch = defaultdict(list)
for b, s in zip(B, S):
    ch[b['channel']].append(s)
print("\nBy channel:")
for c, ss in sorted(ch.items()):
    print(f"  {c}: avg={sum(ss)/len(ss):.1f}%  n={len(ss)}")

print("\nTop 10:")
indexed = sorted(enumerate(S), key=lambda x: -x[1])[:10]
for rank, (idx, sc) in enumerate(indexed):
    b = B[idx]
    print(f"  {rank+1}. {b['name'][:25]:<25} {b['channel']:<20} {sc:.1f}%")
