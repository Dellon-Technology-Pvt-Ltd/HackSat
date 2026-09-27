// Mission Control Dashboard JavaScript with WebRTC Support
class MissionControlDashboard {
    constructor() {
        this.socket = io({
            reconnection: true,
            reconnectionAttempts: Infinity,
            reconnectionDelay: 1000,
            reconnectionDelayMax: 5000,
            timeout: 10000
        });
        this.telemetryData = {};
        this.charts = {};
        this.attitudeCanvas = null;
        this.attitudeCtx = null;
        this.lastUpdateTime = null;
        this.heartbeatInterval = null;
        this.telemetryTimeout = null;
        
        // Antenna tracking animation variables
        this.antennaAnimation = {
            angle: 0,
            currentBeamAngle: 0,
            targetBeamAngle: 0,
            animationId: null,
            centerX: 0,
            centerY: 0,
            radius: 0,
            lastFrameTime: null
        };
        
        // Compass animation variables
        this.compassAnimation = {
            currentAngle: 0,
            targetAngle: 0,
            animationId: null
        };
        
        // Shared antenna state - single source of truth
        this.sharedAntennaState = {
            azimuth: 0,  // degrees (0° = North, 90° = East, 180° = South, 270° = West)
            elevation: 0,
            isTracking: true,
            lastUpdateTime: null
        };
        
        // Unified antenna tracking state
        this.antennaState = {
            azimuth: 0,
            elevation: 0
        };
        
        // WebRTC variables
        this.localConnection = null;
        this.remoteConnection = null;
        this.dataChannel = null;
        this.signalingSocket = null;
        this.isInitiator = false;
        this.peerConnectionConfig = {
            iceServers: [
                { urls: 'stun:stun.l.google.com:19302' }
            ]
        };
        
        // Initialize dashboard
        this.initializeCharts();
        this.startCompassAnimation(0);
        this.setupSocketListeners();
        this.setupRecoveryButton();
        this.startRealtimeUpdates();
        this.initializeAttitudeIndicator();
        this.startAnimations();
        this.initWebRTC();
    }

    setupRecoveryButton() {
        const recoveryBtn = document.getElementById('recovery-btn');
        if (recoveryBtn) {
            recoveryBtn.addEventListener('click', () => {
                this.recoverLink();
            });
        }
    }
    
    startRealtimeUpdates() {
        // Poll for connection status updates every 1 second
        setInterval(() => {
            this.requestConnectionStatus();
        }, 1000);
    }
    
    requestConnectionStatus() {
        // Request current connection status from backend
        this.socket.emit('get_connection_status');
    }
    
    setupSocketListeners() {
        this.socket.on('connect', () => {
            console.log('Connected to server');
            this.updateConnectionStatus('CONNECTED', 'success');
            // Request telemetry data immediately after reconnection
            this.socket.emit('request_telemetry');
            // Start periodic telemetry requests as fallback
            this.startPeriodicTelemetryRequest();
        });

        this.socket.on('disconnect', () => {
            console.log('Disconnected from server');
            this.updateConnectionStatus('DISCONNECTED', 'danger');
            // Stop periodic requests when disconnected
            this.stopPeriodicTelemetryRequest();
        });

        this.socket.on('reconnect', (attemptNumber) => {
            console.log('Reconnected to server after', attemptNumber, 'attempts');
            this.updateConnectionStatus('CONNECTED', 'success');
            this.addAlert('Connection restored', 'success');
            // Request telemetry data after reconnection
            this.socket.emit('request_telemetry');
            // Restart periodic requests
            this.startPeriodicTelemetryRequest();
        });

        this.socket.on('reconnect_attempt', (attemptNumber) => {
            console.log('Reconnection attempt:', attemptNumber);
            this.updateConnectionStatus('RECONNECTING...', 'warning');
        });

        this.socket.on('reconnect_failed', () => {
            console.log('Reconnection failed');
            this.updateConnectionStatus('CONNECTION FAILED', 'danger');
            this.addAlert('Failed to reconnect to server', 'error');
        });

        this.socket.on('telemetry', (data) => {
            this.updateTelemetry(data);
        });

        this.socket.on('connection_status', (status) => {
            this.updateSatelliteConnectionStatus(status);
        });

        this.socket.on('connection_error', (data) => {
            console.error('Connection error:', data.error);
            this.updateConnectionStatus('ERROR', 'danger');
            this.addAlert('Connection Error: ' + data.error, 'critical');
        });

        this.socket.on('history_data', (data) => {
            this.updateCharts(data);
        });

        // Handle recovery response
        this.socket.on('recovery_response', (response) => {
            if (response.success) {
                this.addAlert('Link recovery successful!', 'success');
            } else {
                this.addAlert('Link recovery failed: ' + response.error, 'error');
            }
        });

        // Request initial data
        this.socket.emit('request_telemetry');
    }

    recoverLink() {
        console.log('🔄 Recover Link button clicked');
        this.addAlert('Attempting to recover satellite link...', 'info');
        
        // Send recovery command to backend
        this.socket.emit('recover_link');
    }

    initWebRTC() {
        try {
            // Connect to WebRTC signaling server
            this.signalingSocket = new WebSocket('ws://localhost:8765');
            
            this.signalingSocket.onopen = () => {
                console.log('Connected to WebRTC signaling server');
                this.addAlert('WebRTC signaling connected', 'success');
                
                // Join default room
                this.signalingSocket.send(JSON.stringify({
                    type: 'join',
                    room_id: 'mission_control'
                }));
            };

            this.signalingSocket.onmessage = (event) => {
                const message = JSON.parse(event.data);
                this.handleSignalingMessage(message);
            };

            this.signalingSocket.onerror = (error) => {
                console.error('WebRTC signaling error:', error);
                this.addAlert('WebRTC signaling error: ' + error, 'danger');
            };

            this.signalingSocket.onclose = () => {
                console.log('WebRTC signaling connection closed');
                this.addAlert('WebRTC signaling disconnected', 'warning');
            };

        } catch (error) {
            console.error('Failed to initialize WebRTC:', error);
            this.addAlert('WebRTC initialization failed: ' + error, 'danger');
        }
    }

