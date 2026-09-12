/*
////
// Arduino Weather station by Sergey Dorozhkin aka R2AKT. (C) Copyright 2021-2026.
// Software version: v0.6.0
// Project - https://github.com/R2AKT/WX
//
// Changelog v0.6.0:
//   - Fix: ether.packetLoop() added to UDP mode (DHCP lease renewal)
//   - Fix: SHT31 NaN → -127/100 (was 0, inconsistent with DS18/BME)
//   - Fix: AS5600 direction validation (was isnan on int - never triggers)
//   - Fix: Explicit int16 LE packing (portable beyond AVR)
//   - Fix: #ifdef CRITILL → CRITICAL (typo)
//   - Add: Wire.setTimeout(100) for I2C hang protection
//   - Ref: Code structure cleanup, consistent naming
////
*/

////
// Program configuration. Set parameters before use!
////

//// Network
//#define STATIC // Use a static IP address setting (must be set), otherwise DHCP.
#define LOCAL_UDP  // UDP RAW output
//#define LOCAL_JSON // UDP JSON output (not supported on Arduino Nano)
//#define NO_NET // USART data output only
//#define NARODMON // No comments, no more support

//// Sensors
//#define NO_DS18 // Disable DS18B20 1-wire sensor
//#define NO_SHT // Disable SHT3x I2C sensor
//#define NO_BME // Disable BME2x0 I2C sensor
//#define NO_AMS // Disable AS5600 I2C sensor
//#define AMS_REVERSE // Reverse AS5600 value
#define SKIP_MAG_CHECK // Skip AS5600 magnet check
//#define NO_SENSOR // For debug purposes

//// Verbose level (USART)
//#define DEBUG
//#define CRITICAL
//#define INFO

//// Set USART output level, if no network
#ifdef NO_NET
  #define DEBUG
#endif

//// JSON
#ifdef LOCAL_JSON
  #include <ArduinoJson.h>
#endif

//// Watchdog
#define WD_ENABLE
#ifdef WD_ENABLE
  #include <Watchdog.h>
  Watchdog watchdog;
#endif

//// MAC and hostname
const byte EthMAC[] = {0xA8, 0x61, 0x0A, 0x00, 0x01, 0x01};
const char WX_Net_Name[] = "ArduinoWX";
static String MACstr;

#ifndef NO_NET
  #define ENC28
  #ifdef ENC28
    #include <EtherCard.h>
    #include <IPAddress.h>
    byte Ethernet::buffer[600]; // Must be >= 512
  #else
    #include <Ethernet.h>
    #include <EthernetUdp.h>
    #include <IPAddress.h>
    #define IP_LEN 4
    EthernetUDP Udp;
  #endif

  #ifdef STATIC
    const byte myip[IP_LEN] = {192, 168, 1, 221};
    const byte gwip[IP_LEN] = {192, 168, 1, 1};
    const byte mask[IP_LEN] = {255, 255, 255, 0};
    const byte dns[IP_LEN] = {192, 168, 1, 1};
  #endif

  #ifdef LOCAL_UDP
    const int srcPortUDP = 4001;
    const int dstPortUDP = 4001;
    const byte dstIPUDP[IP_LEN] = {255, 255, 255, 255};
  #endif

  #ifdef LOCAL_JSON
    const int srcPortJSON = 4002;
    const int dstPortJSON = 4002;
    const byte dstIPJSON[IP_LEN] = {255, 255, 255, 255};
  #endif

  #ifdef NARODMON
    const int SendPeriod = 300;
    const int srcPortInt = 8283;
    const int dstPortInt = 8283;
    const char dstAddrInt[] = "narodmon.ru";
    const byte dstIPInt[IP_LEN] = {185, 245, 187, 136};
  #endif
#endif

//// Pins
#define SSPin 3          // Wind speed sensor (TLE4934) interrupt pin
#define ONE_WIRE_BUS 8   // DS18B20 1-Wire bus

