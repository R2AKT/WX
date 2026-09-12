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
┌─────────────────────────────────────────────────────────────────────┐
│                    WX_MASTER (Arduino Nano + ENC28J60)              │
│                                                                     │
│  Sensors:                                                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐   ┌────────┐  ┌────────┐  │
│  │ DS18B20  │  │ BME280   │  │ SHT31    │   │AS5600  │  │TLE4934 │  │
│  │ (1-Wire) │  │ (I2C)    │  │ (I2C)    │   │(I2C)   │  │(GPIO)  │  │
│  │  Temp    │  │ T, H, P  │  │ T, H     │   │ Wind   │  │ Wind   │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘   │ Dir    │  │ Speed  │  │
│       │              │             │        └───┬────┘  └───┬────┘  │
│       └──────────────┴─────────────┴────────────┴───────────┘       │
│                              │                                      │
│                    36-byte UDP packet (1 Hz)                        │
│                    Broadcast → 255.255.255.255:4001                 │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
    ┌─────────▼──────┐ ┌──────▼───────┐ ┌──────▼──────────┐
    │  Gen_WX.py     │ │WX_2_MQTT     │ │  WX_2_WEE.py    │
    │  (APRS files)  │ │  (21 topics) │ │  (Tempest v171) │
    └────────────────┘ └──────────────┘ └──────┬──────────┘
                                               │
                                    ┌──────────▼──────────┐
                                    │  WeeWX 5.2.0        │
                                    │  (WeatherFlowUDP)   │
                                    │  → Grafana/History  │
                                    └─────────────────────┘

    ┌─────────────────────────────────────────────┐
    │  WX_SLAVE (Arduino Nano + ENC28J60 + LCD)   │
    │  Receives UDP:4001, displays on 16x2 LCD    │
    └─────────────────────────────────────────────┘
```

---

## Hardware

### Master (WX_MASTER)

| Component | Interface | Purpose |
|-----------|-----------|---------|
| Arduino Nano (ATmega328P) | — | Main controller |
| ENC28J60 | SPI | Ethernet (passive PoE) |
| DS18B20 | 1-Wire | Air temperature (°C) |
| BME280 | I2C (0x76) | Temperature, Humidity, Pressure |
| SHT31 | I2C (0x44) | Temperature, Humidity (redundancy) |
| AS5600 | I2C | Wind direction (magnetic, 14-bit) |
| TLE4934 | GPIO (interrupt) | Wind speed (Hall effect, 360 pulses/rev) |

### Slave (WX_SLAVE)

| Component | Purpose |
|-----------|---------|
| Arduino Nano + ENC28J60 | UDP receiver |
| 16×2 LCD (I2C, PCF8574) | Local weather display |

### Python Host

- Raspberry Pi (or any Linux machine on the same network)
- Runs: `Gen_WX.py`, `WX_2_MQTT.py`, `WX_2_WEE.py`
- WeeWX 5.2.0 (optional)

---

## UDP Protocol (36-byte binary)

Broadcast to `255.255.255.255:4001`, 1 Hz.

| Offset | Size | Type | Field |
|--------|------|------|-------|
| 0–5 | 6 | bytes | MAC address |
| 6–9 | 4 | float32 LE | DS18B20 Temperature (°C) |
| 10–13 | 4 | float32 LE | BME280 Temperature (°C) |
| 14–17 | 4 | float32 LE | BME280 Relative Humidity (%) |
| 18–21 | 4 | float32 LE | BME280 Pressure (mmHg) |
| 22–25 | 4 | float32 LE | SHT31 Temperature (°C) |
| 26–29 | 4 | float32 LE | SHT31 Relative Humidity (%) |
| 30–31 | 2 | int16 LE | Wind Direction (0–360°) |
| 32–35 | 4 | float32 LE | Wind Speed (m/s) |

### NaN / Error Encoding

| Sensor | Sentinel value |
|--------|---------------|
| Temperature (any) | −127.0 °C |
| Humidity (any) | 100.0 % → clamped to 99 |
| Pressure | 100.0 mmHg |
| Wind | 0 |

### Valid Ranges (consumer-side validation)

| Field | Min | Max |
|-------|-----|-----|
| Temperature | −50 °C | +50 °C |
| Pressure | 700 mmHg | 800 mmHg |
| Humidity | 0 % | 99 % |
| Wind direction | 0° | 360° |

---

## Software

### File Structure

```
wx/
├── README.md
├── README.ru.md
├── LICENSE.txt
├── Addendum.txt
├── docs/
│   ├── logo.svg
│   └── station.jpg
├── wx_common.py              ← shared library (parser, sanitizer, WindTracker)
├── Gen_WX.py                 ← APRS generator
├── WX_2_MQTT.py              ← MQTT publisher (21 topics)
├── WX_2_WEE.py               ← WeeWX bridge (Tempest v1.7.1)
├── WX_emulator.py            ← UDP packet emulator (testing)
├── WX_master.ino             ← Arduino master sketch
├── WX_slave.ino              ← Arduino LCD slave sketch
├── weewx.conf                ← WeeWX configuration
└── tests/
    ├── test_v171.py          ← 73-test protocol suite
    ├── test_calculations.py  ← unit tests (dew point, wind chill, etc.)
    ├── test_mqtt_integration.py
    └── test_integration.py