    async handleSignalingMessage(message) {
        try {
            switch (message.type) {
                case 'offer':
                    console.log('Received WebRTC offer');
                    await this.handleOffer(message);
                    break;
                    
                case 'answer':
                    console.log('Received WebRTC answer');
                    await this.handleAnswer(message);
                    break;
                    
                case 'ice_candidate':
                    console.log('Received ICE candidate');
                    await this.handleIceCandidate(message);
                    break;
                    
                case 'joined':
                    console.log('Joined room:', message.room_id);
                    this.isInitiator = true;
                    await this.createPeerConnection();
                    break;
            }
        } catch (error) {
            console.error('Error handling signaling message:', error);
        }
    }

    async createPeerConnection() {
        try {
            // Create RTCPeerConnection
            this.localConnection = new RTCPeerConnection(this.peerConnectionConfig);
            
            // Handle ICE candidates
            this.localConnection.onicecandidate = (event) => {
                if (event.candidate) {
                    console.log('Sending ICE candidate');
                    this.signalingSocket.send(JSON.stringify({
                        type: 'ice_candidate',
                        data: event.candidate,
                        target: 'peer'
                    }));
                }
            };

            // Handle remote stream
            this.localConnection.ontrack = (event) => {
                console.log('Received remote stream');
                this.remoteStream = event.streams[0];
                // Handle telemetry data from WebRTC stream
                this.setupWebRTCDataChannel();
            };

            // Create data channel for telemetry
            this.localConnection.ondatachannel = (event) => {
                console.log('Data channel established');
                const dataChannel = event.channel;
                dataChannel.onmessage = (event) => {
                    try {
                        const telemetryData = JSON.parse(event.data);
                        this.updateTelemetry(telemetryData);
                    } catch (error) {
                        console.error('Error parsing WebRTC data:', error);
                    }
                };
            };

            if (this.isInitiator) {
                // Create offer if initiator
                const dataChannel = this.localConnection.createDataChannel('telemetry');
                dataChannel.onopen = () => {
                    console.log('Data channel opened');
                };
                
                const offer = await this.localConnection.createOffer();
                await this.localConnection.setLocalDescription(offer);
                
                this.signalingSocket.send(JSON.stringify({
                    type: 'offer',
                    data: offer,
                    target: 'peer'
                }));
            }

        } catch (error) {
            console.error('Error creating peer connection:', error);
            this.addAlert('WebRTC peer connection failed: ' + error, 'danger');
        }
    }

    async handleOffer(message) {
        try {
            if (!this.localConnection) {
                await this.createPeerConnection();
            }
            
            // Set remote description before adding ICE candidates
            await this.localConnection.setRemoteDescription(message.data);
            this.remoteDescriptionSet = true;
            
            // Process any buffered ICE candidates
            await this.processBufferedIceCandidates();
            
            // Create and send answer
            const answer = await this.localConnection.createAnswer();
            await this.localConnection.setLocalDescription(answer);
            
            this.signalingSocket.send(JSON.stringify({
                type: 'answer',
                data: answer,
                target: 'peer'
            }));
            
        } catch (error) {
            console.error('Error handling offer:', error);
        }
    }

    async handleAnswer(message) {
        try {
            if (this.localConnection) {
                // Set remote description after local description is set
                await this.localConnection.setRemoteDescription(message.data);
                this.remoteDescriptionSet = true;
                
                // Process any buffered ICE candidates
                await this.processBufferedIceCandidates();
            }
        } catch (error) {
            console.error('Error handling answer:', error);
        }
    }

    async handleIceCandidate(message) {
        try {
            // Only add ICE candidate after remote description is set
            if (this.localConnection && this.remoteDescriptionSet) {
                await this.localConnection.addIceCandidate(message.data);
                console.log('ICE candidate added successfully');
            } else {
                console.log('Received ICE candidate before remote description - buffering');
                // Buffer ICE candidates until remote description is set
                this.iceCandidateBuffer.push(message.data);
            }
        } catch (error) {
            console.error('Error adding ICE candidate:', error);
        }
    }

    async processBufferedIceCandidates() {
        // Process buffered ICE candidates if any
        if (this.iceCandidateBuffer.length > 0 && this.localConnection) {
            console.log(`Processing ${this.iceCandidateBuffer.length} buffered ICE candidates`);
            for (const candidate of this.iceCandidateBuffer) {
                try {
                    await this.localConnection.addIceCandidate(candidate);
                } catch (error) {
                    console.error('Error adding buffered ICE candidate:', error);
                }
            }
            this.iceCandidateBuffer = [];
        }
    }

    setupWebRTCDataChannel() {
        // This method is called when data channel is established
        console.log('WebRTC data channel established');
    }

    updateTelemetry(data) {
        this.telemetryData = data;
        this.lastUpdateTime = new Date();
        
        console.log('📊 Received telemetry data:', data); // Debug log
        
        // Reset telemetry timeout when data is received
        this.resetTelemetryTimeout();
        
        // When telemetry is received, ensure header status is CONNECTED
        // This fixes the inconsistency where header shows DISCONNECTED but values are updating
        this.ensureConnectedStatus();
        
        // Update dashboard elements with real telemetry fields
        this.updateMissionTime(data.mission_time || 0);
        this.updateAPID(data.apid || 0);
        this.updateSequenceCount(data.seq || 0);
        this.updateUptime(data.mission_time || 0); // Use mission_time for uptime
        this.updateADCSMode(data.adcs_mode || 'UNKNOWN');
        this.updateTemperature(data.temp || 0);
        this.updateHumidity(data.humidity || 0);
        this.updateRadiation(data.radiation || 0);
        
        // Update GPS position with new field names
        this.updatePosition({
            latitude: data.lat || 0,
            longitude: data.lon || 0,
            altitude: data.alt || 0,
            speed: data.speed || 0
        });
        
        // Update IMU data
        this.updateIMUData({
            ax: data.acc && data.acc[0] || 0,
            ay: data.acc && data.acc[1] || 0,
            az: data.acc && data.acc[2] || 0,
            gx: data.gyro && data.gyro[0] || 0,
            gy: data.gyro && data.gyro[1] || 0,
            gz: data.gyro && data.gyro[2] || 0
        });
        
        // Update attitude
        this.updateAttitude({
            roll: data.roll || 0,
            pitch: data.pitch || 0,
            yaw: data.yaw || 0
        });

        // Update current attitude display in telecommand panel
        this.updateCurrentAttitudeDisplay({
            roll: data.roll || 0,
            pitch: data.pitch || 0,
            yaw: data.yaw || 0
        });
        
        // Update GPS status
        this.updateGPSStatus(data.fix || 0, data.sat_count || 0, data.hdop || 99.9);
        
        // Update orbit mode
        this.updateOrbitMode(data.orbit || 'UNKNOWN');
        
        // Update antenna tracking with proper data
        this.updateAntennaTracking({
            azimuth: data.azimuth || 0,
            elevation: data.elevation || 0,
            signal_strength: data.signal_strength || 0,
            tracking_status: data.tracking_status || 'UNKNOWN',
            pointing_offset: data.pointing_offset || 0
        });

        // Update communication state display
        this.updateCommState(data.comm_state || 'LOST');

        // Update target display with commanded target values
        this.updateTargetDisplay(data.target_roll, data.target_pitch, data.target_yaw);

        // Update charts
        this.updateRealtimeCharts(data);
    }
    
