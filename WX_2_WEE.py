#!/usr/bin/python3
#
# Weather to WeeWX service by R2AKT. Ver.0.3.0 - refactored
# Project - https://github.com/R2AKT/WX
# Protocol: WeatherFlow Tempest UDP v171 (FINAL)
# https://weatherflow.github.io/Tempest/api/udp/v171/
#
import socket
import json
import time
import calendar
import sys
import signal
from wx_common import parse_packet, sanitize, WindTracker

localIP = "0.0.0.0"
localPort = 4001
bufferSize = 1024

WeeWX_IP = "127.0.0.1"
WeeWX_Port = 4002

# Constants (Tempest defaults)
Wind_Interval = 1
Illuminance = 0
UV = 0.0
Sun_Radiation = 0
Precipitation = 0
Lightning_Distance = 0
Lightning_Count = 0
Battery = 4.999
Report_Interval_Minutes = 1
Firmware_Revision = 171

tracker = WindTracker()
CycleTime = 0
UTCTime = 0
serial_number = ""
hub_sn = ""

UDPServerSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
UDPServerSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
UDPServerSocket.bind((localIP, localPort))

WeeWXServerSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

print("Listen UDP client up and listening...")
print("Send UDP server up and ready...")

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

        # Set serial identifiers from MAC (first packet only)
        if not serial_number:
            serial_number = v['mac'].upper()
            hub_sn = v['mac'].upper()

        tracker.update(v['wind_speed'], v['wind_dir'])
        tracker.print_status(v)

        # Value validation
        if (v['bme_p'] > 800) or (v['bme_p'] < 700):
            v['bme_p'] = 765
        if (v['ds18_t'] > 50) or (v['ds18_t'] < -50):
            v['ds18_t'] = 0
        if (v['bme_h'] >= 99):
            v['bme_h'] = 0
        if (v['sht_h'] >= 99):
            v['sht_h'] = 0

        UTCTime = calendar.timegm(time.gmtime())
        CycleTime += 1

        # Periodic observations (every 60 seconds)
        if CycleTime >= (Report_Interval_Minutes * 60):
            # Observation (Tempest) [type = obs_st] - 18 fields
            WXData = {
                "serial_number": serial_number,
                "type": "obs_st",
                "hub_sn": hub_sn,
                "obs": [[
                    UTCTime,                                    # 0  Time Epoch Seconds
                    float("{:.3f}".format(tracker.wind_avr_1m)),# 1  Wind Lull m/s
                    float("{:.3f}".format(tracker.wind_avr_10m)),# 2 Wind Avg m/s
                    float("{:.3f}".format(tracker.wind_max_1m)),# 3  Wind Gust m/s
                    int(tracker.dir_avr_1m),                    # 4  Wind Direction Deg
                    Wind_Interval,                               # 5  Wind Sample Interval s
                    float("{:.3f}".format(v['bme_p'] * 1.33322)),# 6 Station Pressure MB
                    float("{:.3f}".format(v['ds18_t'])),        # 7  Air Temperature C
                    float("{:.3f}".format(v['sht_h'])),         # 8  Relative Humidity %
                    Illuminance,                                 # 9  Illuminance Lux
                    float("{:.2f}".format(UV)),                  # 10 UV Index
                    Sun_Radiation,                               # 11 Solar Radiation W/m^2
                    float("{:.6f}".format(0.0)),                 # 12 Rain mm
                    Precipitation,                               # 13 Precipitation Type
                    Lightning_Distance,                           # 14 Lightning Strike Avg Dist
                    Lightning_Count,                              # 15 Lightning Strike Count
                    float("{:.3f}".format(Battery)),             # 16 Battery Volts
                    Report_Interval_Minutes                       # 17 Report Interval Min
                ]],
                "firmware_revision": Firmware_Revision
            }
            jsonWXData = json.dumps(WXData)
            print("\t\t Tempest: ", jsonWXData)
            WeeWXServerSocket.sendto(jsonWXData.encode(), (WeeWX_IP, WeeWX_Port))

            # Observation (AIR) [type = obs_air] - 8 fields
            WXData = {
                "serial_number": serial_number,
                "type": "obs_air",
                "hub_sn": hub_sn,
                "obs": [[
                    UTCTime,                                    # 0  Time Epoch Seconds
                    float("{:.3f}".format(v['bme_p'] * 1.33322)),# 1 Station Pressure MB
                    float("{:.3f}".format(v['ds18_t'])),        # 2  Air Temperature C
                    float("{:.3f}".format(v['sht_h'])),         # 3  Relative Humidity %
                    Lightning_Count,                             # 4  Lightning Strike Count
                    Lightning_Distance,                           # 5  Lightning Strike Avg Dist
                    float("{:.3f}".format(Battery)),             # 6  Battery
                    Report_Interval_Minutes                       # 7  Report Interval Minutes
                ]],
                "firmware_revision": Firmware_Revision
            }
            jsonWXData = json.dumps(WXData)
            print("\t\t AIR: ", jsonWXData)
            WeeWXServerSocket.sendto(jsonWXData.encode(), (WeeWX_IP, WeeWX_Port))

            CycleTime = 0

        # Rapid Wind [type = rapid_wind] - every packet, FLAT ob array
        WXData = {
            "serial_number": serial_number,
            "type": "rapid_wind",
            "hub_sn": hub_sn,
            "ob": [
                UTCTime,
                float("{:.3f}".format(v['wind_speed'])),
                int(v['wind_dir'])
            ]
        }
        jsonWXData = json.dumps(WXData)
        print("\t\t Rapid Wind: ", jsonWXData)
        WeeWXServerSocket.sendto(jsonWXData.encode(), (WeeWX_IP, WeeWX_Port))

UDPServerSocket.close()
WeeWXServerSocket.close()
