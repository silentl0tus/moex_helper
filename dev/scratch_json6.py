import json

filename = "Ликвидная часть (2).json"
with open(filename, 'r') as f:
    data = json.load(f)

# Total cash from cash-balances
cash_rub = 0
for cb in data.get('cash-balances', []):
    if cb.get('currency') == 'RUB':
        cash_rub += cb.get('value', 0)
print(f"Raw cash balance in JSON: {cash_rub}")

# Payments (dividends/coupons)
dividends = sum(p.get('summa', 0) for p in data.get('payments', []) if p.get('type') == 'dividend')
coupons = sum(p.get('summa', 0) for p in data.get('payments', []) if p.get('type') == 'coupon')
print(f"Total dividends: {dividends}")
print(f"Total coupons: {coupons}")

# Cash flows (deposits/withdrawals)
deposits = sum(c.get('value', 0) for c in data.get('cash-flows', []) if c.get('value', 0) > 0)
withdrawals = sum(c.get('value', 0) for c in data.get('cash-flows', []) if c.get('value', 0) < 0)
print(f"Total deposits: {deposits}")
print(f"Total withdrawals: {withdrawals}")
print(f"Net deposits: {deposits + withdrawals}")