    resetTelemetryTimeout() {
        // Clear existing timeout
        if (this.telemetryTimeout) {
            clearTimeout(this.telemetryTimeout);
        }
        
        // Set new timeout to detect when telemetry stops
        this.telemetryTimeout = setTimeout(() => {
            console.log('⚠️ Telemetry timeout - no data received for 5 seconds');
            this.updateSatelliteConnectionStatus({ connection_status: 'NO_DATA' });
            // Request telemetry as fallback
            this.socket.emit('request_telemetry');
        }, 5000); // 5 seconds timeout
    }

    startPeriodicTelemetryRequest() {
        // Stop any existing periodic request
        this.stopPeriodicTelemetryRequest();
        
        // Request telemetry every 3 seconds as fallback mechanism
        this.telemetryRequestInterval = setInterval(() => {
            this.socket.emit('request_telemetry');
        }, 3000);
        
        console.log('📡 Started periodic telemetry requests (3s interval)');
    }

    stopPeriodicTelemetryRequest() {
        if (this.telemetryRequestInterval) {
            clearInterval(this.telemetryRequestInterval);
            this.telemetryRequestInterval = null;
            console.log('🛑 Stopped periodic telemetry requests');
        }
    }
    
    setAntennaTrackingState(isTracking) {
        // UNIFIED ANTENNA STATE CONTROL
        this.sharedAntennaState.isTracking = isTracking;
        this.antennaState.isTracking = isTracking;
        console.log(`📡 Antenna tracking ${isTracking ? 'RESUMED' : 'STOPPED'}`);
        
        // If tracking resumes, ensure both widgets are at correct position
        if (isTracking && this.antennaState.lastUpdateTime) {
            this.drawStaticAntennaTracking();
            this.drawStaticCompass();
            this.updateDirectionText(this.antennaState.azimuth);
        }
    }
    
    ensureConnectedStatus() {
        // Only update header to CONNECTED if communication state is LOCKED or TRACKING
        // Do not force CONNECTED if the link is LOST or ACQUIRING (Modbus attack/disconnect)
        const liveIndicator = document.querySelector('.bg-green-500, .bg-red-500, .bg-yellow-500');
        const liveText = document.querySelector('.text-green-400.text-sm, .text-red-400.text-sm, .text-yellow-400.text-sm');
        const linkStatusElement = document.getElementById('link-status');

        // Get current communication state from telemetry data
        const commState = this.telemetryData && this.telemetryData.comm_state;

        // Only show CONNECTED if link is LOCKED or TRACKING
        if (commState === 'LOCKED' || commState === 'TRACKING') {
            // Update header to LIVE
            if (liveIndicator) {
                liveIndicator.classList.remove('bg-red-500', 'bg-yellow-500');
                liveIndicator.classList.add('bg-green-500');
            }
            if (liveText) {
                liveText.classList.remove('text-red-400', 'text-yellow-400');
                liveText.classList.add('text-green-400');
                liveText.textContent = 'LIVE';
            }

            // Update communication card to CONNECTED
            if (linkStatusElement) {
                linkStatusElement.textContent = 'CONNECTED';
                linkStatusElement.className = 'text-green-400';
            }
        } else {
            // Link is LOST or ACQUIRING - do not force CONNECTED status
            console.log(`⚠️ Not forcing CONNECTED - current state: ${commState}`);
        }
    }

    updateSatelliteConnectionStatus(status) {
        console.log('Satellite connection status:', status);
        
        // Update connection indicator in header
        const liveIndicator = document.querySelector('.bg-green-500');
        const liveText = document.querySelector('.text-green-400.text-sm');
        
        if (status.connection_status === 'CONNECTED') {
            // Show LIVE status
            if (liveIndicator) {
                liveIndicator.classList.remove('bg-red-500', 'bg-yellow-500');
                liveIndicator.classList.add('bg-green-500');
            }
            if (liveText) {
                liveText.classList.remove('text-red-400', 'text-yellow-400');
                liveText.classList.add('text-green-400');
                liveText.textContent = 'LIVE';
            }
            
            // Enable all telemetry displays
            this.enableTelemetryDisplays(true);
            
            // Resume antenna tracking
            this.setAntennaTrackingState(true);
            
            // Add success alert
            this.addAlert('Satellite connection established - Telemetry active', 'success');
            
        } else if (status.connection_status === 'NO_DATA') {
            // Show NO DATA status
            if (liveIndicator) {
                liveIndicator.classList.remove('bg-green-500', 'bg-red-500');
                liveIndicator.classList.add('bg-yellow-500');
            }
            if (liveText) {
                liveText.classList.remove('text-green-400', 'text-red-400');
                liveText.classList.add('text-yellow-400');
                liveText.textContent = 'NO DATA';
            }
            
            // Keep telemetry displays enabled but show warning
            this.addAlert('Connection active but no telemetry data received', 'warning');
            
        } else {
            // Show DISCONNECTED status
            if (liveIndicator) {
                liveIndicator.classList.remove('bg-green-500', 'bg-yellow-500');
                liveIndicator.classList.add('bg-red-500');
            }
            if (liveText) {
                liveText.classList.remove('text-green-400', 'text-yellow-400');
                liveText.classList.add('text-red-400');
                liveText.textContent = 'DISCONNECTED';
            }
            
            // Disable all telemetry displays and clear values
            this.enableTelemetryDisplays(false);
            this.clearAllTelemetryValues();
            
            // Stop antenna tracking
            this.setAntennaTrackingState(false);
            
            // Add warning alert
            this.addAlert('Satellite connection lost - Telemetry disabled', 'warning');
        }
        
        // Update connection statistics
        this.updateConnectionStats(status);
    }

