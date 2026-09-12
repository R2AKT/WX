#!/usr/bin/python3
#
# Weather to MQTT service by R2AKT. Ver.0.5.0 - refactored
# Project - https://github.com/R2AKT/WX
#
import logging
import paho.mqtt.client as mqtt
import socket
import struct
import json
from datetime import datetime
import time
import calendar
import math
import sys
import signal
from wx_common import parse_packet, sanitize, WindTracker

logger = logging.getLogger("WX_2_MQTT")

localIP = "0.0.0.0"
localPort = 4001
bufferSize = 1024

MQTT_Host = "192.168.113.121"
MQTT_Port = 1883
MQTT_Keepalive = 60
MQTT_User = "wx2mqtt"
MQTT_Password = "97a9ad0254bbe0f7f0145cef71093bc9"
MQTT_Client_ID = "WX-python-mqtt"
MQTT_Topic = "WX_Station"
MQTT_QOS = 0

tracker = WindTracker()
connected_flag = False

# --- Pressure tracker (for trend calculation) ---
PARRAY_SIZE = 60          # 1-minute pressure buffer
P30_SIZE = 30             # 30 one-minute averages = 30 minutes
pressure_1m = [0.0] * PARRAY_SIZE
pressure_1m_idx = 0
pressure_1m_count = 0
pressure_30m = [0.0] * P30_SIZE
pressure_30m_idx = 0
pressure_30m_count = 0

UDPServerSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
UDPServerSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
UDPServerSocket.bind((localIP, localPort))
logger.info("UDP server up and listening...")


def on_connect(client, userdata, flags, reason_code, properties):
    global connected_flag
    if reason_code == 0:
        print("MQTT connected!")
        logger.info("Connected with result code " + mqtt.connack_string(reason_code))
        connected_flag = True
        client.subscribe(MQTT_Topic, qos=MQTT_QOS)
    else:
        print("MQTT rejected!!")
        logger.error("Bad connection Returned code " + mqtt.connack_string(reason_code))
        connected_flag = False


def on_disconnect(client, userdata, reason_code):
    global connected_flag
    connected_flag = False
    print("MQTT disconnected!")
    logger.error("Disconnected with result code: %s", reason_code)
    while not connected_flag:
        time.sleep(3)
        try:
            client.reconnect()
            print("Reconnected!")
            return
        except Exception as err:
            logger.error("%s. Reconnect failed. Retrying...", err)


mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311, client_id=MQTT_Client_ID)
mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect
mqtt_client.loop_start()
logger.info("Connecting to MQTT broker " + MQTT_Host)
mqtt_client.username_pw_set(username=MQTT_User, password=MQTT_Password)
mqtt_client.connect(MQTT_Host, MQTT_Port, MQTT_Keepalive)

# Wait for connection
while not connected_flag:
    print("Wait MQTT response...")
    time.sleep(1)
print("Start Main Loop")

running = True
def _shutdown(signum, frame):
    global running
    running = False
signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)


def calc_dewpoint(temp_c, rh_pct):
    """Magnus formula. Returns dew point in °C."""
    if rh_pct <= 0 or rh_pct >= 100:
        return temp_c if rh_pct >= 100 else -99.0
    gamma = math.log(rh_pct / 100.0) + 17.67 * temp_c / (243.5 + temp_c)
    return 243.5 * gamma / (17.67 - gamma)


def calc_windchill(temp_c, wind_ms):
    """Wind chill index. Valid for T < 10°C, V > 1.39 m/s (5 km/h)."""
    if temp_c >= 10.0 or wind_ms < 1.39:
        return temp_c  # No wind chill effect
    v_kmh = wind_ms * 3.6
    return 13.12 + 0.6215 * temp_c - 11.37 * (v_kmh ** 0.16) + 0.3965 * temp_c * (v_kmh ** 0.16)


