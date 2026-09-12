#!/usr/bin/env python3
"""Quick test for WX_2_MQTT derived calculations."""
import math
import json

def calc_dewpoint(temp_c, rh_pct):
    if rh_pct <= 0 or rh_pct >= 100:
        return temp_c if rh_pct >= 100 else -99.0
    gamma = math.log(rh_pct / 100.0) + 17.67 * temp_c / (243.5 + temp_c)
    return 243.5 * gamma / (17.67 - gamma)

def calc_windchill(temp_c, wind_ms):
    if temp_c >= 10.0 or wind_ms < 1.39:
        return temp_c
    v_kmh = wind_ms * 3.6
    return 13.12 + 0.6215 * temp_c - 11.37 * (v_kmh ** 0.16) + 0.3965 * temp_c * (v_kmh ** 0.16)

def calc_sensor_health(v):
    ds18_online = v['ds18_t'] != -127
    bme_online = v['bme_t'] != -127
    sht_online = v['sht_t'] != -127
    temps = []
    if ds18_online: temps.append(v['ds18_t'])
    if bme_online:  temps.append(v['bme_t'])
    if sht_online:  temps.append(v['sht_t'])
    temp_spread = (max(temps) - min(temps)) if len(temps) >= 2 else 0.0
    hum_spread = abs(v['bme_h'] - v['sht_h']) if (bme_online and sht_online and v['sht_h'] < 99) else 0.0
    if not (ds18_online and bme_online and sht_online):
        status = "offline"
    elif temp_spread > 3.0 or hum_spread > 10.0:
        status = "warning"
    else:
        status = "ok"
    return {"status": status, "temp_spread": round(temp_spread,1), "hum_spread": round(hum_spread,1),
            "ds18": ds18_online, "bme": bme_online, "sht": sht_online}

def calc_weather_prediction(v, p_trend_hpa, dewpoint):
    temp, hum, wind = v['ds18_t'], v['sht_h'], v['wind_speed']
    if p_trend_hpa < -3.0 and hum > 80: return "rain_likely"
    elif p_trend_hpa < -2.0: return "change_expected"
    elif p_trend_hpa > 3.0: return "clearing"
    elif dewpoint > -90 and temp - dewpoint < 3.0 and temp < 15: return "fog_possible"
    elif wind > 10.0: return "strong_wind"
    else: return "stable"

print("=" * 50)
print("Test: Derived MQTT calculations")
print("=" * 50)

# Dew point
print("\n--- Dew Point (Magnus) ---")
dp1 = calc_dewpoint(18, 55)
dp2 = calc_dewpoint(5, 95)
dp3 = calc_dewpoint(25, 30)
print(f"  T=18C, RH=55% -> {dp1:.1f}C")
print(f"  T=5C,  RH=95% -> {dp2:.1f}C (close to T = high humidity)")
print(f"  T=25C, RH=30% -> {dp3:.1f}C (very dry)")
assert dp1 < 18, "Dew point must be below air temp"
assert dp2 > 3, "Dew point should be close to 5C at 95% RH"
assert dp3 < 10, "Dew point should be low at 30% RH"
print("  [OK]")

# Wind chill
print("\n--- Wind Chill ---")
wc1 = calc_windchill(18, 5)
wc2 = calc_windchill(5, 5)
wc3 = calc_windchill(-5, 10)
wc4 = calc_windchill(5, 1)  # too slow
print(f"  T=18C, W=5 m/s  -> {wc1:.1f}C (no chill, T>10)")
print(f"  T=5C,  W=5 m/s  -> {wc2:.1f}C")
print(f"  T=-5C, W=10 m/s -> {wc3:.1f}C (cold + windy)")
print(f"  T=5C,  W=1 m/s  -> {wc4:.1f}C (no chill, W<1.39)")
assert wc1 == 18, "No wind chill when T >= 10"
assert wc2 < 5, "Wind chill should be lower than air temp"
assert wc3 < -5, "Cold + wind = much lower felt temp"
assert wc4 == 5, "No wind chill when wind < 1.39 m/s"
print("  [OK]")

# Sensor health
print("\n--- Sensor Health ---")
v_ok = {'ds18_t':18.5, 'bme_t':18.2, 'sht_t':18.0, 'bme_h':55, 'sht_h':57, 'bme_p':740}
h1 = calc_sensor_health(v_ok)
print(f"  Normal: {json.dumps(h1)}")
assert h1['status'] == 'ok'

v_warn = {'ds18_t':20.0, 'bme_t':16.0, 'sht_t':18.0, 'bme_h':55, 'sht_h':57, 'bme_p':740}
h2 = calc_sensor_health(v_warn)
print(f"  Spread: {json.dumps(h2)}")
assert h2['status'] == 'warning'
assert h2['temp_spread'] > 3

v_off = {'ds18_t':-127, 'bme_t':16.0, 'sht_t':18.0, 'bme_h':55, 'sht_h':57, 'bme_p':740}
h3 = calc_sensor_health(v_off)
print(f"  Offline:{json.dumps(h3)}")
assert h3['status'] == 'offline'
assert h3['ds18'] == False
print("  [OK]")

# Weather prediction
print("\n--- Weather Prediction ---")
v = {'ds18_t':18, 'sht_h':60, 'wind_speed':5}
tests = [
    ({'ds18_t':18, 'sht_h':85, 'wind_speed':5}, -4.0, 10.0, "rain_likely"),
    (v, -2.5, 10.0, "change_expected"),
    (v, 4.0, 10.0, "clearing"),
    ({'ds18_t':10, 'sht_h':90, 'wind_speed':2}, 0.5, 8.5, "fog_possible"),
    ({'ds18_t':20, 'sht_h':50, 'wind_speed':12}, 0.5, 10.0, "strong_wind"),
    (v, 0.5, 10.0, "stable"),
]
for tv, trend, dp, expected in tests:
    result = calc_weather_prediction(tv, trend, dp)
    status = "OK" if result == expected else "FAIL"
    print(f"  Trend={trend:+.1f}, T={tv['ds18_t']}, H={tv['sht_h']}% -> {result:18s} [{status}]")
    assert result == expected, f"Expected {expected}, got {result}"
print("  [OK]")

print("\n" + "=" * 50)
print("All calculation tests PASSED")
print("=" * 50)
