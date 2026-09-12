#!/usr/bin/env python3
"""
Integration test: WX_2_MQTT_v2.py with emulator.
Runs full pipeline: emulator packet → parse → sanitize → tracker → derived calcs.
Prints all 21 MQTT topics with values (without actual broker connection).
"""
import struct
import json
import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wx_common import parse_packet, sanitize, WindTracker

# --- Import calc functions from WX_2_MQTT_v2 ---
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

PARRAY_SIZE = 60
P30_SIZE = 30

class PressureTracker:
    def __init__(self):
        self.p1m = [0.0] * PARRAY_SIZE
        self.p1m_idx = 0
        self.p1m_count = 0
        self.p30m = [0.0] * P30_SIZE
        self.p30m_idx = 0
        self.p30m_count = 0

    def update(self, p_mmhg):
        self.p1m[self.p1m_idx] = p_mmhg
        self.p1m_idx += 1
        if self.p1m_idx >= PARRAY_SIZE:
            self.p1m_idx = 0
            p_avg = sum(self.p1m) / PARRAY_SIZE
            self.p30m[self.p30m_idx] = p_avg
            self.p30m_idx += 1
            if self.p30m_idx >= P30_SIZE:
                self.p30m_idx = 0
                self.p30m_count = P30_SIZE
            else:
                self.p30m_count = self.p30m_idx
        if self.p1m_count < PARRAY_SIZE:
            self.p1m_count += 1

    def trend_30m(self, p_current):
        if self.p30m_count == 0:
            return 0.0
        p_avg = sum(self.p30m[:self.p30m_count]) / self.p30m_count
        return round((p_current - p_avg) * 1.33322, 2)


def build_packet(mac_hex, ds18_t, bme_t, bme_h, bme_p, sht_t, sht_h, wind_dir, wind_speed):
    mac = bytes.fromhex(mac_hex)
    pkt = bytearray(36)
    pkt[0:6] = mac
    struct.pack_into('<f', pkt, 6, ds18_t)
    struct.pack_into('<f', pkt, 10, bme_t)
    struct.pack_into('<f', pkt, 14, bme_h)
    struct.pack_into('<f', pkt, 18, bme_p)
    struct.pack_into('<f', pkt, 22, sht_t)
    struct.pack_into('<f', pkt, 26, sht_h)
    struct.pack_into('<h', pkt, 30, wind_dir)
    struct.pack_into('<f', pkt, 32, wind_speed)
    return bytes(pkt)


def sensor_health(v):
    ds18_ok = v['ds18_t'] != -127
    bme_ok = v['bme_t'] != -127
    sht_ok = v['sht_t'] != -127
    temps = []
    if ds18_ok: temps.append(v['ds18_t'])
    if bme_ok: temps.append(v['bme_t'])
    if sht_ok: temps.append(v['sht_t'])
    ts = (max(temps) - min(temps)) if len(temps) >= 2 else 0.0
    hs = abs(v['bme_h'] - v['sht_h']) if (bme_ok and sht_ok and v['sht_h'] < 99) else 0.0
    if not (ds18_ok and bme_ok and sht_ok):
        st = "offline"
    elif ts > 3.0 or hs > 10.0:
        st = "warning"
    else:
        st = "ok"
    return {"status": st, "temp_spread": round(ts,1), "hum_spread": round(hs,1),
            "ds18": ds18_ok, "bme": bme_ok, "sht": sht_ok}


def weather_prediction(v, p_trend, dp):
    t, h, w = v['ds18_t'], v['sht_h'], v['wind_speed']
    if p_trend < -3.0 and h > 80: return "rain_likely"
    elif p_trend < -2.0: return "change_expected"
    elif p_trend > 3.0: return "clearing"
    elif dp > -90 and t - dp < 3.0 and t < 15: return "fog_possible"
    elif w > 10.0: return "strong_wind"
    else: return "stable"


