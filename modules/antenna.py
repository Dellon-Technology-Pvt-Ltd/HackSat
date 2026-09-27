import math

class AntennaTracker:
    def __init__(self):
        # Ground station coordinates (Pune)
        self.gs_lat = 18.5204
        self.gs_lon = 73.8567
        self.gs_alt = 560  # meters above sea level
        self.is_active = True  # Control antenna tracking based on telemetry state
        
    def calculate_az_el(self, sat_lat, sat_lon, sat_alt):
        """Calculate azimuth and elevation from ground station to satellite"""
        
        # Convert degrees to radians
        gs_lat_rad = math.radians(self.gs_lat)
        gs_lon_rad = math.radians(self.gs_lon)
        sat_lat_rad = math.radians(sat_lat)
        sat_lon_rad = math.radians(sat_lon)
        
        # Earth radius in meters
        earth_radius = 6371000
        
        # Convert to Cartesian coordinates
        gs_x = earth_radius * math.cos(gs_lat_rad) * math.cos(gs_lon_rad)
        gs_y = earth_radius * math.cos(gs_lat_rad) * math.sin(gs_lon_rad)
        gs_z = earth_radius * math.sin(gs_lat_rad)
        
        sat_r = earth_radius + sat_alt
        sat_x = sat_r * math.cos(sat_lat_rad) * math.cos(sat_lon_rad)
        sat_y = sat_r * math.cos(sat_lat_rad) * math.sin(sat_lon_rad)
        sat_z = sat_r * math.sin(sat_lat_rad)
        
        # Vector from ground station to satellite
        dx = sat_x - gs_x
        dy = sat_y - gs_y
        dz = sat_z - gs_z
        
        # Calculate local coordinate system
        # East direction
        east_x = -math.sin(gs_lon_rad)
        east_y = math.cos(gs_lon_rad)
        east_z = 0
        
        # North direction
        north_x = -math.sin(gs_lat_rad) * math.cos(gs_lon_rad)
        north_y = -math.sin(gs_lat_rad) * math.sin(gs_lon_rad)
        north_z = math.cos(gs_lat_rad)
        
        # Up direction
        up_x = math.cos(gs_lat_rad) * math.cos(gs_lon_rad)
        up_y = math.cos(gs_lat_rad) * math.sin(gs_lon_rad)
        up_z = math.sin(gs_lat_rad)
        
        # Project satellite vector onto local coordinate system
        east_component = dx * east_x + dy * east_y + dz * east_z
        north_component = dx * north_x + dy * north_y + dz * north_z
        up_component = dx * up_x + dy * up_y + dz * up_z
        
        # Calculate azimuth (0-360 degrees, 0 = North, 90 = East)
        azimuth = math.degrees(math.atan2(east_component, north_component))
        if azimuth < 0:
            azimuth += 360
            
        # Calculate elevation (0-90 degrees)
        horizontal_distance = math.sqrt(east_component**2 + north_component**2)
        elevation = math.degrees(math.atan2(up_component, horizontal_distance))
        
        # Ensure elevation is within bounds
        elevation = max(0, min(90, elevation))
        
        return round(azimuth, 2), round(elevation, 2)
        
    def calculate_signal_strength(self, elevation):
        """Calculate realistic signal strength based on elevation angle"""
        if elevation <= 0:
            return 0
        elif elevation >= 90:
            return 100
        else:
            # More realistic signal strength model
            # Signal strength increases with elevation, with better curve
            return round(max(0, min(100, (elevation / 90) * 100)), 1)
            
    def get_tracking_status(self, elevation):
        """Get tracking status based on elevation"""
        if elevation > 30:
            return "LOCKED"
        elif elevation >= 10:
            return "SEARCHING"
        else:
            return "LOST"
            
    def calculate_pointing_offset(self, azimuth, elevation):
        """Calculate pointing offset from ideal position"""
        # Ideal pointing angles (for demonstration)
        ideal_azimuth = 250.0
        ideal_elevation = 90.0
        
        # Calculate offset
        az_offset = abs(azimuth - ideal_azimuth)
        el_offset = abs(elevation - ideal_elevation)
        
        # Combined offset (RMS)
        pointing_offset = math.sqrt(az_offset**2 + el_offset**2)
        
        return round(pointing_offset, 1)
            
    def set_active(self, is_active):
        """Control antenna tracker active state"""
        self.is_active = is_active
        print(f"📡 Antenna tracker {'activated' if is_active else 'deactivated'}")
    
    def get_antenna_data(self, telemetry):
        """Get complete antenna tracking data"""
        try:
            # Only calculate tracking if antenna is active
            if not self.is_active:
                return {
                    "azimuth": 0,
                    "elevation": 0,
                    "signal_strength": 0,
                    "tracking_status": "STOPPED",
                    "pointing_offset": 0,
                    "gs_lat": self.gs_lat,
                    "gs_lon": self.gs_lon,
                    "sat_lat": telemetry['lat'],
                    "sat_lon": telemetry['lon']
                }
            
            # Calculate azimuth and elevation
            azimuth, elevation = self.calculate_az_el(
                telemetry['lat'], 
                telemetry['lon'], 
                telemetry['alt']
            )
            
            # Calculate signal strength
            signal_strength = self.calculate_signal_strength(elevation)
            
            # Get tracking status
            status = self.get_tracking_status(elevation)
            
            return {
                "azimuth": azimuth,
                "elevation": elevation,
                "signal_strength": signal_strength,
                "tracking_status": status,
                "pointing_offset": self.calculate_pointing_offset(azimuth, elevation),
                "gs_lat": self.gs_lat,
                "gs_lon": self.gs_lon,
                "sat_lat": telemetry['lat'],
                "sat_lon": telemetry['lon']
            }
        except Exception as e:
            print(f"❌ Antenna calculation error: {e}")
            return {
                "azimuth": 0,
                "elevation": 0,
                "signal_strength": 0,
                "tracking_status": "ERROR",
                "pointing_offset": 0,
                "gs_lat": self.gs_lat,
                "gs_lon": self.gs_lon,
                "sat_lat": 0,
                "sat_lon": 0
            }