//// Sensors
#ifndef NO_SENSOR
  #include <AS5600.h>
  AMS_5600 ams5600;

  #ifndef NO_SHT
    #include "Adafruit_SHT31.h"
    Adafruit_SHT31 SHT = Adafruit_SHT31();
  #endif

  #ifndef NO_BME
    #include <Adafruit_BME280.h>
    Adafruit_BME280 BME;
  #endif

  #ifndef NO_DS18
    #include <OneWire.h>
    #include <DallasTemperature.h>
    OneWire DS18(ONE_WIRE_BUS);
    DallasTemperature DS18sensor(&DS18);
  #endif
#endif

#include <TimerOne.h>

////
// Sensor values (static, updated once per second)
////
static float DS_Temperature = -127.0;
static float BME_Temperature = -127.0;
static float BME_Pressure = 765.0;
static float BME_Humidity = 0.0;
static float SHT_Temperature = -127.0;
static float SHT_Humidity = 0.0;
static int Wind_Direction = 0;
volatile float Wind_Speed = 0.0;
volatile int SScount = 0;
static long OldSeconds = 0;
volatile long Seconds = 0;
static int SendDelay = 0;
static int loopCnt = 0;

////
// Timer ISR — fires once per second
////
void SecInt() {
  Seconds++;
  loopCnt++;
  Wind_Speed = (float)SScount / 4.0;  // 4 edges per rotation, 1 rot/s = 1 m/s
  SScount = 0;
  #ifdef WD_ENABLE
    watchdog.reset();
  #endif
}

////
// Wind speed interrupt (TLE4934, pin 3)
////
void SSInt() {
  SScount++;
}

////
// AS5600 raw angle to degrees (0-4095 → 0-359)
////
int convertRawAngleToDegrees(word newAngle) {
  float deg = (float)newAngle * 0.087890625f;

  #ifdef AMS_REVERSE
    if (deg >= 180.0f) {
      deg -= 180.0f;
    } else {
      deg += 180.0f;
    }
  #endif

  if (deg >= 360.0f) {
    deg -= 360.0f;
  }
  if (deg < 0.0f) {
    deg += 360.0f;
  }
  return (int)deg;
}

////
// Read all sensors once
////
void readSensors() {
  #ifndef NO_SENSOR
    #ifndef NO_DS18
      DS18sensor.requestTemperatures();
      DS_Temperature = DS18sensor.getTempCByIndex(0);
      if (DS_Temperature == DEVICE_DISCONNECTED_C) {
        DS_Temperature = -127.0;
      }
    #endif

    #ifndef NO_BME
      BME_Temperature = BME.readTemperature();
      if (isnan(BME_Temperature)) {
        BME_Temperature = -127.0;
      }
      BME_Pressure = BME.readPressure() * 0.007500637f;  // Pa → mmHg
      if (isnan(BME_Pressure)) {
        BME_Pressure = 765.0;
      }
      BME_Humidity = BME.readHumidity();
      if (isnan(BME_Humidity)) {
        BME_Humidity = 0.0;
      }
    #endif

    #ifndef NO_SHT
      SHT_Temperature = SHT.readTemperature();
      SHT_Humidity = SHT.readHumidity();
      if (isnan(SHT_Temperature)) {
        SHT_Temperature = -127.0;
      }
      if (isnan(SHT_Humidity)) {
        SHT_Humidity = 100.0;
      }
    #endif

    #ifndef NO_AMS
      word rawAngle = ams5600.getRawAngle();
      if (rawAngle == 0 || rawAngle == 4095) {
        Wind_Direction = 0;  // Sensor error or stuck
      } else {
        Wind_Direction = convertRawAngleToDegrees(rawAngle);
      }
    #endif
  #endif
}

