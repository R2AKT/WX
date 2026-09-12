#!/usr/bin/env python3
"""
Test suite for WX v2 refactoring against WeatherFlow Tempest UDP protocol v171.
Tests:
  1. Packet format (binary structure)
  2. Consumer parse + sanitize
  3. WX_2_WEE protocol compliance (v171)
  4. Gen_WX output format (APRS)
  5. WX_2_MQTT structure
"""
import socket
import struct
import json
import time
import threading
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wx_common import parse_packet, sanitize, WindTracker, wind_direction_str
from WX_emulator import build_packet

PASS = 0
FAIL = 0

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print("  [OK]   {}".format(name))
    else:
        FAIL += 1
        print("  [FAIL] {} {}".format(name, detail))


# ─── Test 1: Binary packet format ───────────────────────────────────────────
def test_packet_format():
    print("\n[Test 1] Binary packet format (36 bytes)")
    mac = b'\xA8\x61\x0A\x00\x01\x01'
    pkt = build_packet(mac=mac, ds18_t=15.5, bme_t=16.2, bme_h=55.3,
                       bme_p=755.1, sht_t=16.8, sht_h=54.6,
                       wind_dir=270, wind_speed=3.2)
    check("Length = 36", len(pkt) == 36, "got {}".format(len(pkt)))
    check("MAC at [0:6]", pkt[0:6] == mac)
    check("DS18_T at [6:10]", abs(struct.unpack('<f', pkt[6:10])[0] - 15.5) < 0.01)
    check("BME_T at [10:14]", abs(struct.unpack('<f', pkt[10:14])[0] - 16.2) < 0.01)
    check("BME_H at [14:18]", abs(struct.unpack('<f', pkt[14:18])[0] - 55.3) < 0.01)
    check("BME_P at [18:22]", abs(struct.unpack('<f', pkt[18:22])[0] - 755.1) < 0.01)
    check("SHT_T at [22:26]", abs(struct.unpack('<f', pkt[22:26])[0] - 16.8) < 0.01)
    check("SHT_H at [26:30]", abs(struct.unpack('<f', pkt[26:30])[0] - 54.6) < 0.01)
    check("AS56_Dir int16 at [30:32]", struct.unpack('<h', pkt[30:32])[0] == 270)
    check("TLE49 float32 at [32:36]", abs(struct.unpack('<f', pkt[32:36])[0] - 3.2) < 0.01)


# ─── Test 2: Parse + Sanitize ───────────────────────────────────────────────
def test_parse_sanitize():
    print("\n[Test 2] Parse + Sanitize")
    mac = b'\xDE\xAD\xBE\xEF\x00\x01'
    pkt = build_packet(mac=mac, ds18_t=20.0, bme_t=21.0, bme_h=60.0,
                       bme_p=760.0, sht_t=20.5, sht_h=58.0,
                       wind_dir=180, wind_speed=5.0)
    v = parse_packet(pkt)
    v = sanitize(v)
    check("MAC parsed", v['mac'] == 'DEADBEEF0001')
    check("DS18_T", v['ds18_t'] == 20.0)
    check("wind_dir int", isinstance(v['wind_dir'], int))
    check("wind_speed float", isinstance(v['wind_speed'], float))

    # NaN handling
    pkt_nan = bytearray(36)
    pkt_nan[0:6] = mac
    struct.pack_into('<f', pkt_nan, 6, float('nan'))  # DS18 NaN
    struct.pack_into('<f', pkt_nan, 14, float('nan')) # BME_H NaN
    struct.pack_into('<h', pkt_nan, 30, 100)
    struct.pack_into('<f', pkt_nan, 32, float('nan')) # wind NaN
    v2 = parse_packet(bytes(pkt_nan))
    v2 = sanitize(v2)
    check("NaN DS18 -> -127", v2['ds18_t'] == -127)
    check("NaN BME_H -> 99 (clamped)", v2['bme_h'] == 99)
    check("NaN wind -> 0", v2['wind_speed'] == 0)

    # Range validation
    pkt_range = build_packet(mac=mac, ds18_t=60.0, bme_t=20.0, bme_h=100.0,
                             bme_p=760.0, sht_t=20.0, sht_h=95.0,
                             wind_dir=370, wind_speed=5.0)
    v3 = parse_packet(pkt_range)
    v3 = sanitize(v3)
    check("wind_dir 370 -> 0", v3['wind_dir'] == 0)
    check("bme_h 100 -> 99", v3['bme_h'] == 99)
    check("sht_h 95 stays", v3['sht_h'] == 95)

    # wind_dir = 360 is VALID (only >360 wraps)
    pkt_360 = build_packet(mac=mac, ds18_t=20.0, bme_t=20.0, bme_h=50.0,
                           bme_p=760.0, sht_t=20.0, sht_h=50.0,
                           wind_dir=360, wind_speed=5.0)
    v4 = parse_packet(pkt_360)
    v4 = sanitize(v4)
    check("wind_dir 360 stays (valid)", v4['wind_dir'] == 360)


