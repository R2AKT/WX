# Weather Station

<p align="center">
  <img src="docs/logo.svg" width="120" height="120" alt="Project Logo"/>
</p>

<p align="center">
  <img src="docs/station.jpg" width="600" alt="Weather Station"/>
</p>

<p align="center">
  Self-contained weather station: Arduino + ENC28J60, multi-protocol output (APRS / MQTT / WeeWX)
</p>

<p align="center">
  <a href="README.ru.md">Русская версия</a>
</p>

---

## System Overview

```
┌───────────────────────────────────────────────────────────────────────┐
│  WEATHER STATION (Arduino Nano + ENC28J60)                            │
│                                                                       │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌────────┐  ┌────────┐        │
│  │ DS18B20 │  │ BME280  │  │ SHT31   │  │AS5600  │  │TLE4934 │        │
│  │(1-Wire) │  │(I2C)    │  │(I2C)    │  │(I2C)   │  │(GPIO)  │        │
│  └────┬────┘  └────┬────┘  └────┬────┘  └───┬────┘  └───┬────┘        │
│       │            │            │           │           │             │
│       └────────────┴────────────┴───────────┴───────────┘             │
│                                   │                                   │
│                              ┌────┴────┐                              │
│                              │ Arduino │ ← Timer1 ISR (1 Hz)          │
│                              │  Nano   │                              │
│                              └────┬────┘                              │
│                                   │                                   │
│                              ┌────┴────┐                              │
│                              │ENC28J60 │ → UDP broadcast :4001        │
│                              └────┬────┘                              │
└───────────────────────────────────┼───────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
                    ▼               ▼               ▼
              ┌───────────┐   ┌───────────┐   ┌───────────┐
              │  Gen_WX   │   │WX_2_MQTT  │   │WX_2_WEE   │
              │  (APRS)   │   │  (MQTT)   │   │ (WeeWX)   │
              └───────────┘   └───────────┘   └───────────┘
```

**All three Python services listen on the same UDP port 4001** and parse the same 36-byte binary packet. Each converts to its respective output format.

---

## Hardware

### Master (WX_MASTER)

| Component | Interface | Purpose |
|-----------|-----------|---------|
| Arduino Nano (ATmega328P) | - | Main controller |
| ENC28J60 | SPI | Ethernet (passive PoE) |
| DS18B20 | 1-Wire | Air temperature (Stevenson screen) |
| BME280 | I2C (0x76) | Atmospheric pressure (vented enclosure) |
| SHT31 | I2C (0x44) | Relative humidity (30s heater cycle) |
| AS5600 | I2C | Wind direction (magnetic, 14-bit) |
| TLE4934 | GPIO (interrupt) | Wind speed (Hall effect, 2 pulses/rev, 4 magnets) |

> **Wind speed sensor:** 4 neodymium magnets with alternating polarity are mounted on the anemometer cup. The TLE4934 generates 2 pulses per revolution. Alternating polarity ensures reliable rejection of false triggers at the switching threshold zone.

### Slave (WX_SLAVE)

| Component | Purpose |
|-----------|---------|
| Arduino Nano | LCD display controller |
| ENC28J60 | UDP receiver (same port 4001) |
| 1602 LCD (I2C) | Shows: MAC, T+P, H+W, Dir |

---

## Primary Data Sources

| Measurement | Source | Notes |
|-------------|--------|-------|
| Temperature | DS18B20 | In Stevenson screen |
| Humidity | SHT31 | 30s heater cycle (temperature ignored) |
| Pressure | BME280 | Atmospheric (vented enclosure) |
| Wind speed | TLE4934 | Hall sensor, 2 pulses/rev |
| Wind direction | AS5600 | Magnetic, 14-bit |

---

## UDP Protocol (36-byte binary)

Broadcast to `255.255.255.255:4001`, 1 Hz.

| Offset | Size | Type | Field |
|--------|------|------|-------|
| 0-5 | 6 | bytes | MAC address |
| 6-9 | 4 | float32 LE | DS18B20 Temperature (°C) ** [primary] |
| 10-13 | 4 | float32 LE | BME280 Temperature (°C) |
| 14-17 | 4 | float32 LE | BME280 Relative Humidity (%) |
| 18-21 | 4 | float32 LE | BME280 Pressure (mmHg) ** [primary] |
| 22-25 | 4 | float32 LE | SHT31 Temperature (°C) |
| 26-29 | 4 | float32 LE | SHT31 Relative Humidity (%) ** [primary] |
| 30-31 | 2 | int16 LE | Wind Direction (0-360°) |
| 32-35 | 4 | float32 LE | Wind Speed (m/s) |