////
// Build and send 36-byte UDP packet
////
void sendUDP() {
  char BuffToSend[36];

  // [0:6] MAC address
  memcpy(BuffToSend, EthMAC, 6);

  // [6:10] DS18 Temperature (float32 LE)
  float tmp;
  tmp = DS_Temperature;
  memcpy(&BuffToSend[6], &tmp, 4);

  // [10:14] BME Temperature (float32 LE)
  tmp = BME_Temperature;
  memcpy(&BuffToSend[10], &tmp, 4);

  // [14:18] BME Humidity (float32 LE)
  tmp = BME_Humidity;
  memcpy(&BuffToSend[14], &tmp, 4);

  // [18:22] BME Pressure mmHg (float32 LE)
  tmp = BME_Pressure;
  memcpy(&BuffToSend[18], &tmp, 4);

  // [22:26] SHT Temperature (float32 LE)
  tmp = SHT_Temperature;
  memcpy(&BuffToSend[22], &tmp, 4);

  // [26:30] SHT Humidity (float32 LE)
  tmp = SHT_Humidity;
  memcpy(&BuffToSend[26], &tmp, 4);

  // [30:32] Wind Direction (int16 LE)
  BuffToSend[30] = Wind_Direction & 0xFF;
  BuffToSend[31] = (Wind_Direction >> 8) & 0xFF;

  // [32:36] Wind Speed (float32 LE)
  tmp = Wind_Speed;
  memcpy(&BuffToSend[32], &tmp, 4);

  #ifdef DEBUG
    Serial.println(F("\r\nUDP RAW data:"));
    for (byte i = 0; i < 36; i++) {
      Serial.print((char)BuffToSend[i], HEX);
    }
    Serial.print(F("\n"));
  #endif

  #ifndef NO_NET
    #ifdef ENC28
      ether.copyIp(ether.hisip, dstIPUDP);
      ether.sendUdp(BuffToSend, 36, srcPortUDP, ether.hisip, dstPortUDP);
    #else
      Udp.beginPacket((IPAddress)dstIPUDP, dstPortUDP);
      Udp.write((byte*)BuffToSend, 36);
      Udp.endPacket();
    #endif
  #endif
}

#ifdef LOCAL_JSON
  ////
  // Send JSON format (ArduinoJson v6)
  ////
  void sendJSON() {
    String JSON_WX_String;
    StaticJsonDocument<384> JSON_WX;

    JSON_WX["device"] = String(WX_Net_Name);
    JSON_WX["id"] = MACstr;
    JsonObject WX_sensors = JSON_WX.createNestedObject("Sens");

    JsonObject obj;
    obj["id"] = "DS18";  obj["val"] = DS_Temperature;
    WX_sensors.add("Tmp", obj);

    obj["id"] = "SHT";   obj["val"] = SHT_Humidity;
    WX_sensors.add("Hum", obj);

    obj["id"] = "BME";   obj["val"] = BME_Pressure;
    WX_sensors.add("Pre", obj);

    obj["id"] = "TLE49"; obj["val"] = Wind_Speed;
    WX_sensors.add("Wnd", obj);

    obj["id"] = "AS56";  obj["val"] = Wind_Direction;
    WX_sensors.add("Dir", obj);

    serializeJson(JSON_WX, JSON_WX_String);

    char BuffToSendJSON[JSON_WX_String.length()];
    JSON_WX_String.toCharArray(BuffToSendJSON, JSON_WX_String.length());

    #ifdef DEBUG
      Serial.print(F("\r\nUDP JSON data: "));
      Serial.println(JSON_WX_String);
    #endif

    #ifndef NO_NET
      #ifdef ENC28
        ether.copyIp(ether.hisip, dstIPJSON);
        ether.sendUdp(BuffToSendJSON, sizeof(BuffToSendJSON), srcPortJSON, ether.hisip, dstPortJSON);
      #else
        Udp.beginPacket((IPAddress)dstIPJSON, dstPortJSON);
        Udp.write((byte*)BuffToSendJSON, sizeof(BuffToSendJSON));
        Udp.endPacket();
      #endif
    #endif
  }
#endif

#ifdef NARODMON
  ////
  // Send NarodMon format
  ////
  void sendNarodMon() {
    if (SendDelay < SendPeriod) return;
    SendDelay = 0;

    String DataStr = "#" + MACstr + "\n"
      "#DS18T1#" + String(DS_Temperature) + "\n"
      "#SHTH1#" + String(SHT_Humidity) + "\n"
      "#BMEP1#" + String(BME_Pressure) + "\n"
      "#AS56D1#" + String(Wind_Direction) + "\n"
      "#TLE49W1#" + String(Wind_Speed) + "\n"
      "###";

    char BuffToSendInt[DataStr.length()];
    DataStr.toCharArray(BuffToSendInt, DataStr.length());

    #ifdef DEBUG
      Serial.println(F("\r\n'NarodMon.Ru' data:"));
      for (byte i = 0; i < DataStr.length(); i++) {
        Serial.print((char)BuffToSendInt[i], HEX);
      }
      Serial.print(F("\n"));
    #endif

    #ifndef NO_NET
      #ifdef ENC28
        ether.copyIp(ether.hisip, dstIPInt);
        ether.sendUdp(BuffToSendInt, sizeof(BuffToSendInt), srcPortInt, ether.hisip, dstPortInt);
      #else
        Udp.beginPacket((IPAddress)dstIPInt, dstPortInt);
        Udp.write((byte*)BuffToSendInt, sizeof(BuffToSendInt));
        Udp.endPacket();
      #endif
    #endif
  }