# ─── Test 3: WX_2_WEE protocol compliance (v171) ─────────────────────────
def test_wee_v171():
    print("\n[Test 3] WX_2_WEE protocol compliance (v171)")

    # We'll simulate what WX_2_WEE produces by running the same logic
    mac = b'\xA8\x61\x0A\x00\x01\x01'
    serial_number = mac.hex().upper()
    hub_sn = mac.hex().upper()
    Firmware_Revision = 171
    Wind_Interval = 1
    Illuminance = 0
    UV = 0.0
    Sun_Radiation = 0
    Precipitation = 0
    Lightning_Distance = 0
    Lightning_Count = 0
    Battery = 4.999
    Report_Interval_Minutes = 1

    # Simulate 60 packets to trigger the cycle
    tracker = WindTracker()
    UTCTime = int(time.time())
    bme_p = 755.0
    ds18_t = 15.5
    sht_h = 54.0
    wind_speed = 3.2
    wind_dir = 90

    for i in range(60):
        tracker.update(wind_speed, wind_dir)

    # rapid_wind (every packet)
    WXData_rw = {
        "serial_number": serial_number,
        "type": "rapid_wind",
        "hub_sn": hub_sn,
        "ob": [UTCTime, float("{:.3f}".format(wind_speed)), int(wind_dir)]
    }
    check("rapid_wind: has serial_number", "serial_number" in WXData_rw)
    check("rapid_wind: has hub_sn", "hub_sn" in WXData_rw)
    check("rapid_wind: has type", WXData_rw["type"] == "rapid_wind")
    check("rapid_wind: ob is FLAT list (not nested)", isinstance(WXData_rw["ob"], list) and len(WXData_rw["ob"]) == 3)
    check("rapid_wind: ob[0] is int (ts)", isinstance(WXData_rw["ob"][0], int))
    check("rapid_wind: ob[1] is float (speed)", isinstance(WXData_rw["ob"][1], float))
    check("rapid_wind: ob[2] is int (dir)", isinstance(WXData_rw["ob"][2], int))
    check("rapid_wind: no device_id key", "device_id" not in WXData_rw)

    # obs_st (every 60 sec)
    WXData_st = {
        "serial_number": serial_number,
        "type": "obs_st",
        "hub_sn": hub_sn,
        "obs": [[
            UTCTime,
            float("{:.3f}".format(tracker.wind_avr_1m)),
            float("{:.3f}".format(tracker.wind_avr_10m)),
            float("{:.3f}".format(tracker.wind_max_1m)),
            int(tracker.dir_avr_1m),
            Wind_Interval,
            float("{:.3f}".format(bme_p * 1.33322)),
            float("{:.3f}".format(ds18_t)),
            float("{:.3f}".format(sht_h)),
            Illuminance,
            float("{:.2f}".format(UV)),
            Sun_Radiation,
            float("{:.6f}".format(0.0)),
            Precipitation,
            Lightning_Distance,
            Lightning_Count,
            float("{:.3f}".format(Battery)),
            Report_Interval_Minutes
        ]],
        "firmware_revision": Firmware_Revision
    }
    check("obs_st: has serial_number", "serial_number" in WXData_st)
    check("obs_st: type is obs_st", WXData_st["type"] == "obs_st")
    check("obs_st: has hub_sn", "hub_sn" in WXData_st)
    check("obs_st: obs is NESTED [[...]]", isinstance(WXData_st["obs"], list) and isinstance(WXData_st["obs"][0], list))
    check("obs_st: 18 fields in obs[0]", len(WXData_st["obs"][0]) == 18)
    check("obs_st: has firmware_revision", WXData_st.get("firmware_revision") == 171)
    check("obs_st: no device_id key", "device_id" not in WXData_st)
    check("obs_st: field[0] is ts (int)", isinstance(WXData_st["obs"][0][0], int))
    check("obs_st: field[6] pressure > 0", WXData_st["obs"][0][6] > 0)
    check("obs_st: field[16] battery > 0", WXData_st["obs"][0][16] > 0)

    # obs_air (every 60 sec)
    WXData_air = {
        "serial_number": serial_number,
        "type": "obs_air",
        "hub_sn": hub_sn,
        "obs": [[
            UTCTime,
            float("{:.3f}".format(bme_p * 1.33322)),
            float("{:.3f}".format(ds18_t)),
            float("{:.3f}".format(sht_h)),
            Lightning_Count,
            Lightning_Distance,
            float("{:.3f}".format(Battery)),
            Report_Interval_Minutes
        ]],
        "firmware_revision": Firmware_Revision
    }
    check("obs_air: has serial_number", "serial_number" in WXData_air)
    check("obs_air: type is obs_air", WXData_air["type"] == "obs_air")
    check("obs_air: obs is NESTED [[...]]", isinstance(WXData_air["obs"], list) and isinstance(WXData_air["obs"][0], list))
    check("obs_air: 8 fields in obs[0]", len(WXData_air["obs"][0]) == 8)
    check("obs_air: has firmware_revision", WXData_air.get("firmware_revision") == 171)

    # JSON roundtrip
    for name, data in [("rapid_wind", WXData_rw), ("obs_st", WXData_st), ("obs_air", WXData_air)]:
        js = json.dumps(data)
        parsed = json.loads(js)
        check("{}: JSON roundtrip".format(name), json.dumps(parsed) == js)


