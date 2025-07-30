# shrambandhu/utils/location.py
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
from sqlalchemy import func, and_ # Import 'and_' for combined filters
from shrambandhu.models import Job, User # Ensure models are imported
from flask import current_app

geolocator = Nominatim(user_agent="shrambandhu_app_v1") # Use a specific user agent

def get_coordinates(address):
    """Geocode an address string to (latitude, longitude)."""
    if not address:
        return None
    try:
        # Add country bias for better results if needed, e.g., country_codes='in'
        location = geolocator.geocode(address, timeout=10)
        if location:
            return (location.latitude, location.longitude)
    except Exception as e:
        # Log the error appropriately
        current_app.logger.error(f"Geocoding error for address '{address}': {e}")
    return None

def calculate_distance(loc1, loc2):
    """Calculate geodesic distance between two (lat, lon) tuples in kilometers."""
    if not loc1 or not loc2 or None in loc1 or None in loc2:
        return float('inf') # Return infinity if any location is invalid
    try:
        return geodesic(loc1, loc2).km
    except ValueError:
        return float('inf') # Handle potential errors in geopy

def get_nearby_jobs(worker_location, worker_skills=None, max_distance_km=25):
    """
    Find active jobs near a worker's location, optionally filtering by skills.

    Args:
        worker_location (tuple): Worker's (latitude, longitude).
        worker_skills (list): List of worker's skills (strings). Optional.
        max_distance_km (int): Maximum distance in kilometers.

    Returns:
        list: Sorted list of Job objects with an added 'distance' attribute.
    """
    if not worker_location or None in worker_location:
        return [] # Cannot find nearby jobs without worker location

    # --- Query Optimization ---
    # 1. Filter by status and ensure location exists in the database first
    base_query = Job.query.filter(
        Job.status == 'active',
        Job.location_lat.isnot(None),
        Job.location_lng.isnot(None)
    )

    # 2. Optional: Pre-filter by skills if provided (using simple LIKE matching for comma-separated strings)
    if worker_skills:
        # Create OR conditions for each skill
        skill_filters = []
        for skill in worker_skills:
            if skill: # Ensure skill is not empty
                 # Uses LIKE '%skill%', case-insensitive might depend on DB collation
                 # This isn't perfect but works for comma-separated text without complex setup
                 skill_filters.append(Job.skills_required.ilike(f"%{skill.strip()}%"))

        if skill_filters:
             base_query = base_query.filter(and_(*skill_filters)) # Combine skill filters with AND

    # Fetch potentially relevant jobs from DB
    potential_jobs = base_query.all()

    # --- Filter by Distance in Python ---
    nearby_jobs = []
    for job in potential_jobs:
        job_location = (job.location_lat, job.location_lng)
        distance = calculate_distance(worker_location, job_location)
        if distance <= max_distance_km:
            job.distance = distance # Add distance attribute to the object
            nearby_jobs.append(job)

    # Sort by distance
    return sorted(nearby_jobs, key=lambda x: x.distance)


# --- Keep get_nearest_responders and get_hospitals_near_location if still needed ---
# (Code for those functions remains the same as previous versions unless modification is required)

def get_nearest_responders(location, radius_km=5):
    # ... (previous implementation) ...
    if not location or None in location: return []
    responders = User.query.filter(User.role == 'admin', User.location_lat.isnot(None), User.location_lng.isnot(None)).all() # Example filter
    nearby_responders = []
    for responder in responders:
        responder_location = (responder.location_lat, responder.location_lng)
        distance = calculate_distance(location, responder_location)
        if distance <= radius_km:
            responder.distance = distance
            nearby_responders.append(responder)
    return sorted(nearby_responders, key=lambda x: x.distance)


def get_hospitals_near_location(location, radius_km=5):
    # ... (previous mock implementation) ...
     if not location or None in location: return []
     # In a real app, use Google Places API or similar here
     mock_hospitals = [
         {"name": "Apollo Hospital Jubilee Hills", "lat": 17.4182, "lng": 78.4099},
         {"name": "Care Hospitals Banjara Hills", "lat": 17.4152, "lng": 78.4496},
         {"name": "Yashoda Hospitals Somajiguda", "lat": 17.4227, "lng": 78.4571},
         {"name": "Osmania General Hospital", "lat": 17.3728, "lng": 78.4760} # Example public hospital
     ]
     nearby_hospitals = []
     for hospital in mock_hospitals:
         h_loc = (hospital['lat'], hospital['lng'])
         distance = calculate_distance(location, h_loc)
         if distance <= radius_km:
             hospital['distance'] = distance
             nearby_hospitals.append(hospital)
     return sorted(nearby_hospitals, key=lambda x: x.get('distance', float('inf')))