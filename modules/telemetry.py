import struct
import math

# ================= CONFIG =================
# Fixed format to match ESP32 struct exactly
fmt = "<HHH I ff fffffffff B ffff I BB ff B 32s H"
SIZE = struct.calcsize(fmt)

# ================= CRC FUNCTION =================
def crc16(data):
    """Calculate CRC16 CCITT - matching Arduino implementation"""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc

# ================= HELPERS =================
def orbit_name(o):
    """Convert orbit ID to name"""
    return ["LEO", "MEO", "GEO"][o] if o < 3 else "UNK"

def adcs_mode_name(m):
    """Convert ADCS mode ID to name"""
    return ["SAFE", "DETUMBLE", "SUN", "NADIR", "NOMINAL"][m] if m < 5 else "UNK"

# ================= DECODING =================
def decode_telemetry(packet):
    """Decode raw telemetry packet to dictionary"""
    try:
        # Unpack the packet
        data = struct.unpack(fmt, packet)
        
        # Extract sync word and validate
        sync = data[0]
        if sync != 0x55AA:  # ESP32 uses 0x55AA (little endian)
            return None
            
        # Create telemetry dictionary
        telemetry = {
            "apid": data[1],
            "seq": data[2],
            "mission_time": data[3],
            
            # Housekeeping
            "temp": round(data[4], 2),
            "humidity": round(data[5], 2),
            
            # ADCS
            "acc": [round(data[6], 3), round(data[7], 3), round(data[8], 3)],
            "gyro": [round(data[9], 2), round(data[10], 2), round(data[11], 2)],
            "roll": round(data[12], 2),
            "pitch": round(data[13], 2),
            "yaw": round(data[14], 2) % 360,
            "adcs_mode": adcs_mode_name(data[15]),
            
            # Navigation
            "lat": round(data[16], 6),
            "lon": round(data[17], 6),
            "alt": round(data[18], 1),
            "speed": round(data[19], 1),
            "utc": data[20],
            "sat_count": data[21],
            "fix": data[22],
            "hdop": round(data[23], 2),
            "orbit": orbit_name(data[25]),
            
            # Payload
            "radiation": round(data[24], 5)
        }
        
        return telemetry
        
    except Exception as e:
        print(f"❌ Telemetry decode error: {e}")
        return None

def validate_packet(packet):
    """Validate packet sync and CRC"""
    if len(packet) != SIZE:
        return False
        
    # Check sync word (ESP32 uses 0x55AA little endian = AA 55 in bytes)
    if not (packet[0] == 0xAA and packet[1] == 0x55):
        return False
        
    # Validate CRC
    recv_crc = struct.unpack("<H", packet[-2:])[0]
    calc_crc = crc16(packet[:-2])
    
    return recv_crc == calc_crc

def create_test_packet():
    """Create a valid test packet for debugging"""
    # Create test data
    data = struct.pack(fmt,
        0x55AA,    # sync
        100,         # apid
        1,           # seq
        123456,      # mission_time
        25.5,        # temp
        60.2,        # humidity
        0.1, 0.2, 0.3,  # acc
        0.01, 0.02, 0.03,  # gyro
        10.5, 20.5, 30.5,  # roll, pitch, yaw
        1,            # adcs_mode
        18.5204, 73.8567, 500.0, 100.0,  # lat, lon, alt, speed
        123456789,    # utc
        8,             # sat_count
        3,             # fix
        1.2,           # hdop
        0.00001,       # radiation
        0,             # orbit
        b'\x00' * 32,  # reserved
        0              # crc placeholder
    )
    
    # Calculate and append CRC
    crc = crc16(data[:-2])
    data_with_crc = data[:-2] + struct.pack("<H", crc)
    
    return data_with_crc