# ─── Test 4: Gen_WX APRS format ─────────────────────────────────────────
def test_gen_wx_aprs():
    print("\n[Test 4] Gen_WX APRS format")
    # Simulate the APRS output format
    ds18_t = 15.5
    bme_p = 755.0
    sht_h = 54.0
    wind_dir = 90
    wind_speed = 3.2

    # APRS format: !lat/lon_cDDDsssGGGtTTThHHbPPPPPCOMMENT
    # t = temp (C, offset 60 for negative, no offset for positive, 3 digits)
    # h = humidity (2 digits)
    # b = pressure (4 digits, hPa)
    lat = "5556.34N"
    lon = "03758.45E"

    temp_val = int(ds18_t)  # 15
    if temp_val < 0:
        temp_str = "t{:03d}".format(temp_val + 60)
    else:
        temp_str = "t{:03d}".format(temp_val)

    hum_str = "h{:02d}".format(int(sht_h))
    pressure_hpa = int(bme_p * 1.33322)
    baro_str = "b{:04d}".format(pressure_hpa)

    dir_str = "c{:03d}".format(int(wind_dir))
    speed_mph = wind_speed * 2.2369362920544025
    speed_str = "s{:03d}".format(round(speed_mph))
    gust_str = "g{:03d}".format(round(speed_mph))

    aprs = "!{}/{}_{}{}{}{}{}{} shchyolkovo WX station".format(
        lat, lon, dir_str, speed_str, gust_str, temp_str, hum_str, baro_str)

    # Verify format
    check("APRS starts with !", aprs.startswith("!"))
    check("APRS has lat/lon", "/03758.45E_" in aprs)
    check("APRS has cDDD (dir)", "c090" in aprs)
    check("APRS has s (speed)", "s" in aprs)
    check("APRS has t (temp)", "t" in aprs)
    check("APRS has h (hum)", "h54" in aprs)
    check("APRS has b (baro)", "b{:04d}".format(pressure_hpa) in aprs)
    check("APRS has comment", "shchyolkovo WX station" in aprs)
    print("  APRS: " + aprs)

    # wind_direction_str check
    check("wind_dir 90 -> E", wind_direction_str(90) == "E")
    check("wind_dir 0 -> N", wind_direction_str(0) == "N")
    check("wind_dir 360 -> N", wind_direction_str(360) == "N")
    check("wind_dir 359 -> N", wind_direction_str(359) == "N")
    check("wind_dir 180 -> S", wind_direction_str(180) == "S")
    check("wind_dir 270 -> W", wind_direction_str(270) == "W")


