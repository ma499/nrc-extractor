import sqlite3
import sys
from datetime import datetime
import xml.etree.ElementTree as ET
from xml.dom import minidom
import math

def parse_time(timestamp_str):
    """Handles multiple possible timestamp formats from the database."""
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(timestamp_str, fmt)
        except ValueError:
            pass
    # Handle ISO 8601 format with 'T' separator and timezone info
    if 'T' in timestamp_str:
        return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
    raise ValueError(f"no valid date format found for {timestamp_str}")

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculates the distance between two GPS coordinates in meters."""
    R = 6371000  # Radius of Earth in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * \
        math.sin(delta_lambda / 2.0) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c

def calculate_and_print_summary(location_data, heart_rate_data, cadence_data, calories):
    """Calculates and prints a summary of the activity."""
    if not location_data:
        return

    # --- Time ---
    total_time_delta = location_data[-1]['time'] - location_data[0]['time']
    
    # --- Distance ---
    total_distance = 0
    for i in range(1, len(location_data)):
        point1 = location_data[i-1]
        point2 = location_data[i]
        total_distance += haversine_distance(point1['latitude'], point1['longitude'], point2['latitude'], point2['longitude'])
    
    # --- Elevation Gain ---
    elevation_gain = 0
    for i in range(1, len(location_data)):
        if location_data[i]['altitude'] > location_data[i-1]['altitude']:
            elevation_gain += location_data[i]['altitude'] - location_data[i-1]['altitude']

    # --- Averages ---
    avg_hr = sum(hr for _, hr in heart_rate_data) / len(heart_rate_data) if heart_rate_data else 0
    # Cadence in TCX is RPM, we display SPM (RPM * 2)
    avg_cadence_spm = (sum(cad for _, cad in cadence_data) / len(cadence_data)) * 2 if cadence_data else 0

    # --- Pace ---
    total_seconds = total_time_delta.total_seconds()
    km = total_distance / 1000.0
    secs_per_km = total_seconds / km if km > 0 else 0
    pace_min = int(secs_per_km // 60)
    pace_sec = int(secs_per_km % 60)

    # --- Print Summary ---
    print("-" * 30)
    print("Activity Summary")
    print("-" * 30)
    print(f"Total Time:      {str(total_time_delta)}")
    print(f"Distance:        {km:.2f} km")
    print(f"Calories:        {calories} kcal")
    print(f"Elevation Gain:  {elevation_gain:.1f} m")
    print("-" * 30)
    print(f"Average Pace:    {pace_min}:{pace_sec:02d} /km")
    print(f"Average HR:      {avg_hr:.0f} bpm")
    print(f"Average Cadence: {avg_cadence_spm:.0f} spm")
    print("-" * 30)


def find_nearest_metric(target_time, metric_list):
    """
    Finds the metric with the timestamp closest to the target time.
    Assumes metric_list is a list of tuples where the first element is a datetime object
    and the second is the value.
    """
    if not metric_list:
        return None
    
    closest_metric = min(
        metric_list,
        key=lambda metric: abs(metric[0] - target_time)
    )
    return closest_metric[1]

def fetch_data(cursor, activity_id):
    """Fetches and prepares all necessary data from the database."""
    
    # --- Fetch Location and Altitude Data ---
    cursor.execute("""
        SELECT
            m1.startDate,
            m1.coordinateValue,
            (SELECT m2.doubleValue FROM metrics m2 WHERE m2.activityID = ? AND m2.source = 'com.nike.running.ios.corelocation' AND m2.coordinateValue IS NULL AND m2.startDate = m1.startDate) AS altitude
        FROM metrics m1
        WHERE m1.activityID = ?
          AND m1.source = 'com.nike.running.ios.corelocation'
          AND m1.coordinateValue IS NOT NULL
        ORDER BY m1.startDate;
    """, (activity_id, activity_id))

    location_data = []
    for row in cursor.fetchall():
        time_str, coords_str, altitude = row
        if coords_str and ',' in coords_str:
            lat_str, lon_str = coords_str.split(',')
            location_data.append({
                "time": parse_time(time_str),
                "latitude": float(lat_str),
                "longitude": float(lon_str),
                "altitude": float(altitude) if altitude else 0.0
            })

    # --- Fetch Heart Rate Data ---
    cursor.execute("""
        SELECT startDate, intValue
        FROM metrics
        WHERE activityID = ?
          AND source = 'com.nike.running.ios.healthkit'
          AND intValue IS NOT NULL
        ORDER BY startDate;
    """, (activity_id,))
    heart_rate_data = [(parse_time(row[0]), row[1]) for row in cursor.fetchall()]

    # --- Fetch Cadence Data ---
    cursor.execute("""
        SELECT startDate, doubleValue
        FROM metrics
        WHERE activityID = ?
          AND source = 'com.nike.running.ios.coremotion'
          AND doubleValue > 100 -- Filter for cadence, not speed
          AND intValue IS NULL
        ORDER BY startDate;
    """, (activity_id,))
    # TCX expects cadence in RPM (revolutions per minute), which is half of SPM (steps per minute) for running.
    cadence_data = [(parse_time(row[0]), int(row[1] / 2)) for row in cursor.fetchall()]

    # --- Fetch Calories Data ---
    cursor.execute("""
        SELECT MAX(intValue)
        FROM metrics
        WHERE activityID = ?
          AND source = 'com.nike.running.ios.calculatedcalories';
    """, (activity_id,))
    calories_raw = cursor.fetchone()[0]
    # Convert from thousandths of a kcal to kcal
    calories = int(calories_raw / 1000) if calories_raw else 0

    return location_data, heart_rate_data, cadence_data, calories

def create_tcx_file(location_data, heart_rate_data, cadence_data, output_file):
    """Builds and saves the TCX file from the processed data."""
    
    if not location_data:
        print("Error: No location data found for this activity.")
        return

    # --- Create XML Structure ---
    # Register the namespace to avoid ns0: prefixes
    ET.register_namespace('', "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2")
    
    # Root element
    tc_db = ET.Element("TrainingCenterDatabase", {
        "xmlns": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2",
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xsi:schemaLocation": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2 http://www.garmin.com/xmlschemas/TrainingCenterDatabasev2.xsd"
    })

    activities = ET.SubElement(tc_db, "Activities")
    activity = ET.SubElement(activities, "Activity", {"Sport": "Running"})
    
    start_time_str = location_data[0]['time'].isoformat() + "Z"
    
    activity_id_el = ET.SubElement(activity, "Id")
    activity_id_el.text = start_time_str
    
    lap = ET.SubElement(activity, "Lap", {"StartTime": start_time_str})
    track = ET.SubElement(lap, "Track")

    # --- Populate Trackpoints ---
    for point in location_data:
        trackpoint = ET.SubElement(track, "Trackpoint")
        
        time_el = ET.SubElement(trackpoint, "Time")
        time_el.text = point['time'].isoformat() + "Z"
        
        position = ET.SubElement(trackpoint, "Position")
        lat = ET.SubElement(position, "LatitudeDegrees")
        lat.text = str(point['latitude'])
        lon = ET.SubElement(position, "LongitudeDegrees")
        lon.text = str(point['longitude'])
        
        alt = ET.SubElement(trackpoint, "AltitudeMeters")
        alt.text = str(point['altitude'])

        # Find nearest heart rate and add it
        nearest_hr = find_nearest_metric(point['time'], heart_rate_data)
        if nearest_hr is not None:
            hr_bpm = ET.SubElement(trackpoint, "HeartRateBpm")
            hr_val = ET.SubElement(hr_bpm, "Value")
            hr_val.text = str(nearest_hr)
            
        # Find nearest cadence and add it
        nearest_cadence = find_nearest_metric(point['time'], cadence_data)
        if nearest_cadence is not None:
            cadence_el = ET.SubElement(trackpoint, "Cadence")
            cadence_el.text = str(nearest_cadence)

    # --- Write to File ---
    # Use minidom for pretty printing (indentation)
    xml_str = ET.tostring(tc_db, 'utf-8')
    pretty_xml_str = minidom.parseString(xml_str).toprettyxml(indent="  ")
    
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(pretty_xml_str)
    print(f"Successfully created TCX file: {output_file}")


def main():
    if len(sys.argv) != 4:
        print("Usage: python generate_tcx.py <database_file_path> <activity_id> <output_tcx_file>")
        sys.exit(1)

    db_path = sys.argv[1]
    activity_id = sys.argv[2]
    output_path = sys.argv[3]

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        location_data, heart_rate_data, cadence_data, calories = fetch_data(cursor, activity_id)
        
        conn.close()

        calculate_and_print_summary(location_data, heart_rate_data, cadence_data, calories)
        
        create_tcx_file(location_data, heart_rate_data, cadence_data, output_path)

    except sqlite3.Error as e:
        print(f"Database error: {e}")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()

