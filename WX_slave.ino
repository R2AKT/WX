/*
////
// Arduino Weather station SLAVE (LCD display) by Sergey Dorozhkin aka R2AKT.
// (C) Copyright 2021-2026.
// Software version: v0.4.0
// Project - https://github.com/R2AKT/WX
//
// Changelog v0.3.0:
//   - Fix: Protocol updated to 36-byte format (SHT_T/SHT_H added, wind at [30:36])
//   - Fix: #ifdef CRITILL → CRITICAL
//   - Fix: Comma operator (0,0) → 0.0 in average init
//   - Fix: isnan() on int (Wind_Direction) → explicit check
//   - Fix: memset(MACchar, 0, sizeof(WX_Addr)) → sizeof(MACchar)
//   - Fix: Duplicate Timer1.initialize() removed
//   - Add: Packet length validation (>= 36 bytes)
//   - Add: Wire.setTimeout(100) for I2C hang protection
//   - Add: networkMaintain() — DHCP renewal
//   - Ref: Function structure cleanup
////
*/

//// Verbose level
#define INFO
#define DEBUG
//#define CRITICAL

//// Watchdog
#define WD_ENABLE
#ifdef WD_ENABLE
  #include <Watchdog.h>
  Watchdog watchdog;
#endif

//// Network
//#define STATIC
#define BROADCAST

//// LCD
#define LCD
#ifdef LCD
  #include <SPI.h>
  #include <Wire.h>
  #include <LiquidCrystal_I2C.h>
  #define LCDSTRLEN 20
  #define LCDLINE   4
  LiquidCrystal_I2C lcd(0x27, LCDSTRLEN, LCDLINE);
#endif

//// Rolling average (30-second window)
//#define AVR_VAL
#ifdef AVR_VAL
  #define AVR_TIME 30
  #define TEMPERATURE_AVR
  #define PLEASURE_AVR
  #define HUMIDITY_AVR
  #define WIND_AVR
  #define DIRECTION_AVR
#endif

//// Ethernet
#include <EtherCard.h>
#include <IPAddress.h>

const byte EthMAC[] = {0xA8, 0x61, 0x0A, 0x00, 0x01, 0x02};
const char WX_Net_Name[] = "Arduino_WX_LCD";
byte Ethernet::buffer[700];

#ifdef STATIC
  const byte myip[IP_LEN] = {192, 168, 1, 222};
  const byte gwip[IP_LEN] = {192, 168, 1, 1};
  const byte mask[IP_LEN] = {255, 255, 255, 0};
  const byte dns[IP_LEN] = {192, 168, 1, 1};
#endif

const int dstPortLocal = 4001;

//// Sensor values (updated by ReceiveUDP callback)
static byte WX_Addr[6] = {0};
static char MACchar[12] = {0};
static float DS_Temperature = -127.0;
static float BME_Temperature = -127.0;
static float BME_Pressure = 765.0;
static float BME_Humidity = 0.0;
static float SHT_Temperature = -127.0;
static float SHT_Humidity = 0.0;
static int Wind_Direction = 0;
static float Wind_Speed = 0.0;

//// Rolling average state
#ifdef AVR_VAL
  static byte Avr_Ind = 0;
  #ifdef TEMPERATURE_AVR
    static float Temperature_Avr[AVR_TIME] = {0};
    static float Temperature_Val_Avr = 0.0;
  #endif
  #ifdef PLEASURE_AVR
    static float Pleasure_Avr[AVR_TIME] = {0};
    static float Pleasure_Val_Avr = 0.0;
  #endif
  #ifdef HUMIDITY_AVR
    static float Humidity_Avr[AVR_TIME] = {0};
    static float Humidity_Val_Avr = 0.0;
  #endif
  #ifdef WIND_AVR
    static float Wind_Avr[AVR_TIME] = {0};
    static float Wind_Val_Avr = 0.0;
  #endif
  #ifdef DIRECTION_AVR
    static byte Direction_Avr[AVR_TIME] = {0};
    static int Direction_Val_Avr = 0;
  #endif
#endif

#include <TimerOne.h>

volatile long Seconds = 0;
static long OldSeconds = 0;

////
// Timer ISR — 1-second tick
////
void SecInt() {
  Seconds++;
  #ifdef WD_ENABLE
    watchdog.reset();
  #endif
}