    enableTelemetryDisplays(enable) {
        // Find all telemetry display elements
        const telemetryElements = [
            'apid', 'sequence', 'mission-time', 'seq-count', 'uptime',
            'temp', 'humidity', 'adcs-mode', 'roll', 'pitch', 'yaw',
            'orbit', 'altitude', 'speed', 'sat-count', 'azimuth', 
            'elevation', 'pointing-offset', 'track-status', 'direction-text'
        ];
        
        telemetryElements.forEach(id => {
            const element = document.getElementById(id);
            if (element) {
                if (enable) {
                    element.style.opacity = '1';
                    element.style.filter = 'none';
                } else {
                    element.style.opacity = '0.3';
                    element.style.filter = 'grayscale(100%)';
                }
            }
        });
        
        // Handle charts
        const chartContainers = document.querySelectorAll('.chart-container');
        chartContainers.forEach(container => {
            if (enable) {
                container.style.opacity = '1';
            } else {
                container.style.opacity = '0.3';
            }
        });
    }

    clearAllTelemetryValues() {
        // Clear all telemetry values
        const telemetryValues = {
            'apid': '--',
            'sequence': '--',
            'mission-time': '--:--:--',
            'seq-count': '--',
            'uptime': '--:--:--',
            'temp': '--',
            'humidity': '--',
            'adcs-mode': '--',
            'roll': '--°',
            'pitch': '--°',
            'yaw': '--°',
            'orbit': '--',
            'altitude': '--',
            'speed': '--',
            'sat-count': '--',
            'azimuth': '--°',
            'elevation': '--°',
            'pointing-offset': '--°',
            'track-status': 'DISCONNECTED',
            'direction-text': '--'
        };
        
        Object.entries(telemetryValues).forEach(([id, value]) => {
            const element = document.getElementById(id);
            if (element) {
                element.textContent = value;
            }
        });
        
        // Clear charts
        if (this.charts) {
            Object.values(this.charts).forEach(chart => {
                if (chart && chart.data) {
                    chart.data.labels = [];
                    chart.data.datasets.forEach(dataset => {
                        dataset.data = [];
                    });
                    chart.update();
                }
            });
        }
    }

    updateConnectionStats(status) {
        // Update connection statistics display
        const linkStatusElement = document.getElementById('link-status');
        const lastUpdateElement = document.getElementById('last-update');
        const connectionsElement = document.getElementById('connections');
        const disconnectionsElement = document.getElementById('disconnections');
        
        // Update link status based on connection_status
        if (linkStatusElement) {
            linkStatusElement.textContent = status.connection_status || 'DISCONNECTED';
            linkStatusElement.className = status.connection_status === 'CONNECTED' ? 'text-green-400' : 
                                       status.connection_status === 'NO_DATA' ? 'text-yellow-400' : 'text-red-400';
        }
        
        // Update last update time
        if (lastUpdateElement) {
            const now = new Date();
            lastUpdateElement.textContent = now.toLocaleTimeString();
        }
        
        // Update connection counts
        if (connectionsElement) {
            connectionsElement.textContent = status.connect_count || 0;
        }
        
        if (disconnectionsElement) {
            disconnectionsElement.textContent = status.disconnect_count || 0;
        }
    }

    updateMissionTime(time) {
        const hours = Math.floor(time / 3600);
        const minutes = Math.floor((time % 3600) / 60);
        const seconds = time % 60;
        const timeStr = `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
        const missionTimeElement = document.getElementById('mission-time');
        if (missionTimeElement) {
            missionTimeElement.textContent = timeStr;
        }
    }

    updateSequenceCount(seq) {
        const seqElement = document.getElementById('seq-count');
        const sequenceElement = document.getElementById('sequence');
        if (seqElement) seqElement.textContent = seq;
        if (sequenceElement) sequenceElement.textContent = seq;
    }
    
    updateAPID(apid) {
        const apidElement = document.getElementById('apid');
        if (apidElement) {
            apidElement.textContent = apid;
        }
    }
    
    updateUptime(missionTime) {
        // Convert mission time to uptime display
        const hours = Math.floor(missionTime / 3600);
        const minutes = Math.floor((missionTime % 3600) / 60);
        const seconds = missionTime % 60;
        const uptimeStr = `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
        const uptimeElement = document.getElementById('uptime');
        if (uptimeElement) {
            uptimeElement.textContent = uptimeStr;
        }
    }

    updateADCSMode(mode) {
        const adcsModeElement = document.getElementById('adcs-mode');
        if (adcsModeElement) {
            adcsModeElement.textContent = mode;
        }
    }

    updateTemperature(temp) {
        const tempElement = document.getElementById('temp');
        if (tempElement) {
            tempElement.textContent = temp.toFixed(1) + '°C';
        }
    }

    updateHumidity(humidity) {
        const humElement = document.getElementById('humidity');
        if (humElement) {
            humElement.textContent = humidity.toFixed(1) + '%';
        }
    }

    updateRadiation(radiation) {
        const radElement = document.getElementById('radiation');
        const radBarElement = document.getElementById('radiation-bar');
        if (radElement) {
            radElement.textContent = radiation.toFixed(3) + ' mSv/h';
        }
        if (radBarElement) {
            const percentage = Math.min((radiation / 10) * 100, 100); // Scale to 0-100%
            radBarElement.style.width = percentage + '%';
        }
    }

    updatePosition(position) {
        const latElement = document.getElementById('latitude');
        const lonElement = document.getElementById('longitude');
        const altElement = document.getElementById('altitude');
        const speedElement = document.getElementById('speed');

        if (latElement) latElement.textContent = (position.latitude || 0).toFixed(4) + '°';
        if (lonElement) lonElement.textContent = (position.longitude || 0).toFixed(4) + '°';

        // Unit conversion for altitude: internal storage is meters, display in kilometers
        // LEO altitude range: 400-420 km
        // Conversion: meters / 1000 = kilometers
        const altitudeKm = (position.altitude || 0) / 1000.0;
        if (altElement) altElement.textContent = altitudeKm.toFixed(1) + ' km';

        // Unit conversion for speed: internal storage is km/h, display in km/s
        // LEO orbital speed: ~7.7 km/s
        // Conversion: km/h / 3600 = km/s
        const speedKmPerSec = (position.speed || 0) / 3600.0;
        if (speedElement) speedElement.textContent = speedKmPerSec.toFixed(2) + ' km/s';
    }