#endif

////
// Debug output
////
void printDebug() {
  #ifdef DEBUG
    Serial.println(F("________________"));
    Serial.print(F("Temperature (DS18) = ")); Serial.print(DS_Temperature); Serial.println(F("*C"));
    Serial.print(F("Temperature (BME)  = ")); Serial.print(BME_Temperature); Serial.println(F("*C"));
    Serial.print(F("Temperature (SHT)  = ")); Serial.print(SHT_Temperature); Serial.println(F("*C"));
    Serial.print(F("Pressure           = ")); Serial.print(BME_Pressure); Serial.println(F("mmHg"));
    Serial.print(F("Humidity (BME)     = ")); Serial.print(BME_Humidity); Serial.println(F("%"));
    Serial.print(F("Humidity (SHT)     = ")); Serial.print(SHT_Humidity); Serial.println(F("%"));
    Serial.print(F("Wind direction     = ")); Serial.print(Wind_Direction); Serial.println(F("*"));
    Serial.print(F("Wind speed         = ")); Serial.print(Wind_Speed); Serial.println(F("m/s"));
  #endif
}

////
// SHT31 heater cycling (every 30 seconds, 50% duty)
////
void manageSHTHeater() {
  #ifndef NO_SHT
    if (loopCnt >= 30) {
      loopCnt = 0;
      if (SHT.isHeaterEnabled()) {
        SHT.heater(false);
        #ifdef DEBUG
          Serial.println(F("SHT3x heater: OFF"));
        #endif
      } else {
        SHT.heater(true);
        #ifdef DEBUG
          Serial.println(F("SHT3x heater: ON"));
        #endif
      }
    }
  #endif
}

////
// Network maintenance (DHCP renewal, ARP)
////
void networkMaintain() {
  #ifndef NO_NET
    #ifdef ENC28
      #ifndef STATIC
        ether.packetLoop(ether.packetReceive());
      #endif
    #else
      #ifndef STATIC
        Ethernet.maintain();
      #endif
    #endif
  #endif
}

