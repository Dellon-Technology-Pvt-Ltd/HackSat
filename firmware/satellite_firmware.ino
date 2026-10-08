#include <Arduino.h>
#include <Wire.h>
#include <DHT.h>
#include <MPU6050.h>
#include <TinyGPS++.h>
#include <math.h>

#define DHTPIN 4
#define DHTTYPE DHT11

#define LORA_RX 16
#define LORA_TX 17
#define LORA_AUX 5

#define GPS_RX 19
#define GPS_TX 18

DHT dht(DHTPIN, DHTTYPE);
MPU6050 mpu;
TinyGPSPlus gps;

// Dual Serial Architecture
HardwareSerial GPSSerial(1);        // GPS on Serial1
HardwareSerial TelemetrySerial(2);  // Telemetry on Serial2       


#pragma pack(push,1)
struct Telemetry {

uint16_t sync;
uint16_t apid;
uint16_t seq;
uint32_t missionTime;

float temp;
float hum;

float accX, accY, accZ;
float gyroX, gyroY, gyroZ;

float roll, pitch, yaw;

uint8_t adcsMode;

float lat, lon, alt, speed;

uint32_t utc;

uint8_t satCount;
uint8_t fix;

float hdop;
float radiation;

uint8_t orbit;

uint8_t reserved[32];

uint16_t crc;

};
#pragma pack(pop)

Telemetry tlm;

bool systemActive = true;
uint16_t seqCounter = 0;

// Gyroscope Z-axis bias calibration
// Calibrated during startup to reduce yaw drift
// Assumes board is stationary during calibration
float gyroZBias = 0;

float simLat = 18.5204;
float simLon = 73.8567;
float simAngle = 0;  


uint16_t crc16(uint8_t *data, size_t len)
{
    uint16_t crc = 0xFFFF;

    for (size_t i = 0; i < len; i++)
    {
        crc ^= (uint16_t)data[i] << 8;

        for (uint8_t j = 0; j < 8; j++)
        {
            if (crc & 0x8000)
                crc = (crc << 1) ^ 0x1021;
            else
                crc <<= 1;
        }
    }

    return crc;
}

void setup()
{
    Serial.begin(115200);  // Debug output at 115200 baud
        TelemetrySerial.begin(9600, SERIAL_8N1, LORA_RX, LORA_TX);  // Telemetry at 9600 baud
    GPSSerial.begin(9600, SERIAL_8N1, GPS_RX, GPS_TX);

    Wire.begin();

    dht.begin();
    mpu.initialize();

    // Gyroscope Z-axis bias calibration
    // MPU6050 gyroscope has inherent bias that causes yaw drift over time
    // This calibration measures the average Z-axis offset while the board is stationary
    // This reduces yaw drift but does NOT create an absolute yaw measurement
    // Note: MPU6050 has no magnetometer, so long-term drift will still exist
    Serial.println("Calibrating gyroscope Z-axis bias...");
    int16_t ax, ay, az, gx, gy, gz;
    float gyroZSum = 0;
    const int calibrationSamples = 500;

    for (int i = 0; i < calibrationSamples; i++) {
        mpu.getMotion6(&ax, &ay, &az, &gx, &gy, &gz);
        gyroZSum += gz / 131.0;  // Convert to degrees/second
        delay(2);  // Small delay between samples
    }

    gyroZBias = gyroZSum / calibrationSamples;
    Serial.print("Gyroscope Z-axis bias calibrated: ");
    Serial.print(gyroZBias);
    Serial.println(" deg/s");

    // Initialize LoRa AUX pin for status monitoring
    pinMode(LORA_AUX, INPUT);

    tlm.sync = 0x55AA;
    tlm.apid = 1;
    tlm.yaw = 0;

    Serial.println("SATELLITE STARTED");
}