```

### Component Versions

| File | Version | Role |
|------|---------|------|
| `wx_common.py` | — | Shared **library** (not standalone) |
| `Gen_WX.py`    | v0.6.0 | APRS file generator |
| `WX_2_MQTT.py`    | v0.5.0 | MQTT publisher |
| `WX_2_WEE.py`    | v0.3.0 | WeeWX bridge |
| `WX_master.ino`    | v0.6.0 | Arduino master |
| `WX_slave.ino`    | v0.4.0 | Arduino LCD slave |
| `WX_emulator.py`    | — | Testing utility |

### Refactoring Notes (v0.5→v0.6)

Original scripts refactored to fix:
- `udp_socket.close()` undefined variable → consistent naming
- `math.isnan()` on `int` → applied only to float fields
- `DataReady = True` (DEBUG override) → proper 60-second cycle
- `mqtt_client.loop_stop()` before main loop → moved after
- WeeWX: `rapid_wind` nested `[[...]]` → flat `[...]` (per v1.7.1)
- WeeWX: removed port 4002 `bind()` conflict → `sendto()` only
- Arduino: `ether.packetLoop()` missing in UDP mode (DHCP expiry)
- Arduino: SHT NaN → 0 (valid value!) → −127/100 sentinel
- Arduino: `sizeof(int)` non-portable → explicit byte operations
- Slave: parsed 28-byte protocol instead of 36-byte

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
| `sensor/bme_temperature` | float | BME280 temperature (°C) |
| `sensor/sht_temperature` | float | SHT31 temperature (°C) |
| `sensor/bme_humidity` | float | BME280 humidity (%) |
| `sensor/sht_humidity` | float | SHT31 humidity (%) |

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

`WX_2_WEE.py` sends WeatherFlow Tempest UDP JSON to WeeWX on `127.0.0.1:4002`.

| Message type | Interval | Format |
|--------------|----------|--------|
| `rapid_wind` | 1 Hz (every packet) | `ob: [ts, speed_m/s, dir_deg]` (flat) |
| `obs_st` | 60 s | 18 fields, `obs: [[...]]` |
| `obs_air` | 60 s | 8 fields, `obs: [[...]]` |

**Key `weewx.conf` settings:**

```ini
[DataSources]
    driver = user.WeatherFlowUDP
    UDPBindAddress = "127.0.0.1"
    UDPBindPort = 4002

[StdFrame]
    archive_interval = 60
```

Wind data: `rapid_wind` (live) → WeeWX `windSpeed`/`windDir` mappings.

---

## APRS Output

`Gen_WX.py` writes files to `/tmp/` (60-second cycle):

| File | Format |
|------|--------|
| `WX.txt` | APRS mic-E |
| `WX_hum.txt` | Human-readable |
| `WX_hyb.txt` | Hybrid (APRS + human text) |

**Example (APRS):**
```
!5556.34N/03758.45E_c180s007g012t037r...p...P...h54b10066Shchyolkovo WX station
```

**Example (Human):**
```
:=5556.34N/03758.45E_Shchyolkovo WX: Temperature => 2.5 C; Wind => 3.2 m/s, S; Gust => 7.8 m/s; Humidity => 54 %; Pressure => 741 mmHg
```

---

## Wind Tracker

Rolling statistics maintained by `WindTracker` (in `wx_common.py`):

| Period | Buffer | Method |
|--------|--------|--------|
| 1 min | 60 samples | Sum / 60 (includes zeros in first minute) |
| 10 min | 10 × 1-min | Sum of 1-min avgs / 10 |
| 1 hour | 6 × 10-min | Sum of 10-min avgs / 6 |

Also tracks: `wind_max` (instantaneous), `wind_max_1m/10m/1h`, `wind_avr_max_1m/10m/1h` (max of sustained averages).

---

## Derived Calculations

| Metric | Formula | Valid when |
|--------|---------|-----------|
| Dew point | Magnus: `γ=ln(RH/100)+17.67T/(243.5+T)`, `dp=243.5γ/(17.67−γ)` | 0 < RH < 100 |
| Wind chill | `13.12+0.6215T−11.37v^0.16+0.3965T·v^0.16` (v in km/h) | T < 10 °C, v > 1.39 m/s |
| Pressure trend 30m | `(P_now − P_avg_30min) × 1.33322` → hPa | Rolling 30-sample window |

### Weather Prediction (heuristic)

| Condition | Output |
|-----------|--------|
| trend < −3 hPa AND RH > 80% | `rain_likely` |
| trend < −2 hPa | `change_expected` |
| trend > +3 hPa | `clearing` |
| (T − dp) < 3 °C AND T < 15 °C | `fog_possible` |
| Wind > 10 m/s | `strong_wind` |
| else | `stable` |

### Sensor Health

| Check | Warning threshold |
|-------|-------------------|
| Temperature spread (DS18 vs SHT31) | > 3 °C |
| Humidity spread (BME vs SHT31) | > 10 % |

Status: `ok` → `warning` → `offline` (NaN detected).

---

## Installation

### 1. Arduino Master

1. Install **EtherCard** (JeeLabs) + **DallasTemperature** libraries
2. Open `WX_master.ino` in Arduino IDE
3. Configure network (DHCP or static IP)
4. Upload to Arduino Nano

### 2. Python Services

```bash
pip install paho-mqtt

# Run services (separate terminals or systemd units)
python3 Gen_WX.py
python3 WX_2_MQTT.py
python3 WX_2_WEE.py    # only if using WeeWX
```

### 3. WeeWX (optional)

1. Install WeeWX 5.2.0
2. Place `weewx.conf` in config directory
3. `weewxd -f weewx.conf`

### 4. Testing (no hardware required)

```bash
# Terminal 1: start a service
python3 WX_2_MQTT.py

# Terminal 2: feed emulator (60 packets at 1 Hz)
python3 WX_emulator.py --dst 127.0.0.1 --count 60

# Full test suite
python3 tests/test_v171.py
python3 tests/test_calculations.py
python3 tests/test_mqtt_integration.py
```

---

## License

MIT — see [LICENSE](LICENSE) + [Addendum.txt](Addendum.txt)

---

## Author

**R2AKT** — Shchyolkovo, Russia