def update_pressure_tracker(p_mmhg):
    """Update rolling pressure arrays."""
    global pressure_1m_idx, pressure_1m_count, pressure_30m_idx, pressure_30m_count

    pressure_1m[pressure_1m_idx] = p_mmhg
    pressure_1m_idx += 1

    if pressure_1m_idx >= PARRAY_SIZE:
        # 1 minute complete — push average to 30-min array
        pressure_1m_idx = 0
        p_avg_1m = sum(pressure_1m) / PARRAY_SIZE
        pressure_30m[pressure_30m_idx] = p_avg_1m
        pressure_30m_idx += 1
        if pressure_30m_idx >= P30_SIZE:
            pressure_30m_idx = 0
            pressure_30m_count = P30_SIZE
        else:
            pressure_30m_count = pressure_30m_idx

    if pressure_1m_count < PARRAY_SIZE:
        pressure_1m_count += 1


def calc_pressure_trend_30m(p_current_mmhg):
    """Pressure trend in hPa over 30 minutes."""
    if pressure_30m_count == 0:
        return 0.0
    p_avg_30m = sum(pressure_30m[:pressure_30m_count]) / pressure_30m_count
    trend_mmhg = p_current_mmhg - p_avg_30m
    return round(trend_mmhg * 1.33322, 2)  # convert to hPa


def calc_sensor_health(v):
    """Sensor health check. Returns dict."""
    ds18_online = v['ds18_t'] != -127
    bme_online = v['bme_t'] != -127
    sht_online = v['sht_t'] != -127

    # Temperature spread (max deviation between online sensors)
    temps = []
    if ds18_online: temps.append(v['ds18_t'])
    if bme_online:  temps.append(v['bme_t'])
    if sht_online:  temps.append(v['sht_t'])
    temp_spread = (max(temps) - min(temps)) if len(temps) >= 2 else 0.0

    # Humidity spread
    hum_spread = 0.0
    if bme_online and sht_online and v['sht_h'] < 99:
        hum_spread = abs(v['bme_h'] - v['sht_h'])

    # Status
    if not (ds18_online and bme_online and sht_online):
        status = "offline"
    elif temp_spread > 3.0 or hum_spread > 10.0:
        status = "warning"
    else:
        status = "ok"

    return {
        "status": status,
        "temp_spread": round(temp_spread, 1),
        "hum_spread": round(hum_spread, 1),
        "ds18": ds18_online,
        "bme": bme_online,
        "sht": sht_online
    }


def calc_weather_prediction(v, p_trend_hpa, dewpoint):
    """Simple heuristic weather prediction."""
    temp = v['ds18_t']
    hum = v['sht_h']
    wind = v['wind_speed']

    if p_trend_hpa < -3.0 and hum > 80:
        return "rain_likely"
    elif p_trend_hpa < -2.0:
        return "change_expected"
    elif p_trend_hpa > 3.0:
        return "clearing"
    elif dewpoint > -90 and temp - dewpoint < 3.0 and temp < 15:
        return "fog_possible"
    elif wind > 10.0:
        return "strong_wind"
    else:
        return "stable"


