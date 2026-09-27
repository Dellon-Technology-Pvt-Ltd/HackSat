from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import os
import sys
import time
import platform
import threading

# Add modules to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'modules'))

# Import serial reader for LORA wireless communication
from modules.serial_reader import SerialReader
from modules.modbus_control import ModbusControl
from modules.antenna import AntennaTracker

app = Flask(__name__)
app.config['SECRET_KEY'] = 'satellite_mission_control_2024'
socketio = SocketIO(app, cors_allowed_origins="*", ping_timeout=60, ping_interval=25)

# Initialize components
serial_reader = None
modbus_control = None
antenna_tracker = None

# Simulation mode
simulation_mode = False
simulation_thread = None
simulation_running = False

# Heartbeat thread
heartbeat_thread = None
heartbeat_running = False

@app.route('/')
def index():
    """Serve the main dashboard page"""
    return render_template('index.html')


# ==========================================
# TELECOMMAND STORAGE
# ==========================================

telecommand_data = {
    "adcs_mode": "NOMINAL",

    # Target attitude values (set by telecommands)
    "target_roll": None,
    "target_pitch": None,
    "target_yaw": None,

    # Legacy fields for backward compatibility
    "roll": None,
    "pitch": None,
    "yaw": None,

    # Antenna tracking mode: "AUTO" or "MANUAL"
    "antenna_mode": "AUTO",

    "azimuth": None,
    "elevation": None
}

# ADCS simulation parameters
MODE_TRANSITION_DELAY = 2.0  # seconds for mode transition

# Command status tracking
command_status = {
    "status": "IDLE",  # IDLE, SENDING, ACK_RECEIVED, EXECUTING, COMPLETED
    "command": None,
    "timestamp": None
}

# Mode transition state
mode_transition = {
    "in_transition": False,
    "target_mode": None,
    "start_time": None
}

# Communication state machine
comm_state = {
    "state": "LOST",  # LOST, ACQUIRING, TRACKING, LOCKED
    "timestamp": None
}

# Command log (last 20 entries)
command_log = []

# Telecommand override timeout
telecommand_override_time = None
TELECOMMAND_OVERRIDE_DURATION = 5.0  # seconds


@app.route('/send_telecommand', methods=['POST'])
def send_telecommand():

    data = request.json

    # Update command status
    command_status["status"] = "SENDING"
    command_status["command"] = str(data)
    command_status["timestamp"] = time.time()

    # Update ADCS mode if provided
    if "adcs_mode" in data:
        target_mode = data["adcs_mode"]
        # Initiate mode transition
        mode_transition["in_transition"] = True
        mode_transition["target_mode"] = target_mode
        mode_transition["start_time"] = time.time()
        telecommand_data["adcs_mode"] = "TRANSITIONING"
        add_command_log_entry(f"ADCS MODE -> {target_mode}")

    # Update ADCS attitude target values if provided
    global telecommand_override_time
    attitude_command_sent = False

    if "roll" in data and data["roll"] is not None:
        telecommand_data["target_roll"] = data["roll"]
        # For backward compatibility
        telecommand_data["roll"] = data["roll"]
        add_command_log_entry(f"TARGET ROLL -> {data['roll']}°")
        attitude_command_sent = True

    if "pitch" in data and data["pitch"] is not None:
        telecommand_data["target_pitch"] = data["pitch"]
        # For backward compatibility
        telecommand_data["pitch"] = data["pitch"]
        add_command_log_entry(f"TARGET PITCH -> {data['pitch']}°")
        attitude_command_sent = True

    if "yaw" in data and data["yaw"] is not None:
        telecommand_data["target_yaw"] = data["yaw"]
        # For backward compatibility
        telecommand_data["yaw"] = data["yaw"]
        add_command_log_entry(f"TARGET YAW -> {data['yaw']}°")
        attitude_command_sent = True

    # Set override timeout if attitude commands were sent
    if attitude_command_sent:
        telecommand_override_time = time.time()
        add_command_log_entry("TELECOMMAND OVERRIDE ACTIVE (5s)")

    # Update antenna values if provided
    if "azimuth" in data and data["azimuth"] is not None:
        telecommand_data["azimuth"] = data["azimuth"]
        telecommand_data["antenna_mode"] = "MANUAL"
        add_command_log_entry(f"AZIMUTH -> {data['azimuth']}° (MANUAL)")

    if "elevation" in data and data["elevation"] is not None:
        telecommand_data["elevation"] = data["elevation"]
        telecommand_data["antenna_mode"] = "MANUAL"
        add_command_log_entry(f"ELEVATION -> {data['elevation']}° (MANUAL)")

    # Update antenna mode if provided
    if "antenna_mode" in data:
        telecommand_data["antenna_mode"] = data["antenna_mode"]
        add_command_log_entry(f"ANTENNA MODE -> {data['antenna_mode']}")

    print("\n========== TELECOMMAND RECEIVED ==========")
    print("Target Spacecraft: AgniSat")
    print("ADCS Mode         :", telecommand_data["adcs_mode"])
    print("Target Roll       :", telecommand_data["target_roll"])
    print("Target Pitch      :", telecommand_data["target_pitch"])
    print("Target Yaw        :", telecommand_data["target_yaw"])
    print("Antenna Mode      :", telecommand_data["antenna_mode"])
    print("Azimuth           :", telecommand_data["azimuth"])
    print("Elevation         :", telecommand_data["elevation"])
    print("==========================================\n")

    # Update command status to ACK_RECEIVED
    command_status["status"] = "ACK_RECEIVED"
    socketio.emit('command_status', command_status)

    # Simulate execution delay
    command_status["status"] = "EXECUTING"
    socketio.emit('command_status', command_status)

    return jsonify({
        "status": "success"
    })