    updateIMUData(imu) {
        const accXElement = document.getElementById('acc-x');
        const accYElement = document.getElementById('acc-y');
        const accZElement = document.getElementById('acc-z');
        const gyroXElement = document.getElementById('gyro-x');
        const gyroYElement = document.getElementById('gyro-y');
        const gyroZElement = document.getElementById('gyro-z');
        
        if (accXElement) accXElement.textContent = imu.ax.toFixed(3);
        if (accYElement) accYElement.textContent = imu.ay.toFixed(3);
        if (accZElement) accZElement.textContent = imu.az.toFixed(3);
        if (gyroXElement) gyroXElement.textContent = imu.gx.toFixed(1);
        if (gyroYElement) gyroYElement.textContent = imu.gy.toFixed(1);
        if (gyroZElement) gyroZElement.textContent = imu.gz.toFixed(1);
    }

    updateAttitude(attitude) {
        const rollElement = document.getElementById('roll');
        const pitchElement = document.getElementById('pitch');
        const yawElement = document.getElementById('yaw');

        if (rollElement) rollElement.textContent = attitude.roll.toFixed(1) + '°';
        if (pitchElement) pitchElement.textContent = attitude.pitch.toFixed(1) + '°';
        if (yawElement) yawElement.textContent = attitude.yaw.toFixed(1) + '°';
    }

    updateCurrentAttitudeDisplay(attitude) {
        const currentRollElement = document.getElementById('current-roll');
        const currentPitchElement = document.getElementById('current-pitch');
        const currentYawElement = document.getElementById('current-yaw');

        if (currentRollElement) currentRollElement.textContent = attitude.roll.toFixed(1) + '°';
        if (currentPitchElement) currentPitchElement.textContent = attitude.pitch.toFixed(1) + '°';
        if (currentYawElement) currentYawElement.textContent = attitude.yaw.toFixed(1) + '°';
    }

    updateTargetDisplay(targetRoll, targetPitch, targetYaw) {
        const targetRollElement = document.getElementById('target-roll-display');
        const targetPitchElement = document.getElementById('target-pitch-display');
        const targetYawElement = document.getElementById('target-yaw-display');

        if (targetRoll !== null && targetRollElement) {
            targetRollElement.textContent = targetRoll.toFixed(1) + '°';
        } else if (targetRollElement) {
            targetRollElement.textContent = '--';
        }

        if (targetPitch !== null && targetPitchElement) {
            targetPitchElement.textContent = targetPitch.toFixed(1) + '°';
        } else if (targetPitchElement) {
            targetPitchElement.textContent = '--';
        }

        if (targetYaw !== null && targetYawElement) {
            targetYawElement.textContent = targetYaw.toFixed(1) + '°';
        } else if (targetYawElement) {
            targetYawElement.textContent = '--';
        }
    }

    updateCommState(state) {
        const commStateDisplay = document.getElementById('comm-state-display');
        if (commStateDisplay) {
            commStateDisplay.textContent = state;
            // Update color based on state
            if (state === 'LOCKED') {
                commStateDisplay.className = "text-center text-xs text-green-400 font-mono mt-1";
            } else if (state === 'TRACKING') {
                commStateDisplay.className = "text-center text-xs text-cyan-400 font-mono mt-1";
            } else if (state === 'ACQUIRING') {
                commStateDisplay.className = "text-center text-xs text-yellow-400 font-mono mt-1";
            } else {
                commStateDisplay.className = "text-center text-xs text-red-400 font-mono mt-1";
            }
        }
    }

    updateGPSStatus(fix, satCount, hdop) {
        const satCountElement = document.getElementById('sat-count');
        const hdopElement = document.getElementById('hdop');
        
        if (satCountElement) satCountElement.textContent = satCount;
        if (hdopElement) hdopElement.textContent = hdop.toFixed(1);
    }

    updateOrbitMode(orbit) {
        const orbitElement = document.getElementById('orbit');
        if (orbitElement) {
            orbitElement.textContent = orbit;
        }
    }

    updateAntennaTracking(antenna) {
        const azimuthElement = document.getElementById('azimuth');
        const elevationElement = document.getElementById('elevation');
        const signalStrengthElement = document.getElementById('signal-strength');
        const trackStatusElement = document.getElementById('track-status');
        const pointingOffsetElement = document.getElementById('pointing-offset');
        
        // Update shared antenna state - single source of truth
        this.sharedAntennaState.azimuth = antenna.azimuth || 0;
        this.sharedAntennaState.elevation = antenna.elevation || 0;
        this.sharedAntennaState.isTracking = antenna.tracking_status !== 'STOPPED';
        this.sharedAntennaState.lastUpdateTime = new Date();
        
        // UNIFIED STATE FOR ALL COMPONENTS
        this.antennaState.azimuth = antenna.azimuth || 0;
        this.antennaState.elevation = antenna.elevation || 0;
        
        if (azimuthElement) azimuthElement.textContent = this.sharedAntennaState.azimuth.toFixed(1) + '°';
        if (elevationElement) elevationElement.textContent = this.sharedAntennaState.elevation.toFixed(1) + '°';
        if (signalStrengthElement) signalStrengthElement.textContent = antenna.signal_strength + '%';
        if (trackStatusElement) trackStatusElement.textContent = antenna.tracking_status;
        if (pointingOffsetElement) pointingOffsetElement.textContent = (antenna.pointing_offset || 0).toFixed(1) + '°';
        
        // Update both widgets with same unified state
        this.drawStaticAntennaTracking();
        this.drawStaticCompass();
        this.updateDirectionText(this.antennaState.azimuth);
    }
    
    updateDirectionText(angle) {
        // Normalize angle to 0-360 range
        angle = (angle + 360) % 360;
        
        let dir = '';
        
        if (angle >= 337.5 || angle < 22.5) dir = 'N';
        else if (angle < 67.5) dir = 'NE';
        else if (angle < 112.5) dir = 'E';
        else if (angle < 157.5) dir = 'SE';
        else if (angle < 202.5) dir = 'S';
        else if (angle < 247.5) dir = 'SW';
        else if (angle < 292.5) dir = 'W';
        else dir = 'NW';
        
        const directionElement = document.getElementById('direction-text');
        if (directionElement) directionElement.textContent = dir;
    }

    startAntennaAnimation(azimuth, elevation) {
        // UNIFIED COORDINATE SYSTEM - SAME FOR ALL COMPONENTS
        // Compass: 0°=North, 90°=East, 180°=South, 270°=West
        // Canvas: 0°=East, 90°=South, 180°=West, 270°=North
        // Convert compass azimuth to canvas angle
        const canvasAngle = (90 - azimuth) * Math.PI / 180;
        this.antennaAnimation.targetBeamAngle = canvasAngle;
        
        // Initialize animation if not started
        if (!this.antennaAnimation.animationId) {
            this.initializeAntennaCanvas();
            this.animateAntennaTracking();
        }
    }
    