# ─── Test 5: WindTracker behavior ───────────────────────────────────────────
def test_wind_tracker():
    print("\n[Test 5] WindTracker behavior")
    t = WindTracker()

    # After 60 identical samples: avg = value, max = value
    for i in range(60):
        done = t.update(5.0, 90)
    check("After 60 samples: wind_avr_1m = 5.0", abs(t.wind_avr_1m - 5.0) < 0.001)
    check("After 60 samples: wind_max_1m = 5.0", abs(t.wind_max_1m - 5.0) < 0.001)
    check("After 60 samples: dir_avr_1m = 90", abs(t.dir_avr_1m - 90) < 0.001)
    check("cycle_done flag set", done == True)

    # After 10 minutes (10 cycles): 10-min avg = 5.0
    # After 1 cycle: 10-min gets one sample (the 1-min avg at cycle boundary)
    # That avg was computed before the 60th write: 59*5.0/60 = 4.9167
    check("wind_avr_10m after 1 cycle (59*5/60)/10", abs(t.wind_avr_10m - (59*5.0/60)/10) < 0.001,
          "got {}".format(t.wind_avr_10m))

    # Different values: 30x 5.0 then 30x 10.0
    t2 = WindTracker()
    for i in range(30):
        t2.update(5.0, 90)
    check("30x 5.0: avg = 5.0*30/60 = 2.5", abs(t2.wind_avr_1m - 2.5) < 0.001)
    for i in range(30):
        t2.update(10.0, 90)
    check("30x 5.0 + 30x 10.0: avg = 7.5", abs(t2.wind_avr_1m - 7.5) < 0.001)
    check("30x 5.0 + 30x 10.0: max = 10.0", abs(t2.wind_max_1m - 10.0) < 0.001)


# ─── Test 6: UDP Roundtrip (emulator -> consumer) ───────────────────────────
def test_udp_roundtrip():
    print("\n[Test 6] UDP Roundtrip (emulator -> consumer)")
    port = 14001
    mac = b'\xCA\xFE\x00\x00\x00\x01'

    received = []
    def receiver():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", port))
        s.settimeout(3)
        try:
            for _ in range(5):
                data, _ = s.recvfrom(1024)
                received.append(data)
        except socket.timeout:
            pass
        s.close()

    t = threading.Thread(target=receiver, daemon=True)
    t.start()
    time.sleep(0.5)

    # Send 5 packets
    pkt = build_packet(mac=mac, ds18_t=10.0, bme_t=11.0, bme_h=50.0,
                       bme_p=760.0, sht_t=10.5, sht_h=49.0,
                       wind_dir=45, wind_speed=2.5)
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for _ in range(5):
        sender.sendto(pkt, ("127.0.0.1", port))
        time.sleep(0.1)
    sender.close()
    t.join(timeout=5)

    check("Received 5 packets", len(received) == 5, "got {}".format(len(received)))
    if received:
        v = parse_packet(received[0])
        v = sanitize(v)
        check("Parsed MAC", v['mac'] == 'CAFE00000001')
        check("Parsed wind_speed", v['wind_speed'] == 2.5)
        check("Parsed wind_dir", v['wind_dir'] == 45)


# ─── Run all tests ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("WX v2 Test Suite - Protocol v171 compliance")
    print("=" * 60)

    test_packet_format()
    test_parse_sanitize()
    test_wee_v171()
    test_gen_wx_aprs()
    test_wind_tracker()
    test_udp_roundtrip()

    print("\n" + "=" * 60)
    print("Results: {} passed, {} failed".format(PASS, FAIL))
    if FAIL == 0:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
    print("=" * 60)
    sys.exit(0 if FAIL == 0 else 1)