### NaN / Error Encoding

| Sensor | Sentinel value |
|--------|---------------|
| Temperature (any) | -127.0 °C |
| Humidity (any) | 100.0 % → clamped to 99 |
| Pressure | 100.0 mmHg |
| Wind | 0 |

### Range Validation

| Field | Valid range |
|-------|-------------|
| Temperature | -50 … +50 °C |
| Pressure | 700 … 800 mmHg |
| Humidity | 0 … 99 % |
| Wind direction | 0 … 360° (values > 360 wrap to 0) |

---

## Software Components

| File | Version | Function |
|------|---------|----------|
| `WX_master.ino` | v0.6.0 | Arduino: reads sensors, sends UDP at 1 Hz |
| `WX_slave.ino` | v0.4.0 | Arduino: receives UDP, displays on LCD |
| `Gen_WX.py` | v0.6.0 | APRS weather reports (WX.txt, WX_hum.txt, WX_hyb.txt) |
| `WX_2_MQTT.py` | v0.5.0 | MQTT broker publisher (21 topics) |
| `WX_2_WEE.py` | v0.3.0 | WeeWX bridge (Tempest protocol v1.7.1) |
| `wx_common.py` | - | Shared module: packet parser, WindTracker, utilities |
| `WX_emulator.py` | - | UDP packet generator (for testing) |

---

## MQTT Output

Base topic: `WX_Station/`

### Sensor Data

| Topic | Type | Description |
|-------|------|-------------|
| `sensor/temperature` | float | Air temperature (°C, DS18B20) |
| `sensor/humidity` | float | Relative humidity (%, SHT31) |
| `sensor/pressure` | float | Barometric pressure (mmHg) |
| `sensor/wind_speed` | float | Current wind speed (m/s) |
| `sensor/wind_dir` | int | Current wind direction (°) |
| `sensor/wind_gust` | float | Instantaneous max wind (m/s) |
| `sensor/wind_avr_1m` | float | 1-min average (m/s) |
| `sensor/wind_max_1m` | float | 1-min max/gust (m/s) |
| `sensor/wind_avr_10m` | float | 10-min average (m/s) |
| `sensor/wind_max_10m` | float | 10-min max (m/s) |
| `sensor/wind_avr_1h` | float | 1-hour average (m/s) |
| `sensor/wind_max_1h` | float | 1-hour max (m/s) |
| `sensor/bme_temperature` | float | BME280 temperature (°C, reference) |
| `sensor/sht_temperature` | float | SHT31 temperature (°C, reference) |
| `sensor/bme_humidity` | float | BME280 humidity (% , reference) |
| `sensor/sht_humidity` | float | SHT31 humidity (% , primary) |

### Derived Values

| Topic | Type | Description |
|-------|------|-------------|
| `sensor/dew_point` | float | Dew point (°C, Magnus formula) |
| `sensor/wind_chill` | float | Wind chill (°C) |
| `sensor/pressure_trend_30m` | float | 30-min pressure trend (hPa) |
| `sensor/sensor_health` | JSON | `{status, temp_spread, hum_spread, online}` |
| `sensor/weather_prediction` | string | `stable` / `rain_likely` / `clearing` / `fog_possible` / `strong_wind` / `change_expected` |

### System

| Topic | Description |
|-------|-------------|
| `status` | Heartbeat / station status |

**Total: 21 topics.**

---

## WeeWX Integration (Tempest Protocol v1.7.1)

`WX_2_WEE.py` sends JSON to WeeWX (port 4002) using the WeatherFlow UDP protocol:

| Message type | Frequency | Fields |
|-------------|-----------|--------|
| `rapid_wind` | every 1 Hz | timestamp, wind speed (m/s), wind direction (°) |
| `obs_st` | every 1 min | 18 fields: wind avg/max/direction, pressure, temperature, humidity, lightning, battery, interval |
| `obs_air` | every 1 min | 8 fields: pressure, temperature, humidity, lightning, battery, interval |

### Key `weewx.conf` settings

```ini
[Station]
station_type = WeatherFlowUDP

[WeatherFlowUDP]
driver = user.weatherflowudp
udp_address = 127.0.0.1
udp_port = 4002
udp_timeout = 180
share_socket = true

[[sensor_map]]
outTemp = air_temperature.A8610A000101.obs_air
outHumidity = relative_humidity.A8610A000101.obs_air
pressure = station_pressure.A8610A000101.obs_air
windSpeed = wind_speed.A8610A000101.rapid_wind
windDir = wind_direction.A8610A000101.rapid_wind
```

---

## APRS Output (Gen_WX.py)

