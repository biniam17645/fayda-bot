from kenat import Kenat
from datetime import datetime, timedelta


def ethiopian_subtract_days(year, month, day, days):
    """Subtract days from Ethiopian date using Ethiopian calendar rules only."""
    days_in_month = {1: 30, 2: 30, 3: 30, 4: 30, 5: 30, 6: 30,
                     7: 30, 8: 30, 9: 30, 10: 30, 11: 30, 12: 30, 13: 5}

    # Check leap year for Pagume (13th month has 6 days)
    if year % 4 == 0:
        days_in_month[13] = 6

    current_day = day
    current_month = month
    current_year = year

    for _ in range(days):
        current_day -= 1
        if current_day < 1:
            current_month -= 1
            if current_month < 1:
                current_month = 13
                current_year -= 1
                if current_year % 4 == 0:
                    days_in_month[13] = 6
                else:
                    days_in_month[13] = 5
            current_day = days_in_month[current_month]

    return current_year, current_month, current_day


print("=" * 60)
print("INDEPENDENT ETHIOPIAN AND GREGORIAN CALCULATIONS")
print("=" * 60)

# ========== ETHIOPIAN CALENDAR (Pure Kenat, no Gregorian) ==========
print("\n📅 ETHIOPIAN CALENDAR:")
eth_now = Kenat.now()
print(
    f"  Current Ethiopian: {eth_now.day:02d}/{eth_now.month:02d}/{eth_now.year}")

# DOI (Issue Date) - Current date
doi_eth_year = eth_now.year
doi_eth_month = eth_now.month
doi_eth_day = eth_now.day

# Expiry - Add 8 years, then subtract 2 days
expiry_eth_year = doi_eth_year + 8
expiry_eth_month = doi_eth_month
expiry_eth_day = doi_eth_day

# Subtract 2 days using pure Ethiopian logic
final_eth_year, final_eth_month, final_eth_day = ethiopian_subtract_days(
    expiry_eth_year, expiry_eth_month, expiry_eth_day, 2
)

print(f"  DOI Ethiopian: {doi_eth_day:02d}/{doi_eth_month:02d}/{doi_eth_year}")
print(
    f"  Expiry Ethiopian: {final_eth_day:02d}/{final_eth_month:02d}/{final_eth_year}")

# ========== GREGORIAN CALENDAR (Using local time, not UTC) ==========
print("\n📅 GREGORIAN CALENDAR:")
# Use local time instead of UTC
now = datetime.now()  # This uses local system time
print(f"  Current Gregorian: {now.strftime('%Y-%m-%d')}")

# DOI (Issue Date) - Current date
doi_greg = now
print(f"  DOI Gregorian: {doi_greg.strftime('%Y/%b/%d')}")

# Expiry - Current date + 8 years - 2 days
expiry_greg = now.replace(year=now.year + 8) - timedelta(days=2)
print(f"  Expiry Gregorian: {expiry_greg.strftime('%Y/%b/%d')}")

print("\n" + "=" * 60)
print("✅ RESULTS (Calendars calculated independently)")
print("=" * 60)
print(f"DOI Ethiopian: {doi_eth_day:02d}/{doi_eth_month:02d}/{doi_eth_year}")
print(f"DOI Gregorian: {doi_greg.strftime('%Y/%b/%d')}")
print(
    f"Expiry Ethiopian: {final_eth_day:02d}/{final_eth_month:02d}/{final_eth_year}")
print(f"Expiry Gregorian: {expiry_greg.strftime('%Y/%b/%d')}")