@app.route('/system_info')
def system_info():
    """Get system information for cross-platform compatibility"""
    try:
        system_info = {
            'platform': platform.system(),
            'platform_release': platform.release(),
            'platform_version': platform.version(),
            'architecture': platform.machine(),
            'processor': platform.processor(),
            'python_version': platform.python_version(),
            'serial_ports': serial_reader._get_available_ports() if serial_reader else [],
            'current_port': serial_reader.port if serial_reader else 'Unknown'
        }
        return jsonify(system_info)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/modbus_status')
def modbus_status():
    """Get Modbus server status"""
    global modbus_control
    try:
        if modbus_control:
            status = {
                'running': modbus_control.running,
                'host': modbus_control.host,
                'port': modbus_control.port,
                'unit_id': modbus_control.unit_id,
                'coil_0': modbus_control.coil[0],
                'connect_count': modbus_control.connect_count,
                'disconnect_count': modbus_control.disconnect_count
            }
            return jsonify(status)
        else:
            return jsonify({'status': 'error', 'message': 'Modbus control not initialized'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/recover', methods=['POST'])
def recover():
    """Recovery endpoint to restore telemetry link"""
    global modbus_control
    try:
        if modbus_control:
            print("🔄 Recovery endpoint called")
            
            # Use non-blocking set_coils method
            success = modbus_control.set_coils(0, [True])
            
            if success:
                print("✅ Recovery: Coil set to ON via set_coils()")
                return jsonify({'status': 'success', 'message': 'Link recovery successful'})
            else:
                print("❌ Recovery: Failed to set coil")
                return jsonify({'status': 'error', 'message': 'Failed to set recovery coil'})
        else:
            return jsonify({'status': 'error', 'message': 'Modbus control not initialized'})
    except Exception as e:
        print(f"❌ Recovery endpoint error: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/scan_ports')
def scan_ports():
    """Scan for available serial ports"""
    try:
        if serial_reader:
            ports = serial_reader._get_available_ports()
            return jsonify({'ports': ports, 'current': serial_reader.port})
        else:
            return jsonify({'error': 'Serial reader not initialized'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    print('🔗 Client connected')
    emit('status', {'connected': False, 'message': 'Initializing...'})

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    print('🔌 Client disconnected')

@socketio.on('request_telemetry')
def handle_telemetry_request():
    """Handle telemetry status request"""
    if serial_reader and serial_reader.last_packet_time:
        time_since_last = time.time() - serial_reader.last_packet_time
        if time_since_last < 5:
            socketio.emit('status', {'connected': True, 'message': 'LIVE'})
        else:
            socketio.emit('status', {'connected': False, 'message': 'DISCONNECTED'})
    else:
        socketio.emit('status', {'connected': False, 'message': 'NO DATA'})

def enhance_telemetry_with_antenna(telemetry):
    """Enhance telemetry data with antenna tracking information"""
    try:
        if antenna_tracker and telemetry:
            antenna_data = antenna_tracker.get_antenna_data(telemetry)
            if antenna_data:
                telemetry.update(antenna_data)
    except Exception as e:
        print(f"❌ Antenna data enhancement error: {e}")
    return telemetry

def update_mode_transition():
    """Update ADCS mode transition state"""
    global mode_transition, telecommand_data

    if mode_transition["in_transition"]:
        elapsed = time.time() - mode_transition["start_time"]
        if elapsed >= MODE_TRANSITION_DELAY:
            # Transition complete
            telecommand_data["adcs_mode"] = mode_transition["target_mode"]
            mode_transition["in_transition"] = False
            mode_transition["target_mode"] = None
            mode_transition["start_time"] = None
            print(f"✅ Mode transition complete: {telecommand_data['adcs_mode']}")

def add_command_log_entry(message):
    """Add entry to command log (keep last 20)"""
    global command_log
    timestamp = time.strftime("[%H:%M:%S]")
    command_log.append(f"{timestamp} {message}")
    if len(command_log) > 20:
        command_log.pop(0)
    socketio.emit('command_log', command_log)

def update_communication_state():
    """Update communication state machine based on connection status and telemetry"""
    global comm_state, modbus_control

    if modbus_control and modbus_control.coil[0]:
        # Connection is active
        if comm_state["state"] == "LOST":
            comm_state["state"] = "ACQUIRING"
            comm_state["timestamp"] = time.time()
            add_command_log_entry("LINK ACQUIRING")
        elif comm_state["state"] == "ACQUIRING":
            # After 2 seconds, transition to TRACKING
            if time.time() - comm_state["timestamp"] >= 2.0:
                comm_state["state"] = "TRACKING"
                comm_state["timestamp"] = time.time()
                add_command_log_entry("LINK TRACKING")
        elif comm_state["state"] == "TRACKING":
            # After 2 seconds, transition to LOCKED
            if time.time() - comm_state["timestamp"] >= 2.0:
                comm_state["state"] = "LOCKED"
                comm_state["timestamp"] = time.time()
                add_command_log_entry("LINK LOCKED")
    else:
        # Connection is inactive
        if comm_state["state"] != "LOST":
            comm_state["state"] = "LOST"
            comm_state["timestamp"] = time.time()
            add_command_log_entry("LINK LOST")

def handle_telemetry_data(telemetry):
    """Handle incoming telemetry data and enhance it"""

    # Update mode transition state
    update_mode_transition()

    # Update communication state machine
    update_communication_state()

    # Add antenna tracking data
    enhanced_telemetry = enhance_telemetry_with_antenna(telemetry)

    # Add connection status from modbus control
    global modbus_control
    if modbus_control:
        enhanced_telemetry['connection_status'] = {
            'coil_0': modbus_control.coil[0],
            'connect_count': modbus_control.connect_count,
            'disconnect_count': modbus_control.disconnect_count
        }

    # ==========================================
    # TELEMETRY IS MASTER SOURCE
    # ==========================================

    # All attitude values come from live telemetry
    # Telecommands only set targets for display, not actual values
    enhanced_telemetry["roll"] = telemetry.get("roll", 0.0)
    enhanced_telemetry["pitch"] = telemetry.get("pitch", 0.0)
    enhanced_telemetry["yaw"] = telemetry.get("yaw", 0.0)

    # Send target values for display (operator intent)
    enhanced_telemetry["target_roll"] = telecommand_data["target_roll"]
    enhanced_telemetry["target_pitch"] = telecommand_data["target_pitch"]
    enhanced_telemetry["target_yaw"] = telecommand_data["target_yaw"]

    # ==========================================
    # TELECOMMAND OVERRIDE SIMULATION
    # ==========================================
    # Check if telecommand override has expired (after 5 seconds)
    global telecommand_override_time
    if telecommand_override_time is not None:
        if time.time() - telecommand_override_time > TELECOMMAND_OVERRIDE_DURATION:
            # Override expired, revert to live telemetry
            telecommand_override_time = None
            add_command_log_entry("TELECOMMAND OVERRIDE EXPIRED - REVERTING TO TELEMETRY")
        else:
            # Override still active, use telecommand values
            if telecommand_data["target_roll"] is not None:
                enhanced_telemetry["roll"] = telecommand_data["target_roll"]
            if telecommand_data["target_pitch"] is not None:
                enhanced_telemetry["pitch"] = telecommand_data["target_pitch"]
            if telecommand_data["target_yaw"] is not None:
                enhanced_telemetry["yaw"] = telecommand_data["target_yaw"]

    # ==========================================
    # APPLY PERSISTENT TELECOMMAND OVERRIDES
    # ==========================================

    # ADCS mode is persistent - remains until changed
    if telecommand_data["adcs_mode"]:
        enhanced_telemetry["adcs_mode"] = telecommand_data["adcs_mode"]

    # Antenna: AUTO mode uses live telemetry, MANUAL mode uses commanded values
    if telecommand_data["antenna_mode"] == "MANUAL":
        if telecommand_data["azimuth"] is not None:
            enhanced_telemetry["azimuth"] = telecommand_data["azimuth"]
        if telecommand_data["elevation"] is not None:
            enhanced_telemetry["elevation"] = telecommand_data["elevation"]
    # AUTO mode: use live telemetry from antenna tracker (already in enhanced_telemetry)

    # Legacy fields for backward compatibility
    if telecommand_data["roll"] is not None:
        enhanced_telemetry["roll_legacy"] = telecommand_data["roll"]

    if telecommand_data["pitch"] is not None:
        enhanced_telemetry["pitch_legacy"] = telecommand_data["pitch"]

    if telecommand_data["yaw"] is not None:
        enhanced_telemetry["yaw_legacy"] = telecommand_data["yaw"]

    # Add antenna mode to telemetry
    enhanced_telemetry["antenna_mode"] = telecommand_data["antenna_mode"]

    # Add communication state to telemetry
    enhanced_telemetry["comm_state"] = comm_state["state"]

    # Update command status to COMPLETED
    global command_status
    if command_status["status"] == "EXECUTING":
        command_status["status"] = "COMPLETED"
        socketio.emit('command_status', command_status)

    # Emit to all connected clients
    socketio.emit('telemetry', enhanced_telemetry)
@socketio.on('get_connection_status')
def handle_get_connection_status():
    """Handle request for current connection status"""
    global modbus_control
    if modbus_control:
        status_data = {
            'connection_status': 'CONNECTED' if modbus_control.coil[0] else 'DISCONNECTED',
            'connect_count': modbus_control.connect_count,
            'disconnect_count': modbus_control.disconnect_count,
            'timestamp': time.time()
        }
        emit('connection_status_response', status_data)
        print(f"📡 Sent connection status: {status_data['connection_status']}")

@socketio.on('recover_link')
def handle_recover_link():
    """Handle recovery link request"""
    global modbus_control
    print("🔄 Recovery link request received")
    
    try:
        if modbus_control:
            # Use non-blocking set_coils method
            success = modbus_control.set_coils(0, [True])
            
            if success:
                print("✅ Recovery: Coil set to ON via set_coils()")
                
                # Emit success response
                emit('recovery_response', {'success': True, 'message': 'Link recovery successful'})
                
                # Emit status change to all clients
                status_data = {
                    'connection_status': 'RECOVERED',
                    'connect_count': modbus_control.connect_count,
                    'disconnect_count': modbus_control.disconnect_count,
                    'timestamp': time.time()
                }
                socketio.emit('connection_status', status_data)
                
                print("✅ Recovery response sent to client")
            else:
                print("❌ Recovery: Failed to set coil")
                emit('recovery_response', {'success': False, 'error': 'Failed to set recovery coil'})
        else:
            emit('recovery_response', {'success': False, 'error': 'Modbus control not available'})
            
    except Exception as e:
        print(f"❌ Recovery handler error: {e}")
        emit('recovery_response', {'success': False, 'error': str(e)})

@socketio.on('send_command')
def handle_send_command(data):

    try:

        print("\n========== TELECOMMAND RECEIVED ==========")

        print("Command :", data.get("command"))
        print("Value   :", data.get("value"))

        print("==========================================\n")

        emit(
            'command_ack',
            {
                'status': 'success',
                'command': data.get("command"),
                'value': data.get("value")
            }
        )

    except Exception as e:

        print(f"❌ Telecommand error: {e}")

        emit(
            'command_ack',
            {
                'status': 'error',
                'message': str(e)
            }
        )

def emit_connection_status():
    """Emit connection status to all clients"""
    global modbus_control
    if modbus_control:
        status_data = {
            'connection_status': 'CONNECTED' if modbus_control.coil[0] else 'DISCONNECTED',
            'connect_count': modbus_control.connect_count,
            'disconnect_count': modbus_control.disconnect_count,
            'timestamp': time.time()
        }
        socketio.emit('connection_status', status_data)

def generate_simulation_telemetry():
    """Generate simulated telemetry data for testing"""
    import math
    import random
    
    seq_counter = 0
    sim_time = 0
    
    while simulation_running:
        try:
            sim_time += 2.0  # 2 second interval
            
            # Generate realistic satellite telemetry
            telemetry = {
                "apid": 1,
                "seq": seq_counter,
                "mission_time": int(sim_time * 1000),
                
                # Housekeeping
                "temp": round(20 + 5 * math.sin(sim_time * 0.1) + random.uniform(-0.5, 0.5), 2),
                "humidity": round(50 + 10 * math.cos(sim_time * 0.05) + random.uniform(-2, 2), 2),
                
                # ADCS
                "acc": [round(random.uniform(-0.1, 0.1), 3) for _ in range(3)],
                "gyro": [round(random.uniform(-0.05, 0.05), 3) for _ in range(3)],
                "roll": round(10 + 5 * math.sin(sim_time * 0.2), 2),
                "pitch": round(-5 + 3 * math.cos(sim_time * 0.15), 2),
                "yaw": round((sim_time * 10) % 360, 2),
                "adcs_mode": telecommand_data["adcs_mode"],
                
                # Navigation (simulated LEO orbit)
                "lat": round(18.5204 + 0.1 * math.sin(sim_time * 0.1), 6),
                "lon": round(73.8567 + 0.1 * math.cos(sim_time * 0.1), 6),
                "alt": round(400000 + 10000 * math.sin(sim_time * 0.05), 1),  # 400 km LEO
                "speed": round(28000 + random.uniform(-100, 100), 1),  # 7.8 km/s
                "utc": int(sim_time * 1000),
                "sat_count": random.randint(6, 12),
                "fix": 1,
                "hdop": round(1.0 + random.uniform(0, 0.5), 2),
                "orbit": "LEO",
                
                # Payload
                "radiation": round(0.18 + random.uniform(0, 0.02), 5)
            }
            
            seq_counter += 1
            
            # Process through the same pipeline as real telemetry
            handle_telemetry_data(telemetry)
            
            time.sleep(2.0)  # 2 second telemetry interval
            
        except Exception as e:
            print(f"❌ Simulation error: {e}")
            time.sleep(1.0)

def start_simulation():
    """Start simulation mode"""
    global simulation_thread, simulation_running
    simulation_running = True
    simulation_thread = threading.Thread(target=generate_simulation_telemetry, daemon=True)
    simulation_thread.start()
    print("🎮 Simulation mode started")

def stop_simulation():
    """Stop simulation mode"""
    global simulation_running
    simulation_running = False
    if simulation_thread:
        simulation_thread.join(timeout=2)
    print("🛑 Simulation mode stopped")

def initialize_system():
    """Initialize all system components"""
    global serial_reader, modbus_control, antenna_tracker, simulation_mode
    
    print("🚀 Initializing Cross-Platform Satellite Mission Control System...")
    print(f"🖥️  Platform: {platform.system()} {platform.release()}")
    print(f"🐍 Python: {platform.python_version()}")
    
    # Initialize antenna tracker
    antenna_tracker = AntennaTracker()
    print("📡 Antenna tracker initialized")
    
    # Check if simulation mode is enabled
    if simulation_mode:
        print("🎮 SIMULATION MODE ENABLED")
        print("⚠️  Using simulated telemetry instead of hardware")
        
        # Initialize Modbus Control (still needed for telecommand interface)
        modbus_control = ModbusControl(None, socketio)
        modbus_control.start()
        print("🔧 Modbus control started")
        
        # Start simulation
        start_simulation()
    else:
        # Normal hardware mode
        # Initialize serial reader for LORA wireless communication
        serial_reader = SerialReader(socketio)
        serial_reader.telemetry_callback = handle_telemetry_data

        if serial_reader.start():
            print("✅ LORA wireless receiver started")
        else:
            print("❌ Failed to start serial receiver")
        
        # Initialize Modbus Control with serial_reader
        modbus_control = ModbusControl(serial_reader, socketio)
        modbus_control.start()
        print("🔧 Modbus control started")
        
        # Set modbus control reference in serial_reader for connection checking
        serial_reader.set_modbus_control(modbus_control)
        print("📡 Serial reader connection control linked")
    
    # Start heartbeat to keep socket.io connections alive
    start_heartbeat()
    
    print("✅ Cross-platform system initialization complete")

def heartbeat_function():
    """Heartbeat function to keep socket.io connections alive"""
    global heartbeat_running, serial_reader, modbus_control
    
    while heartbeat_running:
        try:
            # Send periodic connection status to keep connection alive
            if modbus_control:
                status_data = {
                    'connection_status': 'CONNECTED' if modbus_control.coil[0] else 'DISCONNECTED',
                    'timestamp': time.time()
                }
                socketio.emit('connection_status', status_data, namespace='/')
            
            time.sleep(10)  # Send heartbeat every 10 seconds
            
        except Exception as e:
            print(f"❌ Heartbeat error: {e}")
            time.sleep(5)

def start_heartbeat():
    """Start the heartbeat thread"""
    global heartbeat_thread, heartbeat_running
    
    heartbeat_running = True
    heartbeat_thread = threading.Thread(target=heartbeat_function, daemon=True)
    heartbeat_thread.start()
    print("💓 Heartbeat started")

def stop_heartbeat():
    """Stop the heartbeat thread"""
    global heartbeat_running
    
    heartbeat_running = False
    if heartbeat_thread:
        heartbeat_thread.join(timeout=2)
    print("💓 Heartbeat stopped")

def cleanup_system():
    """Clean up system resources"""
    global serial_reader, modbus_control, simulation_running, heartbeat_running
    
    print("🛑 Shutting down system...")
    
    # Stop heartbeat
    stop_heartbeat()
    
    # Stop simulation if running
    if simulation_running:
        stop_simulation()
    
    if serial_reader:
        serial_reader.stop()
        
    if modbus_control:
        modbus_control.stop()
        
    print("✅ Cleanup complete")

if __name__ == '__main__':
    try:
        # Initialize system
        initialize_system()
        
        # Start Flask-SocketIO server
        print("🌐 Starting web server on http://localhost:5000")
        print("🔧 Modbus TCP server on port 502")
        socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
        
    except KeyboardInterrupt:
        print("\n⚠️ KeyboardInterrupt received")
        cleanup_system()
        
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        cleanup_system()
        sys.exit(1)