    initializeAntennaCanvas() {
        const canvas = document.getElementById('antennaCanvas');
        if (!canvas) return;
        
        this.antennaAnimation.centerX = canvas.width / 2;
        this.antennaAnimation.centerY = canvas.height / 2;
        this.antennaAnimation.radius = Math.min(this.antennaAnimation.centerX, this.antennaAnimation.centerY) - 20;
    }
    
    animateAntennaTracking() {
        // NO TIME-BASED MOVEMENT - STATIC OFFICE SETUP
        this.drawStaticAntennaTracking();
    }
    
    drawStaticAntennaTracking() {
        const canvas = document.getElementById('antennaCanvas');
        if (!canvas) return;
        
        const ctx = canvas.getContext('2d');
        const { centerX, centerY, radius } = this.antennaAnimation;
        
        // Clear canvas
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        
        // Draw radar background with gradient
        const gradient = ctx.createRadialGradient(centerX, centerY, 0, centerX, centerY, radius);
        gradient.addColorStop(0, 'rgba(0, 20, 40, 0.8)');
        gradient.addColorStop(1, 'rgba(0, 0, 0, 0.9)');
        ctx.fillStyle = gradient;
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        
        // Draw radar circles with glow
        ctx.strokeStyle = 'rgba(0, 255, 255, 0.3)';
        ctx.lineWidth = 1;
        ctx.shadowBlur = 10;
        ctx.shadowColor = 'rgba(0, 255, 255, 0.5)';
        
        for (let i = 1; i <= 3; i++) {
            ctx.beginPath();
            ctx.arc(centerX, centerY, (radius / 3) * i, 0, 2 * Math.PI);
            ctx.stroke();
        }
        
        // Draw grid lines
        ctx.strokeStyle = 'rgba(0, 255, 255, 0.2)';
        ctx.lineWidth = 0.5;
        
        // Cross lines
        ctx.beginPath();
        ctx.moveTo(centerX - radius, centerY);
        ctx.lineTo(centerX + radius, centerY);
        ctx.moveTo(centerX, centerY - radius);
        ctx.lineTo(centerX, centerY + radius);
        ctx.stroke();
        
        // Diagonal lines
        ctx.beginPath();
        ctx.moveTo(centerX - radius * 0.7, centerY - radius * 0.7);
        ctx.lineTo(centerX + radius * 0.7, centerY + radius * 0.7);
        ctx.moveTo(centerX - radius * 0.7, centerY + radius * 0.7);
        ctx.lineTo(centerX + radius * 0.7, centerY - radius * 0.7);
        ctx.stroke();
        
        // Reset shadow
        ctx.shadowBlur = 0;
        
        // SINGLE SOURCE OF TRUTH - STATIC ANTENNA TRACKING
        const azimuth = this.sharedAntennaState.azimuth;
        
        // Calculate position using unified azimuth
        const angleRad = (azimuth - 90) * Math.PI / 180;
        
        // Satellite position (fixed, not moving)
        const satX = centerX + radius * 0.8 * Math.cos(angleRad);
        const satY = centerY + radius * 0.8 * Math.sin(angleRad);
        
        // Draw satellite with glow
        ctx.shadowBlur = 15;
        ctx.shadowColor = 'rgba(255, 100, 0, 0.8)';
        ctx.beginPath();
        ctx.arc(satX, satY, 6, 0, 2 * Math.PI);
        ctx.fillStyle = '#ff6600';
        ctx.fill();
        
        // Satellite core
        ctx.shadowBlur = 0;
        ctx.beginPath();
        ctx.arc(satX, satY, 3, 0, 2 * Math.PI);
        ctx.fillStyle = '#ffaa00';
        ctx.fill();
        
        // Draw static radar beam (aligned with satellite)
        const beamLength = radius * 0.9;
        const beamEndX = centerX + beamLength * Math.cos(angleRad);
        const beamEndY = centerY + beamLength * Math.sin(angleRad);
        
        // Beam glow
        ctx.shadowBlur = 20;
        ctx.shadowColor = 'rgba(0, 255, 100, 0.8)';
        ctx.strokeStyle = 'rgba(0, 255, 100, 0.3)';
        ctx.lineWidth = 8;
        ctx.beginPath();
        ctx.moveTo(centerX, centerY);
        ctx.lineTo(beamEndX, beamEndY);
        ctx.stroke();
        
        // Main beam
        ctx.shadowBlur = 10;
        ctx.shadowColor = 'rgba(0, 255, 100, 0.6)';
        ctx.strokeStyle = '#00ff64';
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.moveTo(centerX, centerY);
        ctx.lineTo(beamEndX, beamEndY);
        ctx.stroke();
        
        // Reset shadow
        ctx.shadowBlur = 0;
        
        // Draw tracking line to satellite
        ctx.strokeStyle = 'rgba(255, 255, 0, 0.4)';
        ctx.lineWidth = 1;
        ctx.setLineDash([5, 5]);
        ctx.beginPath();
        ctx.moveTo(centerX, centerY);
        ctx.lineTo(satX, satY);
        ctx.stroke();
        ctx.setLineDash([]);
    }

    startCompassAnimation(azimuth) {
        // UNIFIED COORDINATE SYSTEM - SAME FOR ALL COMPONENTS
        this.compassAnimation.targetAngle = azimuth;
        
        // Initialize animation if not started
        if (!this.compassAnimation.animationId) {
            this.animateCompass();
        }
    }
    
    animateCompass() {
        // STATIC COMPASS - NO ANIMATION
        this.drawStaticCompass();
    }
    
