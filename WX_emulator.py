#!/usr/bin/env python3
"""
WX Emulator - sends 36-byte binary UDP packets simulating Arduino weather station.
Usage:
  python WX_emulator.py                    # broadcast 255.255.255.255:4001, 60 packets
  python WX_emulator.py 127.0.0.1 4001 --count 60 --interval 1
"""
import socket
import struct
import time
import sys
import argparse

def build_packet(mac=b'\xA8\x61\x0A\x00\x01\x01',
                 ds18_t=15.0, bme_t=16.0, bme_h=55.0, bme_p=755.0,
                 sht_t=16.5, sht_h=54.0, wind_dir=90, wind_speed=2.0):
    """Build 36-byte binary packet."""
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

def run(dst_ip, dst_port, count=60, interval=1.0, mac=None):
    """Send `count` packets at `interval` seconds apart."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if mac is None:
        mac = b'\xA8\x61\x0A\x00\x01\x01'
    pkt = build_packet(mac=mac)
    for i in range(count):
        sock.sendto(pkt, (dst_ip, dst_port))
        if (i+1) % 10 == 0:
            print("  sent {}/{}".format(i+1, count))
        if i < count - 1:
            time.sleep(interval)
    sock.close()
    print("Done: {} packets to {}:{}".format(count, dst_ip, dst_port))

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("dst_ip", nargs="?", default="255.255.255.255")
    p.add_argument("dst_port", nargs="?", type=int, default=4001)
    p.add_argument("--count", type=int, default=60)
    p.add_argument("--interval", type=float, default=1.0)
    args = p.parse_args()
    run(args.dst_ip, args.dst_port, args.count, args.interval)