Three output files generated per 1-minute wind cycle:

| File | Format |
|------|--------|
| `WX.txt` | APRS microformat: `!lat/lon_cDDDsSSSgGGGtTTThHHbPPPPPCOMMENT` |
| `WX_hum.txt` | Human-readable: `:lat/lon_comment: Temperature, Wind, Humidity, Pressure` |
| `WX_hyb.txt` | Hybrid: APRS + human-readable in one message |

**Example (WX.txt):**
```
!5556.34N/03758.45E_c090s007g007t015h54b1006 shchyolkovo WX station
```

**Example (WX_hum.txt):**
```
:=5556.34N/03758.45E_Shchyolkovo WX: Temperature => 2.5 C; Wind => 3.2 m/s, E; Gust => 7.8 m/s; Humidity => 54 %; Pressure => 741 mm Hg
```

---

## File Structure

```
wx/
├── README.md
├── README.ru.md
├── LICENSE
├── Addendum.txt
├── docs/
│   ├── logo.svg
│   └── station.jpg
├── wx_common.py
├── Gen_WX.py
├── WX_2_MQTT.py
├── WX_2_WEE.py
├── WX_emulator.py
├── WX_master.ino
├── WX_slave.ino
├── weewx.conf
└── tests/
    ├── test_v171.py
    ├── test_calculations.py
    ├── test_mqtt_integration.py
    ├── test_integration.py
    ├── test_compare.py
    └── test_originals.py
```

---

## Installation

### 1. Arduino Master

1. Install **EtherCard** (JeeLabs) + **DallasTemperature** libraries
2. Open `WX_master.ino` in Arduino IDE
3. Configure network (DHCP or static IP)
4. Upload to Arduino Nano

### 2. Python Services

```bash
# Install dependencies
pip install paho-mqtt

# Run services (in separate terminals or as systemd services)
python Gen_WX.py         # APRS output
python WX_2_MQTT.py      # MQTT publisher
python WX_2_WEE.py       # WeeWX bridge
```

**Configuration** is at the top of each Python file (lat/lon, MQTT broker IP, file paths).

### 3. WeeWX

1. Install WeeWX 5.x with WeatherFlowUDP driver
2. Copy `weewx.conf` and adjust station parameters
3. Ensure port 4002 is free for `WX_2_WEE.py` to send to

### 4. Tests

```bash
cd tests
python test_v171.py           # Protocol compliance (73 tests)
python test_calculations.py   # Derived calculations
python test_mqtt_integration.py  # Full MQTT pipeline
```

---

## Wind Tracker Algorithm

`WindTracker` in `wx_common.py` maintains three levels of rolling statistics:

| Level | Samples | Source |
|-------|---------|--------|
| 1-minute | 60 raw samples (1 Hz) | Direct |
| 10-minute | 10 one-minute averages | From 1-min level |
| 1-hour | 6 ten-minute averages | From 10-min level |

- **Average** = sum / array length (includes zero-padded slots)
- **Max** = max of all samples in window
- **Average of max** = average of per-cycle maximums

Direction is tracked separately using vector averaging (not circular mean) for the 1-minute period, then propagated to longer periods.

---

## Derived Calculations

### Dew Point (Magnus Formula)

```
γ = ln(RH/100) + 17.67 × T / (243.5 + T)
T_dp = 243.5 × γ / (17.67 - γ)
```

### Wind Chill

Valid for T < 10 °C and V > 1.39 m/s:

```
V_kmh = V_ms × 3.6
T_wc = 13.12 + 0.6215×T - 11.37×(V_kmh^0.16) + 0.3965×T×(V_kmh^0.16)
```

### Pressure Trend (30-min)

```
Trend (hPa) = (P_current - P_avg_30min) × 1.33322
```

Rolling buffer: 60 samples (1-min avg) → 30-sample 30-min average.

### Weather Prediction (Heuristic)

| Condition | Output |
|-----------|--------|
| trend < -3 hPa AND RH > 80% | `rain_likely` |
| trend < -2 hPa | `change_expected` |
| trend > +3 hPa | `clearing` |
| (T - dp) < 3 °C AND T < 15 °C | `fog_possible` |
| Wind > 10 m/s | `strong_wind` |
| else | `stable` |

### Sensor Health

| Check | Warning threshold |
|-------|-------------------|
| Temperature spread (DS18 vs SHT31) | > 3 °C |
| Humidity spread (BME vs SHT31) | > 10 % |

Status: `ok` → `warning` → `offline` (NaN detected).

---

## License

[MIT](LICENSE) + [Addendum](Addendum.txt)

Copyright (c) 2024-2026 R2AKT
