import socket
import threading
import struct
import time

class ModbusControl:
    """
    Custom Modbus TCP Server for Ground-Station Link Control
    
    This is the actual active Modbus server used by app.py.
    telemetry-port.py is legacy/test and should not be used by the running dashboard.
    
    Server Configuration:
    - Host: 0.0.0.0
    - Port: 502
    - Unit ID: 1
    - Coil Address: 0
    - Functions: FC1 (Read Coils), FC5 (Write Single Coil)
    
    Coil 0 Meanings:
    - 1 = ground-station link enabled (telemetry publication ON)
    - 0 = ground-station link disabled (telemetry publication OFF)
    
    IMPORTANT: This controls ground-station telemetry publication, NOT satellite telecommands.
    """
    
    def __init__(self, serial_reader, socketio=None):
        self.serial_reader = serial_reader
        self.socketio = socketio
        self.server_socket = None
        self.coil = [True]  # Single coil: False=link disabled, True=link enabled - Start with enabled
        self.running = False
        self.disconnect_count = 0
        self.connect_count = 0
        self.last_action_time = 0
        self.coil_lock = threading.Lock()  # Thread-safe coil access
        
        # Add missing attributes for status endpoint
        self.host = '0.0.0.0'
        self.port = 502
        self.unit_id = 1
        
        self.COIL_DESCRIPTION = {
            0: "GROUND LINK CONTROL (0=Disabled, 1=Enabled)"
        }
        
    def start(self):
        """Start the custom Modbus TCP server on port 502"""
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind(('0.0.0.0', self.port))
            self.server_socket.listen(5)
            self.running = True

            print("🔧 Modbus TCP Server started on port 502")
            print("📡 Server: 0.0.0.0:502, Unit ID: 1")
            print("🎯 Coil 0: GROUND LINK CONTROL (0=Disabled, 1=Enabled)")

            # Start server thread
            server_thread = threading.Thread(target=self._server_loop, daemon=True)
            server_thread.start()

            return True

        except PermissionError as e:
            print(f"❌ Permission denied: Cannot bind to port {self.port}. Port may be in use or require elevated privileges.")
            return False
        except OSError as e:
            print(f"❌ Failed to bind to port {self.port}: {e}")
            return False
        except Exception as e:
            print(f"❌ Failed to start Modbus server: {e}")
            return False
    
    def _server_loop(self):
        """Main server loop to handle client connections"""
        while self.running:
            try:
                client_socket, client_address = self.server_socket.accept()
                print(f"\n🔗 Modbus client connected: {client_address[0]}:{client_address[1]}")
                
                # Handle client in separate thread
                client_thread = threading.Thread(
                    target=self._handle_client, 
                    args=(client_socket, client_address),
                    daemon=True
                )
                client_thread.start()
                
            except Exception as e:
                if self.running:
                    print(f"❌ Server error: {e}")
                time.sleep(0.1)
    
    def _handle_client(self, client_socket, client_address):
        """Handle individual Modbus client requests"""
        try:
            client_socket.settimeout(30.0)  # 30 second timeout
            buffer = bytearray()
            
            while self.running:
                try:
                    data = client_socket.recv(1024)
                    if not data:
                        break
                    
                    buffer.extend(data)
                    
                    # Process all complete requests in buffer
                    while len(buffer) >= 8:  # Minimum MBAP header size
                        # Parse MBAP header to get expected length
                        transaction_id = struct.unpack('>H', buffer[0:2])[0]
                        protocol_id = struct.unpack('>H', buffer[2:4])[0]
                        length = struct.unpack('>H', buffer[4:6])[0]
                        unit_id = buffer[6]
                        
                        # Validate protocol ID
                        if protocol_id != 0:
                            print(f"❌ Invalid protocol_id ({protocol_id})")
                            break
                        
                        # Validate length (reasonable bounds)
                        if length < 2 or length > 260:  # Minimum 2 (unit_id + FC), maximum to prevent abuse
                            print(f"❌ Invalid length ({length})")
                            break
                        
                        # Check if we have the complete request
                        total_length = 6 + length  # MBAP header (6) + PDU length
                        if len(buffer) < total_length:
                            # Wait for more data
                            break
                        
                        # Extract complete request
                        request_data = bytes(buffer[:total_length])
                        del buffer[:total_length]
                        
                        # Process request
                        response = self._process_modbus_request(request_data, client_address)
                        if response:
                            client_socket.sendall(response)
                            
                except socket.timeout:
                    # Timeout is expected - check if we should continue
                    if not buffer:
                        break
                    # If we have partial data, wait a bit more
                    continue
                    
        except Exception as e:
            print(f"❌ Client handler error: {e}")
        finally:
            client_socket.close()
            print(f"🔌 Modbus client disconnected: {client_address[0]}")
    
    def _process_modbus_request(self, data, client_address):
        """Process Modbus TCP request and return response"""
        try:
            if len(data) < 8:  # Minimum MBAP header size
                return None

            # Parse MBAP header
            transaction_id = struct.unpack('>H', data[0:2])[0]
            protocol_id = struct.unpack('>H', data[2:4])[0]
            length = struct.unpack('>H', data[4:6])[0]
            unit_id = data[6]

            if protocol_id != 0:
                print(f"❌ Invalid protocol_id ({protocol_id})")
                return self._create_error_response(transaction_id, unit_id, data[7] if len(data) > 7 else 0, 4)

            if unit_id != 1:
                print(f"❌ Invalid unit_id ({unit_id})")
                return self._create_error_response(transaction_id, unit_id, data[7] if len(data) > 7 else 0, 2)

            # Parse function code
            if len(data) < 8:
                return None

            function_code = data[7]

            print(f"\n🔍 [MODBUS {function_code}] Client: {client_address[0]}")
            print(f"📊 Transaction ID: {transaction_id}, Length: {length}")

            # Process based on function code
            if function_code == 1:  # Read Coils (FC1)
                return self._handle_read_coils(data, transaction_id, unit_id)
            elif function_code == 5:  # Write Single Coil (FC5)
                return self._handle_write_single_coil(data, transaction_id, unit_id)
            else:
                print(f"❌ Unsupported function code: {function_code}")
                return self._create_error_response(transaction_id, unit_id, function_code, 1)

        except Exception as e:
            print(f"❌ Request processing error: {e}")
            return None
    
    def _handle_read_coils(self, data, transaction_id, unit_id):
        """Handle FC1 Read Coils request"""
        try:
            # Parse request
            starting_address = struct.unpack('>H', data[8:10])[0]
            quantity = struct.unpack('>H', data[10:12])[0]

            print(f"📖 Read Coils - Address: {starting_address}, Quantity: {quantity}")

            # Validate address and quantity
            if starting_address != 0 or quantity != 1:
                print(f"❌ Invalid address/quantity. Only address 0, quantity 1 supported")
                return self._create_error_response(transaction_id, unit_id, 1, 2)

            # Get coil value (thread-safe)
            with self.coil_lock:
                coil_value = self.coil[0]

            status = "Enabled" if coil_value else "Disabled"
            print(f"✅ Coil 0 ({self.COIL_DESCRIPTION[0]}): {status}")

            # Create response
            byte_count = 1
            coil_byte = 0x01 if coil_value else 0x00
            total_length = 3 + byte_count  # unit_id + function_code + byte_count + data

            response_data = struct.pack('>HHHBB',
                transaction_id,  # Transaction ID
                0,              # Protocol ID
                total_length,   # Correct length calculation
                unit_id,        # Unit ID
                1               # Function Code
            )
            response_data += struct.pack('B', byte_count)  # Byte count
            response_data += struct.pack('B', coil_byte)   # Coil value (1 bit)

            print(f"📤 Response: {1 if coil_value else 0}")
            return response_data

        except Exception as e:
            print(f"❌ Read coils error: {e}")
            return self._create_error_response(transaction_id, unit_id, 1, 4)
    
    def set_coils(self, addr, values):
        """Non-blocking coil setter - only updates state immediately"""
        try:
            if addr == 0 and len(values) > 0:
                new_value = bool(values[0])

                with self.coil_lock:
                    old_value = self.coil[0]

                    # Idempotent: if value unchanged, don't increment counters or start action thread
                    if old_value == new_value:
                        print(f"🔄 set_coils() called: value unchanged ({new_value}) - no action needed")
                        return True

                    print(f"🔄 set_coils() called: {old_value} -> {new_value}")

                    # Update coil value immediately
                    self.coil[0] = new_value

                    # Determine what actions need to be executed
                    actions = []
                    if new_value:
                        self.connect_count += 1
                        actions.append({
                            'type': 'connect',
                            'message': '✅ TELEMETRY TURNED ON - Connection established',
                            'status': 'CONNECTED'
                        })
                    else:
                        self.disconnect_count += 1
                        actions.append({
                            'type': 'disconnect',
                            'message': '🔇 TELEMETRY TURNED OFF - Connection terminated',
                            'status': 'DISCONNECTED'
                        })

                # Execute actions in background thread (non-blocking)
                threading.Thread(target=self._execute_actions, args=(actions,), daemon=True).start()

                print(f"✅ Coil 0 updated immediately to: {new_value}")
                return True
            else:
                print(f"❌ Invalid address or values: addr={addr}, values={values}")
                return False

        except Exception as e:
            print(f"❌ set_coils error: {e}")
            return False
    
    def _execute_actions(self, actions):
        """Execute heavy operations in background thread"""
        try:
            for action in actions:
                print(f"🔄 Background action executing: {action['type']}")

                if action['type'] == 'connect':
                    print(action['message'])
                    print("MODBUS CONTROL | GROUND LINK ENABLED")
                    print("SATELLITE TELECOMMAND: NOT IMPLEMENTED")

                elif action['type'] == 'disconnect':
                    print(action['message'])
                    print("MODBUS CONTROL | GROUND LINK DISABLED")
                    print("SATELLITE TELECOMMAND: NOT IMPLEMENTED")

            print(f"✅ Background actions completed")

        except Exception as e:
            print(f"❌ Background action execution error: {e}")
    
    def _handle_write_single_coil(self, data, transaction_id, unit_id):
        """Handle FC5 Write Single Coil request"""
        try:
            # Parse request
            starting_address = struct.unpack('>H', data[8:10])[0]
            output_value = struct.unpack('>H', data[10:12])[0]

            print(f"✍️  Write Single Coil - Address: {starting_address}, Value: {output_value}")

            # Validate address
            if starting_address != 0:
                print(f"❌ Invalid address. Only address 0 supported")
                return self._create_error_response(transaction_id, unit_id, 5, 2)

            # Validate output value (0x0000 or 0xFF00)
            if output_value not in [0x0000, 0xFF00]:
                print(f"❌ Invalid output value: {output_value}. Must be 0x0000 or 0xFF00")
                return self._create_error_response(transaction_id, unit_id, 5, 3)

            # Convert to boolean (0xFF00 = True, 0x0000 = False)
            new_value = (output_value == 0xFF00)

            # Use non-blocking set_coils method
            success = self.set_coils(starting_address, [new_value])

            if success:
                status = "Enabled" if new_value else "Disabled"
                print(f"✅ Coil 0 ({self.COIL_DESCRIPTION[0]}): {status}")
            else:
                print(f"❌ Failed to set coil value")
                return self._create_error_response(transaction_id, unit_id, 5, 4)

            # Create response (echo the request) - return immediately
            response_data = struct.pack('>HHHBBHH',
                transaction_id,  # Transaction ID
                0,              # Protocol ID
                6,              # Length (unit_id + function_code + address + value)
                unit_id,        # Unit ID
                5,              # Function Code
                starting_address, # Starting Address
                output_value    # Output Value
            )

            print(f"📤 Response: Echoed write request (non-blocking)")
            return response_data

        except Exception as e:
            print(f"❌ Write single coil error: {e}")
            return self._create_error_response(transaction_id, unit_id, 5, 4)
    
    def _create_error_response(self, transaction_id, unit_id, function_code, exception_code):
        """Create Modbus error response"""
        response_data = struct.pack('>HHHBBB',
            transaction_id,  # Transaction ID
            0,              # Protocol ID
            3,              # Length (unit_id + function_code + exception_code)
            unit_id,        # Unit ID
            function_code | 0x80,  # Function Code with error bit set
            exception_code  # Exception Code
        )
        return response_data

    def calculate_connection_status(self, last_packet_time):
        """
        Shared backend status calculation.

        Rules:
        - Coil 0=False → DISCONNECTED, regardless of incoming telemetry
        - Coil 0=True and valid telemetry received within 8 seconds → CONNECTED
        - Coil 0=True without recent valid telemetry → NO_DATA

        Args:
            last_packet_time: Unix timestamp of last valid telemetry packet, or None

        Returns:
            String: 'DISCONNECTED', 'CONNECTED', or 'NO_DATA'
        """
        with self.coil_lock:
            link_enabled = self.coil[0]

        if not link_enabled:
            return 'DISCONNECTED'

        if last_packet_time:
            time_since_last = time.time() - last_packet_time
            if time_since_last < 8:
                return 'CONNECTED'
            else:
                return 'NO_DATA'
        else:
            return 'NO_DATA'

    def stop(self):
        """Stop the Modbus server"""
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        print("🛑 Modbus server stopped")
