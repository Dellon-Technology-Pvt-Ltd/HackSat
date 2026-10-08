import serial
import serial.tools.list_ports
import time
import threading
import platform

from .telemetry import SIZE, validate_packet, decode_telemetry


class SerialReader:

    def __init__(self, socketio):

        self.socketio = socketio

    # Callback for telemetry processing
        self.telemetry_callback = None

        self.system = platform.system()

        self.log_buffer = []
        self.max_log_entries = 100

        self.port = self._detect_serial_port()

        self.baudrate = 9600
        self.serial_conn = None

        # IMPORTANT
        self.buffer = bytearray()

        self.running = False
        self.thread = None

        self.last_packet_time = 0

        self.connection_attempts = 0
        self.max_attempts = 5

        self.modbus_control = None

        self.communication_mode = 'LORA'

        self.telemetry_health = {
            'packets_received': 0,
            'packets_lost': 0,
            'last_valid_time': 0,
            'consecutive_failures': 0,
            'average_interval': 1.0,
            'health_score': 100
        }

        self.connection_state = 'DISCONNECTED'

        self.last_health_check = time.time()

        self.last_seq = None
        self.expected_seq = 1
        self.packets_lost = 0
        self.total_packets_expected = 0

    # ==========================================================
    # LOGGING
    # ==========================================================

    def _log_event(self, level, message):

        timestamp = time.time()

        log_entry = {
            'timestamp': timestamp,
            'level': level,
            'message': message
        }

        self.log_buffer.append(log_entry)

        if len(self.log_buffer) > self.max_log_entries:
            self.log_buffer.pop(0)

        time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))

        print(f"[{time_str}] [{level}] {message}")

        if self.socketio:
            try:
                self.socketio.emit('log_event', log_entry)
            except:
                pass

    # ==========================================================
    # SERIAL PORT DETECTION
    # ==========================================================

    def _detect_serial_port(self):

        try:

            ports = sorted(
                serial.tools.list_ports.comports(),
                key=lambda p: p.device,
                reverse=True
            )

            self._log_event("INFO", f"Scanning ports... Found {len(ports)}")

            target_keywords = ['CH340', 'CP210', 'FTDI', 'USB SERIAL', 'UART', 'USB']

            for port in ports:

                desc = (port.description or "").upper()
                hwid = (port.hwid or "").upper()

                for keyword in target_keywords:

                    if keyword in desc or keyword in hwid:

                        self._log_event(
                            "INFO",
                            f"Detected serial device: {port.device}"
                        )

                        return port.device

            for port in ports:

                if "USB" in port.device or "ACM" in port.device:
                    return port.device

            self._log_event("WARN", "No serial port detected")

            return None

        except Exception as e:

            self._log_event("ERROR", f"Port detection error: {e}")

            return None

    # ==========================================================
    # CONNECTION STATUS
    # ==========================================================

    def _emit_connection_status(self, status):

        try:

            if self.socketio:

                self.socketio.emit(
                    'connection_status',
                    {
                        'connection_status': status,
                        'timestamp': time.time(),
                        'health_score': self.telemetry_health['health_score']
                    }
                )

                print(f"📡 Sent connection status: {status}")

        except Exception as e:

            print(f"❌ Status emit error: {e}")

    # ==========================================================
    # HEALTH
    # ==========================================================

    def update_telemetry_health(self, packet_received=True):

        try:

            current_time = time.time()

            if packet_received:

                self.telemetry_health['packets_received'] += 1
                self.telemetry_health['last_valid_time'] = current_time
                self.telemetry_health['consecutive_failures'] = 0

                self.telemetry_health['health_score'] = min(
                    100,
                    self.telemetry_health['health_score'] + 5
                )

                # Use shared status calculation from modbus_control
                if self.modbus_control:
                    new_state = self.modbus_control.calculate_connection_status(self.last_packet_time)
                else:
                    # Fallback if modbus_control not available
                    new_state = 'CONNECTED'

                if self.connection_state != new_state:

                    self.connection_state = new_state

                    self._emit_connection_status(new_state)

            else:

                self.telemetry_health['packets_lost'] += 1

                self.telemetry_health['consecutive_failures'] += 1

                self.telemetry_health['health_score'] = max(
                    0,
                    self.telemetry_health['health_score'] - 5
                )

                # Use shared status calculation from modbus_control
                if self.modbus_control:
                    new_state = self.modbus_control.calculate_connection_status(self.last_packet_time)
                else:
                    # Fallback if modbus_control not available
                    time_since_last = (
                        current_time -
                        self.telemetry_health['last_valid_time']
                    )
                    if time_since_last > 8:
                        new_state = 'NO_DATA'
                    else:
                        new_state = self.connection_state

                if self.connection_state != new_state:

                    self.connection_state = new_state

                    self._emit_connection_status(new_state)

        except Exception as e:

            print(f"❌ Health update error: {e}")

    # ==========================================================
    # CONNECT SERIAL
    # ==========================================================

    def connect_serial(self):

        try:

            if self.serial_conn and self.serial_conn.is_open:

                try:
                    self.serial_conn.close()
                except:
                    pass

            if not self.port:
                self.port = self._detect_serial_port()

            if not self.port:
                return None

            self._log_event(
                "INFO",
                f"Connecting to {self.port}"
            )

            self.serial_conn = serial.Serial(

                port=self.port,

                baudrate=self.baudrate,

                timeout=0.2,

                write_timeout=0.2
            )

            if self.serial_conn.is_open:

                self._log_event(
                    "INFO",
                    f"Connected to {self.port}"
                )

                return self.serial_conn

        except Exception as e:

            self._log_event(
                "ERROR",
                f"Connection error: {e}"
            )

        return None

    # ==========================================================
    # SEQUENCE CHECK
    # ==========================================================

    def _check_sequence_gap(self, current_seq):

        if self.last_seq is not None:

            expected = self.last_seq + 1

            if current_seq > expected:

                gap = current_seq - expected

                self.packets_lost += gap

                self._log_event(
                    "WARN",
                    f"Packet loss: {gap}"
                )

        self.last_seq = current_seq

        self.total_packets_expected += 1

    # ==========================================================
    # MAIN READ LOOP
    # ==========================================================

    def read_loop(self):

        while self.running:

            try:

                # ==================================================
                # CONNECT IF NOT CONNECTED
                # ==================================================

                if not self.serial_conn or not self.serial_conn.is_open:

                    self.serial_conn = self.connect_serial()

                    if not self.serial_conn:

                        self.update_telemetry_health(False)

                        time.sleep(2)

                        continue

                # ==================================================
                # READ DATA
                # ==================================================

                waiting = self.serial_conn.in_waiting

                if waiting > 0:

                    data = self.serial_conn.read(waiting)

                    if not data:
                        continue

                    self.buffer.extend(data)

                    print(f"📡 Receiving Telemetry (LORA): {len(data)} bytes")

                # ==================================================
                # PROCESS PACKETS
                # ==================================================

                while len(self.buffer) >= SIZE:

                    sync_found = False

                    for i in range(len(self.buffer) - 1):

                        if (
                            self.buffer[i] == 0xAA and
                            self.buffer[i + 1] == 0x55
                        ):

                            if i > 0:

                                del self.buffer[:i]

                            sync_found = True

                            break

                    # ==================================================
                    # FIXED RECOVERY LOGIC
                    # ==================================================

                    if not sync_found:

                        if len(self.buffer) > SIZE * 2:

                            print("⚠️ Sync lost - trimming buffer")

                            self.buffer = self.buffer[-SIZE:]

                        break

                    # ==================================================
                    # WAIT FOR COMPLETE PACKET
                    # ==================================================

                    if len(self.buffer) < SIZE:
                        break

                    packet = bytes(self.buffer[:SIZE])

                    # ==================================================
                    # VALIDATE PACKET
                    # ==================================================

                    if validate_packet(packet):

                        telemetry = decode_telemetry(packet)

                        if telemetry:

                            self._check_sequence_gap(
                                telemetry['seq']
                            )

                            print(
                                f"Emitting telemetry: "
                                f"Seq={telemetry['seq']}, "
                                f"Temp={telemetry['temp']:.1f}°C"
                            )

                            # Update health metrics regardless of publication state
                            self.last_packet_time = time.time()
                            self.update_telemetry_health(True)

                            # Check if publication is enabled via Modbus coil
                            publication_enabled = True
                            if self.modbus_control:
                                with self.modbus_control.coil_lock:
                                    publication_enabled = self.modbus_control.coil[0]

                            if publication_enabled:
                                try:

                                    if self.telemetry_callback:

                                        self.telemetry_callback(
                                            telemetry
                                        )

                                    else:

                                        self.socketio.emit(
                                            'telemetry',
                                            telemetry,
                                            namespace='/'
                                        )

                                    print(
                                        "CRC OK - "
                                        "Real telemetry decoded (LORA) - Published"
                                    )

                                except Exception as emit_error:

                                    print(
                                        f"❌ Emit error: {emit_error}"
                                    )
                                    # Continue processing even if emit fails
                                    # The serial connection should stay alive
                            else:
                                print(
                                    "CRC OK - "
                                    "Real telemetry decoded (LORA) - Publication disabled"
                                )

                        else:

                            print("❌ Decode failed")

                            self.update_telemetry_health(
                                False
                            )

                    else:

                        print("❌ CRC ERROR")

                        self.update_telemetry_health(
                            False
                        )

                    # ==================================================
                    # SAFE BUFFER REMOVE
                    # ==================================================

                    try:

                        del self.buffer[:SIZE]

                    except:

                        self.buffer.clear()

                time.sleep(0.02)

            except Exception as e:

                print(f"❌ Read loop error: {e}")
                print("🔄 Attempting to recover serial connection...")
                print("⏳ Waiting 2 seconds for USB to stabilize...")

                try:

                    if self.serial_conn:

                        self.serial_conn.close()

                except:
                    pass

                self.serial_conn = None

                # Wait longer for USB to stabilize before reconnection
                time.sleep(2.0)

    # ==========================================================
    # START
    # ==========================================================

    def start(self):

        try:

            self.running = True

            self.thread = threading.Thread(
                target=self.read_loop,
                daemon=True
            )

            self.thread.start()

            print("📡 Serial reader started")

            return True

        except Exception as e:

            print(f"❌ Start error: {e}")

            return False

    # ==========================================================
    # MODBUS CONTROL LINK
    # ==========================================================

    def set_modbus_control(self, modbus_control):

        self.modbus_control = modbus_control

        self._log_event(
            "INFO",
            "Serial reader connection control linked"
        )

    # ==========================================================
    # STOP
    # ==========================================================

    def stop(self):

        try:

            self.running = False

            if self.serial_conn and self.serial_conn.is_open:

                self.serial_conn.close()

            if self.thread:

                self.thread.join(timeout=2)

            print("📡 Serial reader stopped")

        except Exception as e:

            print(f"❌ Stop error: {e}")