    drawStaticCompass() {
        const canvas = document.getElementById('directionCanvas');
        if (!canvas) return;
        
        const ctx = canvas.getContext('2d');
        const centerX = canvas.width / 2;
        const centerY = canvas.height / 2;
        const radius = Math.min(centerX, centerY) - 10;
        
        // Clear canvas
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        
        // STEP 1: BACKGROUND (GLASS EFFECT)
        const grad = ctx.createRadialGradient(centerX, centerY, 10, centerX, centerY, radius);
        grad.addColorStop(0, "#0a0f1a");
        grad.addColorStop(1, "#02060d");
        
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(centerX, centerY, radius, 0, Math.PI * 2);
        ctx.fill();
        
        // STEP 2: OUTER GLOW RING
        ctx.beginPath();
        ctx.arc(centerX, centerY, radius, 0, Math.PI * 2);
        ctx.strokeStyle = "#00eaff";
        ctx.lineWidth = 2;
        ctx.shadowColor = "#00eaff";
        ctx.shadowBlur = 12;
        ctx.stroke();
        
        // STEP 3: TICK MARKS (PRO LOOK)
        for (let i = 0; i < 360; i += 30) {
            const rad = (i - 90) * Math.PI / 180;
            
            const x1 = centerX + (radius - 10) * Math.cos(rad);
            const y1 = centerY + (radius - 10) * Math.sin(rad);
            
            const x2 = centerX + radius * Math.cos(rad);
            const y2 = centerY + radius * Math.sin(rad);
            
            ctx.beginPath();
            ctx.moveTo(x1, y1);
            ctx.lineTo(x2, y2);
            ctx.strokeStyle = "rgba(0,255,200,0.4)";
            ctx.lineWidth = 1;
            ctx.stroke();
        }
        
        // STEP 4: CARDINAL DIRECTIONS (STYLISH)
        ctx.fillStyle = "#00eaff";
        ctx.font = "bold 14px Orbitron, monospace";
        ctx.textAlign = "center";
        
        ctx.fillText("N", centerX, centerY - radius + 20);
        ctx.fillText("E", centerX + radius - 20, centerY);
        ctx.fillText("S", centerX, centerY + radius - 10);
        ctx.fillText("W", centerX - radius + 20, centerY);
        
        // STEP 5: SINGLE GLOWING NEEDLE
        const azimuth = this.sharedAntennaState.azimuth;
        const angleRad = (azimuth - 90) * Math.PI / 180;
        
        ctx.beginPath();
        ctx.moveTo(centerX, centerY);
        
        ctx.lineTo(
            centerX + (radius - 20) * Math.cos(angleRad),
            centerY + (radius - 20) * Math.sin(angleRad)
        );
        
        ctx.strokeStyle = "#00ffcc";
        ctx.lineWidth = 3;
        ctx.shadowColor = "#00ffcc";
        ctx.shadowBlur = 15;
        ctx.stroke();
        
        // STEP 6: CENTER HUB
        ctx.beginPath();
        ctx.arc(centerX, centerY, 5, 0, Math.PI * 2);
        ctx.fillStyle = "#00ffcc";
        ctx.shadowBlur = 10;
        ctx.fill();
    }
    
    updateDirectionText(angle) {
        // SINGLE DIRECTION FUNCTION - REMOVE DUPLICATES
        angle = (angle + 360) % 360;
        
        let dir = '';
        
        if (angle >= 337.5 || angle < 22.5) dir = 'N';
        else if (angle < 67.5) dir = 'NE';
        else if (angle < 112.5) dir = 'E';
        else if (angle < 157.5) dir = 'SE';
        else if (angle < 202.5) dir = 'S';
        else if (angle < 247.5) dir = 'SW';
        else if (angle < 292.5) dir = 'W';
        else dir = 'NW';
        
        const directionElement = document.getElementById('direction-text');
        if (directionElement) directionElement.textContent = dir;
    }

    initializeCharts() {
        // Temperature chart
        const tempCtx = document.getElementById('tempChart');
        if (tempCtx) {
            this.charts.temperature = new Chart(tempCtx.getContext('2d'), {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'Temperature (°C)',
                        data: [],
                        borderColor: '#ff6b6b',
                        backgroundColor: 'rgba(255, 107, 107, 0.1)',
                        tension: 0.4
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: { beginAtZero: false }
                    }
                }
            });
        }

        // Radiation chart
        const radCtx = document.getElementById('radChart');
        if (radCtx) {
            this.charts.radiation = new Chart(radCtx.getContext('2d'), {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'Radiation (mSv/h)',
                        data: [],
                        borderColor: '#4ecdc4',
                        backgroundColor: 'rgba(78, 205, 196, 0.1)',
                        tension: 0.4
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: { beginAtZero: true }
                    }
                }
            });
        }
    }

    initializeAttitudeIndicator() {
        this.attitudeCanvas = document.getElementById('attitude-canvas');
        if (this.attitudeCanvas) {
            this.attitudeCtx = this.attitudeCanvas.getContext('2d');
        }
    }

    updateRealtimeCharts(data) {
        const timestamp = new Date().toLocaleTimeString();
        
        // Update temperature chart
        if (this.charts.temperature) {
            const tempChart = this.charts.temperature;
            tempChart.data.labels.push(timestamp);
            tempChart.data.datasets[0].data.push(data.temp || 0);
            
            // Keep only last 20 data points
            if (tempChart.data.labels.length > 20) {
                tempChart.data.labels.shift();
                tempChart.data.datasets[0].data.shift();
            }
            tempChart.update('none');
        }
        
        // Update radiation chart
        if (this.charts.radiation) {
            const radChart = this.charts.radiation;
            radChart.data.labels.push(timestamp);
            radChart.data.datasets[0].data.push(data.radiation || 0);
            
            // Keep only last 20 data points
            if (radChart.data.labels.length > 20) {
                radChart.data.labels.shift();
                radChart.data.datasets[0].data.shift();
            }
            radChart.update('none');
        }
    }

    updateConnectionStatus(status, type) {
        const statusElement = document.getElementById('connection-status');
        if (statusElement) {
            statusElement.textContent = status;
            statusElement.className = `badge bg-${type}`;
        }
    }

    addAlert(message, type) {
        const alertContainer = document.getElementById('alerts');
        if (!alertContainer) return;
        
        const alert = document.createElement('div');
        alert.className = `alert alert-${type}`;
        alert.innerHTML = `
            <i class="fas fa-${type === 'critical' ? 'exclamation-triangle' : 'info-circle'} mr-1"></i>
            ${message}
        `;
        alertContainer.appendChild(alert);
        
        // Auto-remove after 5 seconds
        setTimeout(() => {
            if (alert.parentNode) {
                alert.parentNode.removeChild(alert);
            }
        }, 5000);
    }

    startAnimations() {
        // Add any periodic animations here
        setInterval(() => {
            this.updateConnectionTime();
        }, 1000);
    }

    updateConnectionTime() {
        if (this.lastUpdateTime) {
            const now = new Date();
            const diff = Math.floor((now - this.lastUpdateTime) / 1000);
            const timeElement = document.getElementById('last-update');
            if (timeElement) {
                timeElement.textContent = `${diff}s ago`;
            }
        }
    }

    sendTelecommand(command, value = 0) {
        const telecommand = {
            type: 'telecommand',
            command: command,
            value: value,
            timestamp: new Date().toISOString()
        };
        
        this.socket.emit('send_command', telecommand);
        this.addAlert(`Command sent: ${command} = ${value}`, 'info');
    }
}

