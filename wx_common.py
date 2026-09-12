#!/usr/bin/env python3
"""Shared WX protocol module - parsing, sanitization, wind tracking."""
import struct
import math


def parse_packet(data):
    """Parse 36-byte binary UDP packet. Returns dict of sensor values."""
    return {
        'mac': data[0:6].hex().upper(),
        'ds18_t': struct.unpack('<f', data[6:10])[0],
        'bme_t': struct.unpack('<f', data[10:14])[0],
        'bme_h': struct.unpack('<f', data[14:18])[0],
        'bme_p': struct.unpack('<f', data[18:22])[0],
        'sht_t': struct.unpack('<f', data[22:26])[0],
        'sht_h': struct.unpack('<f', data[26:30])[0],
        'wind_dir': struct.unpack('<h', data[30:32])[0],
        'wind_speed': struct.unpack('<f', data[32:36])[0],
    }


def sanitize(v):
    """Apply NaN check and range correction to all sensor values."""
    # NaN replacements (same order as original)
    if math.isnan(v['wind_speed']):
        v['wind_speed'] = 0
    if math.isnan(v['bme_h']):
        v['bme_h'] = 100
    if math.isnan(v['bme_t']):
        v['bme_t'] = -127
    if math.isnan(v['bme_p']):
        v['bme_p'] = 100
    if math.isnan(v['sht_t']):
        v['sht_t'] = -127
    if math.isnan(v['sht_h']):
        v['sht_h'] = 100
    if math.isnan(v['ds18_t']):
        v['ds18_t'] = -127

    # Range corrections
    if v['wind_dir'] > 360 or v['wind_dir'] < 0:
        v['wind_dir'] = 0
    if v['bme_h'] >= 99:
        v['bme_h'] = 99
    if v['sht_h'] >= 99:
        v['sht_h'] = 99

    return v


def wind_direction_str(deg):
    """32-point compass direction (matches original Gen_WX.py exactly)."""
    if ((deg > 355 and deg <= 360) or (deg >= 0 and deg < 6)):
        return "N"
    elif 6 <= deg < 16: return "NtE"
    elif 16 <= deg < 27: return "NNE"
    elif 27 <= deg < 39: return "NEtN"
    elif 39 <= deg < 51: return "NE"
    elif 51 <= deg < 62: return "NEtE"
    elif 62 <= deg < 73: return "ENE"
    elif 73 <= deg < 84: return "EtN"
    elif 84 <= deg < 95: return "E"
    elif 95 <= deg < 106: return "EtS"
    elif 106 <= deg < 118: return "ESE"
    elif 118 <= deg < 130: return "SEtE"
    elif 130 <= deg < 141: return "SE"
    elif 141 <= deg < 152: return "SEtS"
    elif 152 <= deg < 163: return "SSE"
    elif 163 <= deg < 174: return "StE"
    elif 174 <= deg < 185: return "S"
    elif 185 <= deg < 196: return "StW"
    elif 196 <= deg < 208: return "SSW"
    elif 208 <= deg < 219: return "SWtS"
    elif 219 <= deg < 231: return "SW"
    elif 231 <= deg < 243: return "SWtW"
    elif 243 <= deg < 254: return "WSW"
    elif 254 <= deg < 265: return "WtS"
    elif 265 <= deg < 276: return "W"
    elif 276 <= deg < 287: return "WtN"
    elif 287 <= deg < 298: return "WNW"
    elif 298 <= deg < 310: return "NWtW"
    elif 310 <= deg < 322: return "NW"
    elif 322 <= deg < 333: return "NWtN"
    elif 333 <= deg < 344: return "NNW"
    elif 344 <= deg < 355: return "NtW"
    else:
        return "N/A"