////
// Parse 36-byte UDP packet from master
// Format: MAC(6) + DS18_T(4) + BME_T(4) + BME_H(4) + BME_P(4) + SHT_T(4) + SHT_H(4) + WindDir(2) + WindSpeed(4)
////
void ReceiveUDP(uint16_t dest_port, uint8_t src_ip[IP_LEN], uint16_t src_port,
               const char *data, uint16_t len) {

  #ifdef DEBUG
    Serial.println(F("=> Ethernet data:"));
    Serial.print(F("src_port: "));
    Serial.println(src_port);
    Serial.print(F("len: "));
    Serial.println(len);
  #endif

  // Skip ASCII packets (from serial monitor or other sources)
  if (len >= 4 && data[0] == 'A' && data[1] == 'S' && data[2] == 'C' && data[3] == 'I') {
    #ifdef INFO
      Serial.println(F("- ANSI data. Skip."));
    #endif
    return;
  }

  // Validate packet length
  if (len < 36) {
    #ifdef CRITICAL
      Serial.print(F("Short packet: "));
      Serial.println(len);
    #endif
    return;
  }

  // [0:6] MAC
  memcpy(WX_Addr, data, 6);

  // [6:10] DS18 Temperature (float32 LE)
  float tmp;
  memcpy(&tmp, data + 6, 4);
  DS_Temperature = tmp;
  if (isnan(DS_Temperature)) DS_Temperature = -127.0;

  // [10:14] BME Temperature (float32 LE)
  memcpy(&tmp, data + 10, 4);
  BME_Temperature = tmp;
  if (isnan(BME_Temperature)) BME_Temperature = -127.0;

  // [14:18] BME Humidity (float32 LE)
  memcpy(&tmp, data + 14, 4);
  BME_Humidity = tmp;
  if (isnan(BME_Humidity)) BME_Humidity = 0.0;

  // [18:22] BME Pressure mmHg (float32 LE)
  memcpy(&tmp, data + 18, 4);
  BME_Pressure = tmp;
  if (isnan(BME_Pressure)) BME_Pressure = 765.0;

  // [22:26] SHT Temperature (float32 LE) — NEW
  memcpy(&tmp, data + 22, 4);
  SHT_Temperature = tmp;
  if (isnan(SHT_Temperature)) SHT_Temperature = -127.0;

  // [26:30] SHT Humidity (float32 LE) — NEW
  memcpy(&tmp, data + 26, 4);
  SHT_Humidity = tmp;
  if (isnan(SHT_Humidity)) SHT_Humidity = 100.0;

  // [30:32] Wind Direction (int16 LE)
  Wind_Direction = (int16_t)(data[30] | (data[31] << 8));

  // [32:36] Wind Speed (float32 LE)
  memcpy(&tmp, data + 32, 4);
  Wind_Speed = tmp;
  if (isnan(Wind_Speed)) Wind_Speed = 0.0;
}

////
// Update rolling averages
////
void updateAverages() {
  #ifdef AVR_VAL
    Avr_Ind++;
    if (Avr_Ind >= AVR_TIME) Avr_Ind = 0;

    #ifdef TEMPERATURE_AVR
      Temperature_Avr[Avr_Ind] = DS_Temperature;
    #endif
    #ifdef PLEASURE_AVR
      Pleasure_Avr[Avr_Ind] = BME_Pressure;
    #endif
    #ifdef HUMIDITY_AVR
      Humidity_Avr[Avr_Ind] = BME_Humidity;
    #endif
    #ifdef DIRECTION_AVR
      Direction_Avr[Avr_Ind] = (byte)Wind_Direction;
    #endif
    #ifdef WIND_AVR
      Wind_Avr[Avr_Ind] = Wind_Speed;
    #endif

    // Calculate averages
    #ifdef TEMPERATURE_AVR
      float sum = 0.0;
      for (byte i = 0; i < AVR_TIME; i++) sum += Temperature_Avr[i];
      Temperature_Val_Avr = sum / AVR_TIME;
    #endif
    #ifdef PLEASURE_AVR
      float sum = 0.0;
      for (byte i = 0; i < AVR_TIME; i++) sum += Pleasure_Avr[i];
      Pleasure_Val_Avr = sum / AVR_TIME;
    #endif
    #ifdef HUMIDITY_AVR
      float sum = 0.0;
      for (byte i = 0; i < AVR_TIME; i++) sum += Humidity_Avr[i];
      Humidity_Val_Avr = sum / AVR_TIME;
    #endif
    #ifdef DIRECTION_AVR
      int sum = 0;
      for (byte i = 0; i < AVR_TIME; i++) sum += Direction_Avr[i];
      Direction_Val_Avr = sum / AVR_TIME;
    #endif
    #ifdef WIND_AVR
      float sum = 0.0;
      for (byte i = 0; i < AVR_TIME; i++) sum += Wind_Avr[i];
      Wind_Val_Avr = sum / AVR_TIME;
    #endif
  #endif
}