////
// SETUP
////
void setup() {
  #ifndef NO_SENSOR
    pinMode(SSPin, INPUT_PULLUP);
    attachInterrupt(digitalPinToInterrupt(SSPin), SSInt, CHANGE);
    Wire.begin();
    Wire.setClock(100000);
    Wire.setTimeout(100);  // I2C timeout 100ms (prevents hang on sensor fault)
  #endif

  #ifdef CRITICAL
    Serial.begin(9600);
  #else
    #ifdef DEBUG
      Serial.begin(9600);
    #else
      #ifdef INFO
        Serial.begin(9600);
      #endif
    #endif
  #endif

  #ifdef INFO
    Serial.println(F("\r\nArduino Weather station by Sergey Dorozhkin aka R2AKT. (C) Copyright 2021-2026."));
    Serial.println(F("Software version: v0.6.0"));
    Serial.println(F("\r\nProject - https://github.com/r2akt/"));
    Serial.println(F("\nBuild: " __DATE__ ", " __TIME__));
  #endif

  // Timer1: 1-second tick
  Timer1.initialize(1000000);
  Timer1.attachInterrupt(SecInt);

  // MAC string
  char MACchar[17];
  sprintf(MACchar, "%02X-%02X-%02X-%02X-%02X-%02X",
          EthMAC[0], EthMAC[1], EthMAC[2], EthMAC[3], EthMAC[4], EthMAC[5]);
  MACstr = String(MACchar);

  // Network
  #ifndef NO_NET
    #ifdef INFO
      Serial.print(F("Start Ethernet... "));
    #endif

    #ifdef ENC28
      if (ether.begin(sizeof(Ethernet::buffer), EthMAC, SS) == 0) {
        #ifdef CRITICAL
          Serial.println(F("Failed access to Ethernet controller!"));
        #endif
        while (1) delay(1000);
      } else {
        #ifdef STATIC
          #ifdef INFO
            Serial.print(F("Setting up static address..."));
          #endif
          ether.staticSetup(myip, gwip, dns, mask);
          #ifdef DEBUG
            Serial.println(F(" OK"));
          #endif
        #else
          #ifdef INFO
            Serial.print(F("Setting up DHCP address..."));
          #endif
          while (!ether.dhcpSetup(WX_Net_Name)) {
            #ifdef CRITICAL
              Serial.println(F("DHCP failed!"));
            #endif
            delay(1000);
          }
          #ifdef INFO
            Serial.println(F(" OK"));
          #endif
        #endif
        #ifdef DEBUG
          ether.printIp(F("IP: "), ether.myip);
          ether.printIp(F("Mask: "), ether.netmask);
          ether.printIp(F("GW: "), ether.gwip);
          ether.printIp(F("DNS: "), ether.dnsip);
        #endif
      }
    #else // W5500
      #ifdef STATIC
        Ethernet.begin(EthMAC, myip, dns, gwip, mask);
      #else
        while (!Ethernet.begin(EthMAC)) delay(1000);
      #endif
      #ifdef DEBUG
        Serial.print(F("IP: "));
        Serial.println(Ethernet.localIP());
      #endif
      Udp.begin(srcPortUDP);
    #endif

    #ifdef NARODMON
      #ifdef INFO
        Serial.print("DNS lookup '" + String(dstAddrInt) + "'...");
      #endif
      #ifdef ENC28
        if (!ether.dnsLookup(dstAddrInt)) {
          #ifdef DEBUG
            Serial.println(F(" Failed! Use manual IP"));
          #endif
          ether.copyIp(ether.hisip, dstIPInt);
        } else {
          #ifdef DEBUG
            Serial.println(F(" OK"));
          #endif
          ether.copyIp(dstIPInt, ether.hisip);
        }
        #ifdef INFO
          ether.printIp(F("Resolved IP: "), ether.hisip);
        #endif
      #endif
    #endif
  #endif

  // Sensors
  #ifndef NO_SENSOR
    #ifdef INFO
      Serial.println(F("Start: "));
    #endif

    #ifndef NO_DS18
      #ifdef INFO
        Serial.println(F("-DS18"));
      #endif
      DS18sensor.begin();
      DS18sensor.setResolution(12);
    #endif

    #ifndef NO_SHT
      #ifdef INFO
        Serial.println(F("-SHT"));
      #endif
      SHT.begin(0x44);
    #endif

    #ifndef NO_BME
      #ifdef INFO
        Serial.println(F("-BME"));
      #endif
      BME.begin(0x76);
    #endif

    #ifndef NO_AMS
      #ifdef INFO
        Serial.print(F("-AS5600"));
      #endif
      #ifndef SKIP_MAG_CHECK
        Serial.print(F(", check magnet..."));
        if (ams5600.detectMagnet() == 0) {
          while (ams5600.detectMagnet() != 1) {
            #ifdef CRITICAL
              Serial.println(F("Can not detect magnet..."));
            #endif
            delay(100);
          }
        }
      #else
        Serial.print(F("\n"));
      #endif
    #endif
  #endif

  #ifdef INFO
    Serial.println(F("Start loop... "));
  #endif

  #ifdef WD_ENABLE
    watchdog.enable(Watchdog::TIMEOUT_4S);
  #endif
}

////
// MAIN LOOP
////
void loop() {
  if (OldSeconds != Seconds) {
    OldSeconds = Seconds;
    SendDelay++;

    readSensors();

    #ifdef LOCAL_UDP
      sendUDP();
    #endif

    #ifdef NARODMON
      sendNarodMon();
    #endif

    #ifdef LOCAL_JSON
      sendJSON();
    #endif

    // Network maintenance (DHCP renewal, ARP) — CRITICAL for long-term uptime
    networkMaintain();

    printDebug();
    manageSHTHeater();
  }
}
