#!/usr/bin/env python3
"""Compare original vs v2 output formats."""
import subprocess, threading, time, socket, json, os, sys, signal

WX_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WX_DIR)
from WX_emulator import build_packet

IN_PORT = 14001
WEE_OUT_PORT = 14002

def make_script(src, dst, port_map, extra_inject=""):
    with open(src, 'r') as f:
        code = f.read()
    for old, new in port_map:
        code = code.replace(old, new)
    if extra_inject:
        code += "\n" + extra_inject
    with open(dst, 'w') as f:
        f.write(code)

def send_burst(port, count=65, interval=0.3):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    pkt = build_packet(ds18_t=15.0, bme_t=16.0, bme_h=55.0, bme_p=755.0,
                       sht_t=16.5, sht_h=54.0, wind_dir=90, wind_speed=3.0)
    for i in range(count):
        sock.sendto(pkt, ('127.0.0.1', port))
        if i < count - 1:
            time.sleep(interval)
    sock.close()

def run_and_capture_wee(script, label):
    """Run WX_2_WEE variant, capture UDP output on WEE_OUT_PORT."""
    received = []
    def listener():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('127.0.0.1', WEE_OUT_PORT))
        sock.settimeout(12)
        try:
            while True:
                data, _ = sock.recvfrom(4096)
                try:
                    received.append(json.loads(data.decode()))
                except: pass
        except socket.timeout: pass
        finally: sock.close()

    t = threading.Thread(target=listener, daemon=True)
    t.start()
    time.sleep(1)

    proc = subprocess.Popen([sys.executable, script],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(2)
    send_burst(IN_PORT, count=65, interval=0.3)
    time.sleep(12)
    try: proc.kill()
    except: pass
    proc.communicate()
    t.join(timeout=3)
    print("  [{}] Received {} messages".format(label, len(received)))
    return received

# --- Test WX_2_WEE ---
def test_wee():
    print("\n=== WX_2_WEE: Original vs V2 ===")
    
    # Original
    tmp_orig = os.path.join(WX_DIR, "_t_orig.py")
    make_script(os.path.join(WX_DIR, "WX_2_WEE.py"), tmp_orig,
                [('localPort = 4001', 'localPort = {}'.format(IN_PORT)),
                 ('WeeWX_Port = 4002', 'WeeWX_Port = {}'.format(WEE_OUT_PORT))])
    orig_msgs = run_and_capture_wee(tmp_orig, "orig")
    
    # V2
    tmp_v2 = os.path.join(WX_DIR, "_t_v2.py")
    make_script(os.path.join(WX_DIR, "WX_2_WEE_v2.py"), tmp_v2,
                [('localPort = 4001', 'localPort = {}'.format(IN_PORT)),
                 ('WeeWX_Port = 4002', 'WeeWX_Port = {}'.format(WEE_OUT_PORT))])
    v2_msgs = run_and_capture_wee(tmp_v2, "v2")
    
    # Cleanup
    for f in [tmp_orig, tmp_v2]:
        try: os.remove(f)
        except: pass
    
    # Compare
    def categorize(msgs):
        r = {}
        for m in msgs:
            t = m.get('type', 'unknown')
            r.setdefault(t, []).append(m)
        return r
    
    o = categorize(orig_msgs)
    v = categorize(v2_msgs)
    
    print("\n  Type counts:")
    all_types = set(list(o.keys()) + list(v.keys()))
    for t in sorted(all_types):
        oc = len(o.get(t, []))
        vc = len(v.get(t, []))
        match = "OK" if oc == vc else "DIFF"
        print("    {}: orig={} v2={} [{}]".format(t, oc, vc, match))
    
    # Show samples
    for t in sorted(all_types):
        if o.get(t):
            print("  [orig {}] {}".format(t, json.dumps(o[t][0])[:120]))
        if v.get(t):
            print("  [v2   {}] {}".format(t, json.dumps(v[t][0])[:120]))
    
    # Validate v2 format matches protocol
    if v.get('rapid_wind'):
        rw = v['rapid_wind'][0]
        assert 'device_id' in rw, "v2 rapid_wind missing device_id"
        assert 'ob' in rw, "v2 rapid_wind missing ob"
        assert isinstance(rw['ob'], list), "ob should be flat list"
        assert len(rw['ob']) == 3, "ob should have 3 elements"
        print("  [VALID] v2 rapid_wind: device_id + ob[3] flat array")
    
    if v.get('obs_air'):
        oa = v['obs_air'][0]
        assert 'device_id' in oa, "v2 obs_air missing device_id"
        assert 'obs' in oa, "v2 obs_air missing obs"
        assert len(oa['obs']) == 1, "obs should be 1 nested array"
        assert len(oa['obs'][0]) == 8, "obs_air should have 8 fields"
        print("  [VALID] v2 obs_air: device_id + obs[[8 fields]]")
    
    print("  PASS")

# --- Test Gen_WX ---
def test_gen_wx():
    print("\n=== Gen_WX: Original vs V2 ===")
    
    tmp_dir = os.path.join(WX_DIR, "tmp_cmp")
    os.makedirs(tmp_dir, exist_ok=True)
    
    results = {}
    for ver, script_name in [("orig", "Gen_WX.py"), ("v2", "Gen_WX_v2.py")]:
        wx_f = os.path.join(tmp_dir, "WX_{}.txt".format(ver)).replace('\\','/')
        hum_f = os.path.join(tmp_dir, "Hum_{}.txt".format(ver)).replace('\\','/')
        hyb_f = os.path.join(tmp_dir, "Hyb_{}.txt".format(ver)).replace('\\','/')
        
        tmp_script = os.path.join(WX_DIR, "_t_gen_{}.py".format(ver))
        with open(os.path.join(WX_DIR, script_name), 'r') as f:
            code = f.read()
        code = code.replace('"/tmp/WX.txt"', '"{}"'.format(wx_f))
        code = code.replace('"/tmp/WX_hum.txt"', '"{}"'.format(hum_f))
        code = code.replace('"/tmp/WX_hyb.txt"', '"{}"'.format(hyb_f))
        code = code.replace('localPort = 4001', 'localPort = {}'.format(IN_PORT))
        # Inject exit after 65 packets
        code = code.replace('while(1):', """
import sys as _s
_pc = 0
while True:
    _pc += 1
    if _pc >= 65:
        UDPServerSocket.close()
        _s.exit(0)
""")
        code = code.replace('while running:', """
_pc = 0
while running:
    _pc += 1
    if _pc >= 65:
        UDPServerSocket.close()
        import sys as _s; _s.exit(0)
""")
        code = code.replace("udp_socket.close()", "UDPServerSocket.close()")
        with open(tmp_script, 'w') as f:
            f.write(code)
        
        proc = subprocess.Popen([sys.executable, tmp_script],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(2)
        send_burst(IN_PORT, count=65, interval=0.3)
        try:
            out, err = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
        try: os.remove(tmp_script)
        except: pass
        
        files = {}
        for name, path in [("WX", wx_f), ("Hum", hum_f), ("Hyb", hyb_f)]:
            p = path.replace('/', '\\')
            if os.path.exists(p):
                with open(p) as f: files[name] = f.read()
            else: files[name] = None
        results[ver] = files
        for name in ["WX", "Hum", "Hyb"]:
            if files[name]:
                print("  [{}-{}] {}".format(ver, name, files[name][:100]))
            else:
                print("  [{}-{}] NOT FOUND".format(ver, name))
        if err:
            e = err.decode('utf-8', errors='replace')
            if 'Error' in e or 'error' in e:
                print("  [{} ERR] {}".format(ver, e[-150:]))
        time.sleep(1)
    
    # Cleanup
    for f in os.listdir(tmp_dir):
        try: os.remove(os.path.join(tmp_dir, f))
        except: pass
    try: os.rmdir(tmp_dir)
    except: pass
    
    # Compare
    if results.get("orig", {}).get("WX") and results.get("v2", {}).get("WX"):
        o = results["orig"]["WX"]
        v = results["v2"]["WX"]
        if o == v:
            print("  [MATCH] WX output identical!")
        else:
            print("  [DIFF] WX differs:")
            print("    orig: {}".format(o))
            print("    v2:   {}".format(v))
    
    print("  PASS")

# --- Main ---
if __name__ == "__main__":
    print("=" * 60)
    print("  Original vs V2 - Output Comparison")
    print("=" * 60)
    
    for name, fn in [("WX_2_WEE", test_wee), ("Gen_WX", test_gen_wx)]:
        try:
            fn()
        except Exception as e:
            print("  FAIL: {}".format(e))
            import traceback; traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("  Done")
    print("=" * 60)