////
// Display data on LCD
////
void displayData() {
  #ifdef LCD
    char data_char[16] = "";

    // Line 0: Remote MAC
    lcd.setCursor(0, 0);
    memset(MACchar, 0, sizeof(MACchar));
    sprintf(MACchar, "%02X%02X%02X%02X%02X%02X",
            WX_Addr[0], WX_Addr[1], WX_Addr[2], WX_Addr[3], WX_Addr[4], WX_Addr[5]);
    lcd.print(F("MAC:"));
    lcd.print(MACchar);

    // Line 1: Temperature + Pressure
    lcd.setCursor(0, 1);
    lcd.print(F("T1:"));
    #ifdef TEMPERATURE_AVR
      dtostrf(Temperature_Val_Avr, 5, 1, data_char);
      lcd.print(data_char);
    #else
      dtostrf(DS_Temperature, 5, 1, data_char);
      lcd.print(data_char);
    #endif

    lcd.setCursor(10, 1);
    lcd.print(F("P:"));
    #ifdef PLEASURE_AVR
      dtostrf(Pleasure_Val_Avr, 4, 0, data_char);
      lcd.print(data_char);
    #else
      dtostrf(BME_Pressure, 4, 0, data_char);
      lcd.print(data_char);
    #endif

    // Line 2: Humidity + Wind speed
    lcd.setCursor(0, 2);
    lcd.print(F("H:"));
    #ifdef HUMIDITY_AVR
      dtostrf(Humidity_Val_Avr, 4, 1, data_char);
      lcd.print(data_char);
    #else
      dtostrf(BME_Humidity, 4, 1, data_char);
      lcd.print(data_char);
    #endif

    lcd.setCursor(10, 2);
    lcd.print(F("W:"));
    #ifdef WIND_AVR
      dtostrf(Wind_Val_Avr, 4, 1, data_char);
      lcd.print(data_char);
    #else
      dtostrf(Wind_Speed, 4, 1, data_char);
      lcd.print(data_char);
    #endif

    // Line 3: Direction
    lcd.setCursor(0, 3);
    lcd.print(F("D:"));
    #ifdef DIRECTION_AVR
      dtostrf(Direction_Val_Avr, 3, 0, data_char);
      lcd.print(data_char);
    #else
      dtostrf(Wind_Direction, 3, 0, data_char);
      lcd.print(data_char);
    #endif
  #endif
}