function initializeTelecommandPanel() {

    const sendBtn = document.getElementById('send-tc-btn');
    const connectBtn = document.getElementById('tc-connect');
    const disconnectBtn = document.getElementById('tc-disconnect');

    if (!sendBtn) {
        console.log("❌ Telecommand button not found");
        return;
    }

    console.log("✅ Telecommand button found, setting up event listener");

    sendBtn.addEventListener('click', async () => {

        console.log("📡 Send button clicked");

        const adcsMode =
            document.getElementById('tc-adcs').value;

        // Get optional ADCS attitude values
        const roll = parseFloat(document.getElementById('tc-roll').value) || null;
        const pitch = parseFloat(document.getElementById('tc-pitch').value) || null;
        const yaw = parseFloat(document.getElementById('tc-yaw').value) || null;

        // Get antenna mode and values
        const antennaMode = document.getElementById('tc-antenna-mode').value;
        const azimuth = parseFloat(document.getElementById('tc-azimuth').value) || null;
        const elevation = parseFloat(document.getElementById('tc-elevation').value) || null;

        const statusBox =
            document.getElementById('tc-status');

        const commandStatusDisplay =
            document.getElementById('command-status-display');

        console.log(`Sending telecommand: ADCS=${adcsMode}, Roll=${roll}, Pitch=${pitch}, Yaw=${yaw}, AntennaMode=${antennaMode}, Azimuth=${azimuth}, Elevation=${elevation}`);

        statusBox.innerHTML = "Sending...";
        commandStatusDisplay.innerHTML = "SENDING";
        commandStatusDisplay.className = "text-center text-xs text-yellow-400 font-mono mt-1";

       try {

    const response = await fetch('/send_telecommand', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            adcs_mode: adcsMode,
            roll: roll,
            pitch: pitch,
            yaw: yaw,
            antenna_mode: antennaMode,
            azimuth: azimuth,
            elevation: elevation
        })
    });

    const result = await response.json();

    console.log("Server response:", result);

    if (result.status === "success") {
        statusBox.innerHTML = "Command Sent";
        console.log("✅ Command sent successfully");
    } else {
        statusBox.innerHTML = "Failed";
        console.log("❌ Command failed");
    }

} catch (error) {

    console.error("❌ Error sending command:", error);

    statusBox.innerHTML = "Error";
}
    });

    // Listen for command status updates
    window.dashboard.socket.on('command_status', (status) => {
        console.log("📡 Command status update:", status);
        const commandStatusDisplay = document.getElementById('command-status-display');
        if (commandStatusDisplay) {
            commandStatusDisplay.innerHTML = status.status;
            // Update color based on status
            if (status.status === 'COMPLETED') {
                commandStatusDisplay.className = "text-center text-xs text-green-400 font-mono mt-1";
            } else if (status.status === 'EXECUTING') {
                commandStatusDisplay.className = "text-center text-xs text-blue-400 font-mono mt-1";
            } else if (status.status === 'ACK_RECEIVED') {
                commandStatusDisplay.className = "text-center text-xs text-cyan-400 font-mono mt-1";
            } else {
                commandStatusDisplay.className = "text-center text-xs text-yellow-400 font-mono mt-1";
            }
        }
    });

    // Listen for command log updates
    window.dashboard.socket.on('command_log', (log) => {
        console.log("📡 Command log update:", log);
        const commandLogDisplay = document.getElementById('command-log-display');
        if (commandLogDisplay) {
            commandLogDisplay.innerHTML = log.join('<br>');
            // Auto-scroll to bottom
            commandLogDisplay.scrollTop = commandLogDisplay.scrollHeight;
        }
    });

    // Listen for communication state updates (included in telemetry)
    // This will be handled in the updateTelemetry function

    // Setup CONNECT button (placeholder for future implementation)
    if (connectBtn) {
        connectBtn.addEventListener('click', () => {
            console.log("📡 CONNECT button clicked (placeholder)");
            // Future: Implement actual connect logic via Modbus
            window.dashboard.recoverLink();
        });
    }

    // Setup DISCONNECT button (placeholder for future implementation)
    if (disconnectBtn) {
        disconnectBtn.addEventListener('click', () => {
            console.log("📡 DISCONNECT button clicked (placeholder)");
            // Future: Implement actual disconnect logic via Modbus
            // For now, this is a placeholder
        });
    }
}

// Initialize dashboard when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    console.log('🚀 Dashboard initializing...');
    window.dashboard = new MissionControlDashboard();
    console.log('✅ Dashboard initialized successfully');

    initializeTelecommandPanel();
    
    // Add antenna alignment test function to window for manual testing
    window.testAntennaAlignment = function() {
        console.log('🧪 Testing antenna alignment...');
        const dashboard = window.dashboard;
        
        // Test different cardinal directions
        const testAngles = [0, 90, 180, 270]; // North, East, South, West
        
        let testIndex = 0;
        const runTest = () => {
            if (testIndex < testAngles.length) {
                const angle = testAngles[testIndex];
                console.log(`🧪 Testing angle: ${angle}° (${['North', 'East', 'South', 'West'][testIndex]})`);
                
                // Update shared antenna state
                dashboard.sharedAntennaState.azimuth = angle;
                dashboard.sharedAntennaState.elevation = 45;
                dashboard.sharedAntennaState.isTracking = true;
                dashboard.sharedAntennaState.lastUpdateTime = new Date();
                
                // Update both widgets
                dashboard.startAntennaAnimation(angle, 45);
                dashboard.startCompassAnimation(angle);
                
                // Update display
                const azimuthElement = document.getElementById('azimuth');
                if (azimuthElement) azimuthElement.textContent = angle.toFixed(1) + '°';
                
                testIndex++;
                setTimeout(runTest, 2000); // Test each direction for 2 seconds
            } else {
                console.log('🧪 Antenna alignment test complete');
            }
        };
        
        runTest();
    };
    
    // Auto-run test after 3 seconds for verification
    setTimeout(() => {
        console.log('🧪 Auto-running antenna alignment test...');
        window.testAntennaAlignment();
    }, 3000);
});