class WindTracker:
    """Rolling wind/direction tracker (1m, 10m, 1h).
    Matches original behavior exactly: divides by full array length."""

    def __init__(self):
        self.wind_max = 0
        self.wind_max_1m = 0
        self.wind_max_10m = 0
        self.wind_max_1h = 0
        self.wind_avr_max_1m = 0
        self.wind_avr_max_10m = 0
        self.wind_avr_max_1h = 0

        self.wind_index_1m = 0
        self.wind_array_1m = [0] * 60
        self.wind_index_10m = 0
        self.wind_array_10m = [0] * 10
        self.wind_index_1h = 0
        self.wind_array_1h = [0] * 6

        self.dir_index_1m = 0
        self.dir_array_1m = [0] * 60
        self.dir_index_10m = 0
        self.dir_array_10m = [0] * 10
        self.dir_index_1h = 0
        self.dir_array_1h = [0] * 6

        self.wind_avr_1m = 0
        self.wind_avr_10m = 0
        self.wind_avr_1h = 0
        self.dir_avr_1m = 0
        self.dir_avr_10m = 0
        self.dir_avr_1h = 0

    def update(self, wind_speed, wind_dir):
        """Feed one sample. Returns True if 1-min cycle completed."""
        cycle_done = False

        # Direction (original order)
        self.dir_array_1m[self.dir_index_1m] = wind_dir
        self.dir_index_1m += 1
        if self.dir_index_1m >= 60:
            self.dir_index_1m = 0
            cycle_done = True
            self.dir_array_10m[self.dir_index_10m] = self.dir_avr_1m
            self.dir_index_10m += 1
            if self.dir_index_10m >= 10:
                self.dir_index_10m = 0
                self.dir_array_1h[self.dir_index_1h] = self.dir_avr_10m
                self.dir_index_1h += 1
                if self.dir_index_1h >= 6:
                    self.dir_index_1h = 0

        self.dir_avr_1m = sum(self.dir_array_1m) / len(self.dir_array_1m)
        self.dir_avr_10m = sum(self.dir_array_10m) / len(self.dir_array_10m)
        self.dir_avr_1h = sum(self.dir_array_1h) / len(self.dir_array_1h)

        # Wind speed (original order)
        self.wind_array_1m[self.wind_index_1m] = wind_speed
        self.wind_index_1m += 1
        if self.wind_index_1m >= 60:
            self.wind_index_1m = 0
            self.wind_array_10m[self.wind_index_10m] = self.wind_avr_1m
            self.wind_index_10m += 1
            if self.wind_index_10m >= 10:
                self.wind_index_10m = 0
                self.wind_array_1h[self.wind_index_1h] = self.wind_avr_10m
                self.wind_index_1h += 1
                if self.wind_index_1h >= 6:
                    self.wind_index_1h = 0

        if self.wind_max < wind_speed:
            self.wind_max = wind_speed
        self.wind_max_1m = max(self.wind_array_1m)
        self.wind_max_10m = max(self.wind_array_10m)
        self.wind_max_1h = max(self.wind_array_1h)

        self.wind_avr_1m = sum(self.wind_array_1m) / len(self.wind_array_1m)
        self.wind_avr_10m = sum(self.wind_array_10m) / len(self.wind_array_10m)
        self.wind_avr_1h = sum(self.wind_array_1h) / len(self.wind_array_1h)

        if self.wind_avr_max_1m < self.wind_avr_1m:
            self.wind_avr_max_1m = self.wind_avr_1m
        if self.wind_avr_max_10m < self.wind_avr_10m:
            self.wind_avr_max_10m = self.wind_avr_10m
        if self.wind_avr_max_1h < self.wind_avr_1h:
            self.wind_avr_max_1h = self.wind_avr_1h

        return cycle_done

    def print_status(self, v):
        """Print status line (matches original format exactly)."""
        print("\n")
        print("\tTemperature (DS18) *C/*F: {:03.1f}/{:03.1f}".format(
            v['ds18_t'], v['ds18_t'] * 1.8 + 32))
        print("\tTemperature (BME) *C/*F: {:03.1f}/{:03.1f}".format(
            v['bme_t'], v['bme_t'] * 1.8 + 32))
        print("\tTemperature (SHT) *C/*F: {:03.1f}/{:03.1f}".format(
            v['sht_t'], v['sht_t'] * 1.8 + 32))
        print("\tHumidity (BME) %: {:02.1f}".format(v['bme_h']))
        print("\tHumidity (SHT) %: {:02.1f}".format(v['sht_h']))
        print("\tPlersure (BME) mmHg/hPa: {:03.0f}/{:04.0f}".format(
            v['bme_p'], v['bme_p'] * 1.3332))
        print("\tWind Direction Cur./Avr.(1m)/Avr.(10m)/Avr.(1h) *: {:.0f}/{:.0f}/{:.0f}/{:.0f}".format(
            v['wind_dir'], self.dir_avr_1m, self.dir_avr_10m, self.dir_avr_1h))
        print("\tWind Speed Cur./Avr.(1m)/Avr.(10m)/Avr.(1h) m/s: {:.1f}/{:.1f}/{:.1f}/{:.1f}".format(
            v['wind_speed'], self.wind_avr_1m, self.wind_avr_10m, self.wind_avr_1h))
        print("\tWind Speed Max./Max.(1m)/Max.(10m)/Max.(1h) m/s: {:.1f}/{:.1f}/{:.1f}/{:.1f}".format(
            self.wind_max, self.wind_max_1m, self.wind_max_10m, self.wind_max_1h))
        print("\tWind Speed Avr.max.(1m)/Avr.max.(10m)/Avr.max.(1h) m/s: {:.1f}/{:.1f}/{:.1f}".format(
            self.wind_avr_max_1m, self.wind_avr_max_10m, self.wind_avr_max_1h))
