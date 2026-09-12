#!/usr/bin/python3
#
# APRS weather service by R2AKT. Ver.0.6.0 - refactored
# Project - https://github.com/R2AKT/WX
#
import socket
import struct
import math
import sys
import signal
from wx_common import parse_packet, sanitize, wind_direction_str, WindTracker

#
MyLat = "5556.34N"
MyLon = "03758.45E"
MyWXComment = "Shchyolkovo WX station"
MyHumanWXComment = "Weather in Shchyolkovo"
MyHybridWXComment = "Weather in Shchyolkovo"

APRS_WX_file = "/tmp/WX.txt"
APRS_WX_humfile = "/tmp/WX_hum.txt"
APRS_WX_hybridfile = "/tmp/WX_hyb.txt"

localIP = "0.0.0.0"
localPort = 4001
bufferSize = 1024

MyLat = MyLat.upper()
MyLon = MyLon.upper()

tracker = WindTracker()
AprsDataReady = False

UDPServerSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
UDPServerSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
UDPServerSocket.bind((localIP, localPort))

running = True
def _shutdown(signum, frame):
    global running
    running = False
signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)

while running:
    clientMsg, clientIP = UDPServerSocket.recvfrom(bufferSize)

    if clientMsg[:4] != b'ASCI' and len(clientMsg) >= 36:
        v = parse_packet(clientMsg)
        v = sanitize(v)

        cycle_done = tracker.update(v['wind_speed'], v['wind_dir'])
        if cycle_done:
            AprsDataReady = True

        tracker.print_status(v)

        if AprsDataReady:
            ## Value check
            print("\nCheck sersor value...")

            if (v['bme_p'] > 800) or (v['bme_p'] < 700):
                BME_P1_WX_formated = "....."
                BME_P1_Human_formated = "n/a"
                print("Plesure sensor ERROR!")
            else:
                BME_P1_WX_formated = "{:05.0f}".format(v['bme_p'] * 1.3332 * 10)
                BME_P1_Human_formated = "{:.0f}".format(v['bme_p'])

            if (v['ds18_t'] > 50) or (v['ds18_t'] < -50):
                DS18_T1_WX_formated = "..."
                DS18_T1_Human_formated = "n/a"
                print("Temperature sensor ERROR!")
            else:
                DS18_T1_WX_formated = "{:03.0f}".format(v['ds18_t'] * 1.8 + 32)
                DS18_T1_Human_formated = "{:.1f}".format(v['ds18_t'])

            if (v['sht_h'] >= 99):
                SHT_H1_WX_formated = ".."
                SHT_H1_Human_formated = "n/a"
                print("Humidity sensor ERROR!")
            else:
                SHT_H1_WX_formated = "{:02.0f}".format(v['sht_h'])
                SHT_H1_Human_formated = "{:.0f}".format(v['sht_h'])

            Wind_dir_str = wind_direction_str(tracker.dir_avr_1m)

            print("\nGenarate WX, Human and hybrid WF file...")

            # WX format
            wx_line = "!{}/{}_c{:03.0f}s{:03.0f}g{:03.0f}t{}r...p...P...h{}b{}{}".format(
                MyLat, MyLon,
                tracker.dir_avr_1m,
                tracker.wind_avr_1m * 2.2369362920544025,
                tracker.wind_max_1m * 2.2369362920544025,
                DS18_T1_WX_formated,
                SHT_H1_WX_formated,
                BME_P1_WX_formated,
                MyWXComment)
            print("WX File: " + wx_line)
            with open(APRS_WX_file, 'w') as f:
                f.write(wx_line)

            # Human format
            hum_line = ":={}/{}_{}: Temperature => {} C; Wind => {:.1f} m/s, {}; Gust => {:.1f} m/s; Humidity => {} %; Pressure => {} mmHg".format(
                MyLat, MyLon, MyHumanWXComment,
                DS18_T1_Human_formated,
                tracker.wind_avr_1m,
                Wind_dir_str,
                tracker.wind_max_1m,
                SHT_H1_Human_formated,
                BME_P1_Human_formated)
            print("Human WX File: " + hum_line)
            with open(APRS_WX_humfile, 'w') as f:
                f.write(hum_line)

            # Hybrid format
            hyb_line = "!{}/{}_c{:03.0f}s{:03.0f}g{:03.0f}t{}r...p...P...h{}b{}{}: Temperature => {} C; Wind => {:.1f} m/s, {}; Gust => {:.1f} m/s; Humidity => {} %; Pressure => {} mmHg".format(
                MyLat, MyLon,
                tracker.dir_avr_1m,
                tracker.wind_avr_1m * 2.2369362920544025,
                tracker.wind_max_1m * 2.2369362920544025,
                DS18_T1_WX_formated,
                SHT_H1_WX_formated,
                BME_P1_WX_formated,
                MyHybridWXComment,
                DS18_T1_Human_formated,
                tracker.wind_avr_1m,
                Wind_dir_str,
                tracker.wind_max_1m,
                SHT_H1_Human_formated,
                BME_P1_Human_formated)
            print("Hybrid WX File: " + hyb_line)
            with open(APRS_WX_hybridfile, 'w') as f:
                f.write(hyb_line)

            print("...OK")
            AprsDataReady = False

UDPServerSocket.close()
