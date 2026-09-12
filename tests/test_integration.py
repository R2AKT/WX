#!/usr/bin/env python3
"""Integration test: run WX_2_WEE_v2 with emulator, verify JSON output."""
import socket
import struct
import time
import threading
import subprocess
import sys
import os

def send_burst(port, count=5, interval=0.1):
    pkt = bytearray(36)
    pkt[0:6] = b'\xA8\x61\x0A\x00\x01\x01'
    struct.pack_into('<f', pkt, 6, 15.5)
    struct.pack_into('<f', pkt, 10, 16.2)
    struct.pack_into('<f', pkt, 14, 55.3)
    struct.pack_into('<f', pkt, 18, 755.0)
    struct.pack_into('<f', pkt, 22, 16.8)
    struct.pack_into('<f', pkt, 26, 54.6)
    struct.pack_into('<h', pkt, 30, 270)
    struct.pack_into('<f', pkt, 32, 3.2)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for i in range(count):
        s.sendto(bytes(pkt), ('127.0.0.1', port))
        time.sleep(interval)
    s.close()

if __name__ == "__main__":
    print("Starting WX_2_WEE_v2 integration test...")
    
    # Start WX_2_WEE_v2
    proc = subprocess.Popen(
        [sys.executable, '-u', 'WX_2_WEE_v2.py'],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, cwd=r'c:\wx'
    )
    time.sleep(2)
    
    # Send 5 packets
    send_burst(4001, count=5, interval=0.1)
    
    # Wait for output
    time.sleep(2)
    
    # Kill
    proc.terminate()
    try:
        out, _ = proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
    
    # Show relevant output lines
    print("\n--- WX_2_WEE_v2 Output (last 30 lines) ---")
    lines = out.strip().split('\n')
    for line in lines[-30:]:
        print(line)
    
    # Verify protocol structure in output
    import json
    found_rapid = False
    found_error = False
    for line in lines:
        if "Rapid Wind" in line:
            found_rapid = True
            # Extract JSON
            json_str = line.split("Rapid Wind: ")[1].strip()
            data = json.loads(json_str)
            assert "serial_number" in data, "Missing serial_number"
            assert "hub_sn" in data, "Missing hub_sn"
            assert data["type"] == "rapid_wind"
            assert len(data["ob"]) == 3, "ob should be flat with 3 elements"
            assert isinstance(data["ob"][0], int), "ob[0] should be int"
            print("\n[OK] rapid_wind protocol verified: {}" .format(json.dumps(data, indent=2)))
        if "Error" in line or "Exception" in line or "Traceback" in line:
            found_error = True
            print("\n[FAIL] Found error in output: " + line)
    
    if not found_rapid:
        print("\n[FAIL] No rapid_wind output found")
    if not found_error:
        print("\n[OK] No errors in output")
    
    print("\nIntegration test complete.")