while running:
    clientMsg, clientIP = UDPServerSocket.recvfrom(bufferSize)

    if clientMsg[:4] != b'ASCI' and len(clientMsg) >= 36:
        v = parse_packet(clientMsg)
        v = sanitize(v)

        tracker.update(v['wind_speed'], v['wind_dir'])
        tracker.print_status(v)

        # Value validation
        if (v['bme_p'] > 800) or (v['bme_p'] < 700):
            v['bme_p'] = 755
            print("Pressure sensor ERROR! Set Default...")
        if (v['ds18_t'] > 50) or (v['ds18_t'] < -50):
            v['ds18_t'] = 0
            print("Temperature sensor ERROR! Set Default...")
        if (v['sht_t'] > 50) or (v['sht_t'] < -50):
            v['sht_t'] = 0
            print("SHT Temperature sensor ERROR! Set Default...")
        if (v['bme_h'] > 99):
            v['bme_h'] = 0
            print("Humidity sensor ERROR! Set Default...")
        if (v['sht_h'] > 99):
            v['sht_h'] = 0
            print("SHT Humidity sensor ERROR! Set Default...")

        # Derived calculations
        update_pressure_tracker(v['bme_p'])
        dewpoint = calc_dewpoint(v['ds18_t'], v['sht_h'])
        windchill = calc_windchill(v['ds18_t'], v['wind_speed'])
        p_trend_30m = calc_pressure_trend_30m(v['bme_p'])
        health = calc_sensor_health(v)
        prediction = calc_weather_prediction(v, p_trend_30m, dewpoint)

        print("...OK")

        if connected_flag:
            print("Sending message to MQTT broker. Topic " + MQTT_Topic)
            # --- Standard sensor data ---
            mqtt_client.publish(MQTT_Topic + "/sensor/air_temperature", v['ds18_t'], qos=MQTT_QOS)
            mqtt_client.publish(MQTT_Topic + "/sensor/air_pressure", v['bme_p'], qos=MQTT_QOS)
            mqtt_client.publish(MQTT_Topic + "/sensor/air_humidity", v['sht_h'], qos=MQTT_QOS)
            mqtt_client.publish(MQTT_Topic + "/sensor/wind_direction", v['wind_dir'], qos=MQTT_QOS)
            mqtt_client.publish(MQTT_Topic + "/sensor/wind_speed", v['wind_speed'], qos=MQTT_QOS)
            # --- Wind statistics ---
            mqtt_client.publish(MQTT_Topic + "/sensor/wind_speed_max", tracker.wind_max, qos=MQTT_QOS)
            mqtt_client.publish(MQTT_Topic + "/sensor/wind_speed_max_1m", tracker.wind_max_1m, qos=MQTT_QOS)
            mqtt_client.publish(MQTT_Topic + "/sensor/wind_direction_avr_1m", tracker.dir_avr_1m, qos=MQTT_QOS)
            mqtt_client.publish(MQTT_Topic + "/sensor/wind_speed_avr_1m", tracker.wind_avr_1m, qos=MQTT_QOS)
            mqtt_client.publish(MQTT_Topic + "/sensor/wind_speed_max_avr_1m", tracker.wind_avr_max_1m, qos=MQTT_QOS)
            mqtt_client.publish(MQTT_Topic + "/sensor/wind_direction_avr_10m", tracker.dir_avr_10m, qos=MQTT_QOS)
            mqtt_client.publish(MQTT_Topic + "/sensor/wind_speed_avr_10m", tracker.wind_avr_10m, qos=MQTT_QOS)
            mqtt_client.publish(MQTT_Topic + "/sensor/wind_speed_max_avr_10m", tracker.wind_avr_max_10m, qos=MQTT_QOS)
            mqtt_client.publish(MQTT_Topic + "/sensor/wind_direction_avr_1h", tracker.dir_avr_1h, qos=MQTT_QOS)
            mqtt_client.publish(MQTT_Topic + "/sensor/wind_speed_avr_1h", tracker.wind_avr_1h, qos=MQTT_QOS)
            mqtt_client.publish(MQTT_Topic + "/sensor/wind_speed_max_avr_1h", tracker.wind_avr_max_1h, qos=MQTT_QOS)
            # --- Derived values (NEW) ---
            mqtt_client.publish(MQTT_Topic + "/sensor/dew_point", round(dewpoint, 1), qos=MQTT_QOS)
            mqtt_client.publish(MQTT_Topic + "/sensor/wind_chill", round(windchill, 1), qos=MQTT_QOS)
            mqtt_client.publish(MQTT_Topic + "/sensor/pressure_trend_30m", p_trend_30m, qos=MQTT_QOS)
            # --- System (NEW) ---
            mqtt_client.publish(MQTT_Topic + "/sensor/sensor_health", json.dumps(health), qos=MQTT_QOS)
            mqtt_client.publish(MQTT_Topic + "/sensor/weather_prediction", prediction, qos=MQTT_QOS)
        else:
            print("Skip sending message to MQTT broker!")

UDPServerSocket.close()
mqtt_client.loop_stop()
mqtt_client.disconnect()