void loop()
{
    
    if (Serial.available() >= 2)  // Debug commands at 115200
    {
        uint8_t b1 = Serial.read();
        uint8_t b2 = Serial.read();

        if (b1 == 0xDE && b2 == 0xAD)
        {
            systemActive = false;
            Serial.println("COMMAND: STOP");
        }
        else if (b1 == 0x00 && b2 == 0xFF)
        {
            systemActive = true;
            Serial.println("COMMAND: START");
        }
    }

    if (!systemActive)
    {
        delay(200);
        return;
    }

    while (GPSSerial.available())
    {
        gps.encode(GPSSerial.read());
    }

    int16_t ax, ay, az, gx, gy, gz;
    mpu.getMotion6(&ax, &ay, &az, &gx, &gy, &gz);

    tlm.seq = seqCounter++;
    tlm.missionTime = millis();

    float tempReading = dht.readTemperature();
    float humReading = dht.readHumidity();

    // Fallback for temperature/humidity if DHT11 fails
    if (isnan(tempReading)) {
        tlm.temp = 25.0 + random(-5, 6) / 10.0;  // Simulate 25°C ± 0.5°C
    } else {
        tlm.temp = tempReading;
    }

    if (isnan(humReading)) {
        tlm.hum = 45.0 + random(-10, 11) / 10.0;  // Simulate 45% ± 1%
    } else {
        tlm.hum = humReading;
    }

    tlm.accX = ax / 16384.0;
    tlm.accY = ay / 16384.0;
    tlm.accZ = az / 16384.0;

    tlm.gyroX = gx / 131.0;
    tlm.gyroY = gy / 131.0;
    tlm.gyroZ = (gz / 131.0) - gyroZBias;  // Apply calibrated bias to reduce yaw drift

    tlm.roll  = atan2(tlm.accY, tlm.accZ) * 180 / PI;
    tlm.pitch = atan2(-tlm.accX, sqrt(tlm.accY * tlm.accY + tlm.accZ * tlm.accZ)) * 180 / PI;

    // Yaw integration using real delta time (dt) instead of fixed timestep
    // Previous implementation used fixed 0.02s (20ms) timestep, but main loop executes every ~2000ms
    // This caused yaw integration to underestimate changes by ~100x
    // New implementation uses actual time between loop iterations for physically consistent integration
    // Note: This only improves yaw integration timing. Gyroscope drift will still exist because
    // no sensor fusion or magnetometer is being used for absolute heading reference.
    static unsigned long prevTime = 0;  // Track previous iteration time
    unsigned long currentTime = millis();

    // Safe initialization: skip first iteration to avoid large dt
    if (prevTime == 0) {
        prevTime = currentTime;
    } else {
        float dt = (currentTime - prevTime) / 1000.0;  // Convert milliseconds to seconds
        tlm.yaw += tlm.gyroZ * dt;  // Integrate yaw using real delta time
        prevTime = currentTime;  // Update previous time for next iteration
    }

    // Normalize yaw between 0° and 360°
    if (tlm.yaw > 360) tlm.yaw -= 360;
    if (tlm.yaw < 0) tlm.yaw += 360;

    tlm.adcsMode = 4;

    if (gps.location.isValid())
    {
        tlm.lat = gps.location.lat();
        tlm.lon = gps.location.lng();
        // Internal storage: altitude in meters (display converted to km in dashboard)
        tlm.alt = gps.altitude.meters();
        // Internal storage: speed in km/h (display converted to km/s in dashboard)
        tlm.speed = gps.speed.kmph();
        tlm.utc = gps.time.value();

        tlm.fix = 1;
        tlm.satCount = gps.satellites.value();
        tlm.hdop = gps.hdop.hdop();

       
        if (tlm.alt < 2000000) tlm.orbit = 0;
        else if (tlm.alt < 35786000) tlm.orbit = 1;
        else tlm.orbit = 2;
    }
    else
    {
        // GPS simulation when no valid GPS fix is available
        simAngle += 0.02;

        float radius = 0.02;

        tlm.lat = 18.5204 + radius * cos(simAngle);
        tlm.lon = 73.8567 + radius * sin(simAngle);

        // Internal storage: altitude in meters (400,000 m = 400 km LEO altitude)
        // Dashboard converts to km for display
        tlm.alt = 400000 + 10000 * sin(simAngle);
        // Internal storage: speed in km/h (28,000 km/h = 7.78 km/s LEO orbital speed)
        // Dashboard converts to km/s for display
        tlm.speed = 28000;

        tlm.utc = millis();

        tlm.fix = 0;
        tlm.satCount = 0;
        tlm.hdop = 1.5;

        tlm.orbit = 0; 
    }

    tlm.radiation = 0.18 + random(0, 100) / 10000.0;

    tlm.crc = crc16((uint8_t*)&tlm, sizeof(tlm) - 2);


    TelemetrySerial.write((uint8_t*)&tlm, sizeof(tlm));

    Serial.println("Telemetry Sent");
    
    // Monitor LoRa AUX status
    int auxStatus = digitalRead(LORA_AUX);
    Serial.print("LoRa AUX Status: ");
    Serial.println(auxStatus ? "HIGH" : "LOW");

    delay(2000);
}