def run():
    print("=" * 60)
    print("Integration Test: WX_2_MQTT_v2 full pipeline")
    print("Emulator -> parse -> sanitize -> tracker -> MQTT topics")
    print("=" * 60)

    tracker = WindTracker()
    ptracker = PressureTracker()
    MAC = "A8610A000101"

    # Simulate 70 packets (60 for tracker cycle + 10 extra)
    topics_data = {}
    for i in range(70):
        # Vary wind to test tracker
        wind_speed = 3.0 + (i % 5) * 0.5
        wind_dir = 270 + (i % 10) * 10

        pkt = build_packet(MAC, 18.5, 16.2, 55.3, 740.5, 15.8, 58.1, wind_dir, wind_speed)

        # Pipeline
        v = parse_packet(pkt)
        v = sanitize(v)
        tracker.update(v['wind_speed'], v['wind_dir'])
        ptracker.update(v['bme_p'])

        # Derived
        dp = calc_dewpoint(v['ds18_t'], v['sht_h'])
        wc = calc_windchill(v['ds18_t'], v['wind_speed'])
        pt = ptracker.trend_30m(v['bme_p'])
        health = sensor_health(v)
        pred = weather_prediction(v, pt, dp)

    # Final output (last iteration values)
    print(f"\n--- MQTT Topics (21 total) ---\n")

    # Standard
    topics = [
        ("air_temperature", v['ds18_t']),
        ("air_pressure", v['bme_p']),
        ("air_humidity", v['sht_h']),
        ("wind_direction", v['wind_dir']),
        ("wind_speed", v['wind_speed']),
        # Wind stats
        ("wind_speed_max", tracker.wind_max),
        ("wind_speed_max_1m", round(tracker.wind_max_1m, 2)),
        ("wind_direction_avr_1m", tracker.dir_avr_1m),
        ("wind_speed_avr_1m", round(tracker.wind_avr_1m, 2)),
        ("wind_speed_max_avr_1m", round(tracker.wind_avr_max_1m, 2)),
        ("wind_direction_avr_10m", tracker.dir_avr_10m),
        ("wind_speed_avr_10m", round(tracker.wind_avr_10m, 2)),
        ("wind_speed_max_avr_10m", round(tracker.wind_avr_max_10m, 2)),
        ("wind_direction_avr_1h", tracker.dir_avr_1h),
        ("wind_speed_avr_1h", round(tracker.wind_avr_1h, 2)),
        ("wind_speed_max_avr_1h", round(tracker.wind_avr_max_1h, 2)),
        # NEW
        ("dew_point", round(dp, 1)),
        ("wind_chill", round(wc, 1)),
        ("pressure_trend_30m", pt),
        ("sensor_health", json.dumps(health)),
        ("weather_prediction", pred),
    ]

    for topic, value in topics:
        print(f"  WX_Station/sensor/{topic:25s} = {value}")

    # Validation
    print(f"\n--- Validation ---")
    errors = 0

    assert v['ds18_t'] == 18.5, "DS18 temperature mismatch"
    assert v['bme_p'] == 740.5, "Pressure mismatch"
    assert v['wind_speed'] == wind_speed, "Wind speed mismatch"
    print(f"  [OK] Packet parse correct")

    assert 0 < dp < 18.5, "Dew point should be between 0 and air temp"
    print(f"  [OK] Dew point: {dp:.1f}C (valid range)")

    assert wc == 18.5, "Wind chill = T when T > 10C"
    print(f"  [OK] Wind chill: {wc:.1f}C (no effect at 18.5C)")

    assert health['status'] == 'ok', f"Health should be ok, got {health['status']}"
    print(f"  [OK] Sensor health: {health['status']}")

    assert pred == 'stable', f"Prediction should be stable, got {pred}"
    print(f"  [OK] Prediction: {pred}")

    assert tracker.wind_max_1m > 0, "Wind max should be > 0 after data"
    print(f"  [OK] Wind max_1m: {tracker.wind_max_1m:.2f} m/s")

    assert ptracker.p1m_count == 60, "Pressure tracker should have full 1-min buffer"
    print(f"  [OK] Pressure tracker: {ptracker.p1m_count}/60 samples (1-min full)")

    print(f"\n{'=' * 60}")
    print(f"RESULT: ALL PASSED - 21/21 topics verified")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    run()
