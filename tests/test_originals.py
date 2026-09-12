#!/usr/bin/env python3
"""
Test original WX scripts: feed UDP data, capture outputs, verify format.
"""
import subprocess, threading, time, socket, struct, os, sys, json, re, signal

WX_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WX_DIR)
from WX_emulator import build_packet

# Use non-standard ports to avoid conflicts
IN_PORT = 14001   # input (from emulator)
OUT_PORT = 14002  # output (for WX_2_WEE)

# Patch ports in source by creating temp copies
def make_temp_copy(src, dst, port_replacements):
    with open(src, 'r') as f:
        code = f.read()
    for old, new in port_replacements:
        code = code.replace(old, new)
    # Add timeout-based exit after N packets (insert a counter)
    with open(dst, 'w') as f:
        f.write(code)

def send_burst(port, count=65, interval=0.5, wind_dir=90, wind_speed=3.0):
    """Send count packets to port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    pkt = build_packet(ds18_t=15.0, bme_t=16.0, bme_h=55.0, bme_p=755.0,
                       sht_t=16.5, sht_h=54.0, wind_dir=wind_dir, wind_speed=wind_speed)
    for i in range(count):
        sock.sendto(pkt, ('127.0.0.1', port))
        if i < count - 1:
            time.sleep(interval)
    sock.close()
    return count

# --- TEST 1: Gen_WX.py ---
def test_gen_wx():
    print("\n=== TEST Gen_WX.py ===")
    # Ensure /tmp exists
    tmp_dir = WX_DIR + r"\\tmp_test"
    if not os.path.exists(tmp_dir):
        os.makedirs(tmp_dir)
    
    wx_file = os.path.join(tmp_dir, "WX.txt").replace("\\", "/")
    hum_file = os.path.join(tmp_dir, "WX_hum.txt").replace("\\", "/")
    hyb_file = os.path.join(tmp_dir, "WX_hyb.txt").replace("\\", "/")
    
    # Create temp copy with modified paths and port
    src = os.path.join(WX_DIR, "Gen_WX.py")
    tmp_script = os.path.join(WX_DIR, "_tmp_gen_wx.py")
    
    with open(src, 'r') as f:
        code = f.read()
    # Replace paths
    code = code.replace('"/tmp/WX.txt"', '"' + wx_file + '"')
    code = code.replace('"/tmp/WX_hum.txt"', '"' + hum_file + '"')
    code = code.replace('"/tmp/WX_hybridfile"', '"' + hyb_file + '"')
    code = code.replace('"/tmp/WX_hyb.txt"', '"' + hyb_file + '"')
    # Replace port
    code = code.replace('localPort = 4001', 'localPort = {}'.format(IN_PORT))
    # Inject packet counter into while loop + exit after 65 packets
    code = code.replace('while(1):', '''
import sys
_pkt_count = 0
while(1):
    _pkt_count += 1
    if _pkt_count >= 65:
        UDPServerSocket.close()
        sys.exit(0)
''')
    # Remove the broken udp_socket.close() at end
    code = code.replace('udp_socket.close()', 'pass')
    
    with open(tmp_script, 'w') as f:
        f.write(code)
    
    # Run in background
    proc = subprocess.Popen([sys.executable, tmp_script],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(2)  # Wait for bind
    
    # Send 65 packets (60 for 1-min cycle + 5 extra)
    send_burst(IN_PORT, count=65, interval=0.3)
    
    # Wait for script to process and exit
    try:
        out, err = proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
    
    output = out.decode('utf-8', errors='replace') if out else ''
    errors = err.decode('utf-8', errors='replace') if err else ''
    
    # Check output files
    results = {}
    for name, path in [("WX", wx_file), ("Hum", hum_file), ("Hyb", hyb_file)]:
        if os.path.exists(path):
            with open(path) as f:
                results[name] = f.read()
        else:
            results[name] = None
    
    # Cleanup
    try: os.remove(tmp_script)
    except: pass
    
    # Verify
    print("  Stdout (last 200):")
    print("  " + output[-200:].replace('\n', '\n  '))
    if errors:
        print("  Stderr (last 200):")
        print("  " + errors[-200:].replace('\n', '\n  '))
    
    for name, content in results.items():
        if content:
            print("  [{}] {}".format(name, content[:100]))
        else:
            print("  [{}] NOT FOUND".format(name))
    
    # Validate WX format
    if results["WX"]:
        wx = results["WX"]
        # Expected: !5556.34N/03758.45E_c090s007g007t059r...p...P...h54b10064Shchyolkovo WX station
        assert wx.startswith("!5556.34N/03758.45E_"), "WX format error: " + wx
        assert "_c" in wx, "Missing direction in WX"
        assert "s" in wx, "Missing speed in WX"
        assert "g" in wx, "Missing gust in WX"
        assert "t" in wx, "Missing temp in WX"
        assert "h" in wx, "Missing humidity in WX"
        assert "b" in wx, "Missing pressure in WX"
        assert "Shchyolkovo WX station" in wx, "Missing comment"
        print("  [VALID] WX format OK")
    
    if results["Hum"]:
        hum = results["Hum"]
        assert hum.startswith(":="), "Human format should start with :="
        assert "Temperature =>" in hum
        assert "Wind =>" in hum
        assert "Gust =>" in hum
        assert "Humidity =>" in hum
        assert "Pressure =>" in hum
        print("  [VALID] Human format OK")
    
    if results["Hyb"]:
        hyb = results["Hyb"]
        assert hyb.startswith("!5556.34N/03758.45E_"), "Hybrid format error"
        assert "Temperature =>" in hyb
        print("  [VALID] Hybrid format OK")
    
    # Cleanup temp dir
    for f in [wx_file, hum_file, hyb_file]:
        try: os.remove(f.replace('/', '\\'))
        except: pass
    try: os.rmdir(tmp_dir)
    except: pass
    
    print("  PASS")
    return results

# --- TEST 2: WX_2_WEE.py ---
def test_wx2wee():
    print("\n=== TEST WX_2_WEE.py ===")
    
    src = os.path.join(WX_DIR, "WX_2_WEE.py")
    tmp_script = os.path.join(WX_DIR, "_tmp_wx2wee.py")
    
    with open(src, 'r') as f:
        code = f.read()
    # Replace ports
    code = code.replace('localPort = 4001', 'localPort = {}'.format(IN_PORT))
    code = code.replace('WeeWX_Port = 4002', 'WeeWX_Port = {}'.format(OUT_PORT))
    code = code.replace('WeeWX_IP = "127.0.0.1"', 'WeeWX_IP = "127.0.0.1"')
    # Add exit after N seconds
    code = code.replace('udp_socket.close()', '''
    time.sleep(2)
    UDPServerSocket.close()
    WeeWXServerSocket.close()
    sys.exit(0)
''')
    code = 'import sys\n' + code
    
    with open(tmp_script, 'w') as f:
        f.write(code)
    
    # Listen on OUT_PORT to capture JSON
    received_json = []
    def listener():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('127.0.0.1', OUT_PORT))
        sock.settimeout(15)
        try:
            while True:
                data, addr = sock.recvfrom(4096)
                try:
                    received_json.append(json.loads(data.decode()))
                except:
                    received_json.append(data.decode())
        except socket.timeout:
            pass
        finally:
            sock.close()
    
    t = threading.Thread(target=listener, daemon=True)
    t.start()
    time.sleep(1)
    
    # Run script
    proc = subprocess.Popen([sys.executable, tmp_script],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(2)
    
    # Send 65 packets
    send_burst(IN_PORT, count=65, interval=0.3)
    
    # Wait
    time.sleep(15)
    try:
        proc.kill()
    except: pass
    out, err = proc.communicate()
    
    t.join(timeout=5)
    
    # Cleanup
    try: os.remove(tmp_script)
    except: pass
    
    output = out.decode('utf-8', errors='replace') if out else ''
    errors = err.decode('utf-8', errors='replace') if err else ''
    
    print("  Received {} JSON messages".format(len(received_json)))
    
    # Categorize
    obs_st = [m for m in received_json if isinstance(m, dict) and m.get('type') == 'obs_st']
    obs_air = [m for m in received_json if isinstance(m, dict) and m.get('type') == 'obs_air']
    rapid_wind = [m for m in received_json if isinstance(m, dict) and m.get('type') == 'rapid_wind']
    
    print("  obs_st: {}, obs_air: {}, rapid_wind: {}".format(
        len(obs_st), len(obs_air), len(rapid_wind)))
    
    if obs_st:
        print("  [obs_st sample] {}".format(json.dumps(obs_st[0])[:150]))
    if obs_air:
        print("  [obs_air sample] {}".format(json.dumps(obs_air[0])[:150]))
    if rapid_wind:
        print("  [rapid_wind sample] {}".format(json.dumps(rapid_wind[0])[:150]))
    
    if errors:
        print("  Stderr: " + errors[-200:].replace('\n', ' '))
    
    # Validate
    assert len(rapid_wind) > 0, "No rapid_wind received"
    assert len(obs_st) >= 1, "No obs_st received"
    assert len(obs_air) >= 1, "No obs_air received"
    
    # Validate obs_st structure (18 fields)
    if obs_st:
        fields = obs_st[0]['obs'][0]
        assert len(fields) == 18, "obs_st should have 18 fields, got {}".format(len(fields))
        print("  [VALID] obs_st: 18 fields")
    
    # Validate obs_air structure (8 fields)
    if obs_air:
        fields = obs_air[0]['obs'][0]
        assert len(fields) == 8, "obs_air should have 8 fields, got {}".format(len(fields))
        print("  [VALID] obs_air: 8 fields")
    
    # Validate rapid_wind (3 fields)
    if rapid_wind:
        # Check if it uses 'ob' or 'obs' key
        key = 'obs' if 'obs' in rapid_wind[0] else 'ob'
        fields = rapid_wind[0][key][0]
        assert len(fields) == 3, "rapid_wind should have 3 fields, got {}".format(len(fields))
        print("  [VALID] rapid_wind: 3 fields (key='{}')".format(key))
    
    print("  PASS")
    return {"obs_st": obs_st, "obs_air": obs_air, "rapid_wind": rapid_wind}

# --- TEST 3: WX_2_MQTT.py ---
def test_wx2mqtt():
    print("\n=== TEST WX_2_MQTT.py ===")
    print("  (Skipping - requires MQTT broker. Testing parse logic only.)")
    
    # Test that the module can be imported and parsed
    # (Full test requires a running MQTT broker at 192.168.113.121:1883)
    
    src = os.path.join(WX_DIR, "WX_2_MQTT.py")
    with open(src, 'r') as f:
        code = f.read()
    
    # Verify structure
    expected_topics = [
        "air_temperature", "air_pressure", "air_humidity",
        "wind_direction", "wind_speed", "wind_speed_max", "wind_speed_max_1m",
        "wind_direction_avr_1m", "wind_speed_avr_1m", "wind_speed_max_avr_1m",
        "wind_direction_avr_10m", "wind_speed_avr_10m", "wind_speed_max_avr_10m",
        "wind_direction_avr_1h", "wind_speed_avr_1h", "wind_speed_max_avr_1h"
    ]
    
    found_topics = []
    for t in expected_topics:
        if '"/sensor/' + t + '"' in code:
            found_topics.append(t)
    
    assert len(found_topics) == 16, "Expected 16 MQTT topics, found {}".format(len(found_topics))
    print("  Found 16 MQTT topics in source: OK")
    print("  PASS (structure only)")

# --- MAIN ---
if __name__ == "__main__":
    print("=" * 60)
    print("  Original WX Scripts - Output Format Test")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    tests = [
        ("Gen_WX.py", test_gen_wx),
        ("WX_2_WEE.py", test_wx2wee),
        ("WX_2_MQTT.py", test_wx2mqtt),
    ]
    
    for name, test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            failed += 1
            print("  FAIL: {}".format(e))
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("  Results: {} passed, {} failed".format(passed, failed))
    print("=" * 60)