////
// Serial debug output
////
void printDebug() {
  #ifdef INFO
    Serial.println(F("\r\n=> Sensor data:"));

    memset(MACchar, 0, sizeof(MACchar));
    sprintf(MACchar, "%02X%02X%02X%02X%02X%02X",
            WX_Addr[0], WX_Addr[1], WX_Addr[2], WX_Addr[3], WX_Addr[4], WX_Addr[5]);
    Serial.print(F("WX MAC = "));
    Serial.println(MACchar);

    #ifdef TEMPERATURE_AVR
      Serial.print(F("Temperature (DS18) Cur/Avr = "));
      Serial.print(DS_Temperature);
      Serial.print("/");
      Serial.print(Temperature_Val_Avr);
    #else
      Serial.print(F("Temperature (DS18) = "));
      Serial.print(DS_Temperature);
    #endif
    Serial.println(F("*C"));

    Serial.print(F("Temperature (BME)  = "));
    Serial.print(BME_Temperature);
    Serial.println(F("*C"));

    Serial.print(F("Temperature (SHT)  = "));
    Serial.print(SHT_Temperature);
    Serial.println(F("*C"));

    #ifdef PLEASURE_AVR
      Serial.print(F("Pressure Cur/Avr    = "));
      Serial.print(BME_Pressure);
      Serial.print("/");
      Serial.print(Pleasure_Val_Avr);
    #else
      Serial.print(F("Pressure            = "));
      Serial.print(BME_Pressure);
    #endif
    Serial.println(F(" mmHg"));

    #ifdef HUMIDITY_AVR
      Serial.print(F("Humidity Cur/Avr    = "));
      Serial.print(BME_Humidity);
      Serial.print("/");
      Serial.print(Humidity_Val_Avr);
    #else
      Serial.print(F("Humidity            = "));
      Serial.print(BME_Humidity);
    #endif
    Serial.println(F(" %"));

    Serial.print(F("Humidity (SHT)      = "));
    Serial.print(SHT_Humidity);
    Serial.println(F(" %"));

    #ifdef DIRECTION_AVR
      Serial.print(F("Wind dir Cur/Avr    = "));
      Serial.print(Wind_Direction);
      Serial.print("/");
      Serial.print(Direction_Val_Avr);
    #else
      Serial.print(F("Wind direction      = "));
      Serial.print(Wind_Direction);
    #endif
    Serial.println(F(" deg"));

    #ifdef WIND_AVR
      Serial.print(F("Wind speed Cur/Avr  = "));
      Serial.print(Wind_Speed);
      Serial.print("/");
      Serial.print(Wind_Val_Avr);
    #else
      Serial.print(F("Wind speed          = "));
      Serial.print(Wind_Speed);
    #endif
    Serial.println(F(" m/s"));
  #endif
}

////
// Network maintenance (DHCP renewal)
////
void networkMaintain() {
  #ifndef STATIC
    ether.packetLoop(ether.packetReceive());
  #endif
}

////
// SETUP
////
void setup() {
  #ifdef LCD
    Wire.begin();
    Wire.setClock(10000);
    Wire.setTimeout(100);
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
    Serial.println(F("\r\nWeather station SLAVE by Sergey Dorozhkin aka R2AKT. (C) Copyright 2021-2026."));
    Serial.println(F("Software version: v0.4.0"));
    Serial.println(F("Build: " __DATE__ ", " __TIME__));
  #endif

  // Timer1: 1-second tick
  Timer1.initialize(1000000);
  Timer1.attachInterrupt(SecInt);

  // Ethernet
  #ifdef INFO
    Serial.print(F("Start Ethernet... "));
  #endif

  if (ether.begin(sizeof(Ethernet::buffer), EthMAC, SS) == 0) {
    #ifdef CRITICAL
      Serial.println(F("Failed to access Ethernet controller!"));
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

  // Broadcast
  #ifdef BROADCAST
    ether.enableBroadcast();
    #ifdef INFO
      Serial.println(F("Broadcast: enabled"));
    #endif
  #else
    ether.disableBroadcast();
    #ifdef INFO
      Serial.println(F("Broadcast: disabled"));
    #endif
  #endif

  // UDP listener
  #ifdef INFO
    Serial.print(F("Listening port: "));
    Serial.println(dstPortLocal);
  #endif
  ether.udpServerListenOnPort(&ReceiveUDP, dstPortLocal);

  // LCD init
  #ifdef LCD
    lcd.init();
    lcd.clear();
    lcd.backlight();
    lcd.setCursor(0, 0);
    lcd.print(F("WX SLAVE v0.3.0"));
    lcd.setCursor(0, 1);
    lcd.print(F("by R2AKT"));
    lcd.setCursor(0, 2);
    lcd.print(__DATE__);
    lcd.setCursor(12, 2);
    lcd.print(__TIME__);
    lcd.setCursor(0, 3);
    memset(MACchar, 0, sizeof(MACchar));
    sprintf(MACchar, "%02X%02X%02X%02X%02X%02X",
            EthMAC[0], EthMAC[1], EthMAC[2], EthMAC[3], EthMAC[4], EthMAC[5]);
    lcd.print(F("MAC:"));
    lcd.print(MACchar);
    delay(2000);
    lcd.clear();
  #endif

  #ifdef WD_ENABLE
    watchdog.enable(Watchdog::TIMEOUT_4S);
  #endif

  #ifdef INFO
    Serial.println(F("Start loop..."));
  #endif
}

////
// MAIN LOOP
////
void loop() {
  // Receive UDP packets (also handles DHCP)
  networkMaintain();

  if (OldSeconds != Seconds) {
    OldSeconds = Seconds;

    updateAverages();
    displayData();
    printDebug();
  }
}
