# ===============================
# 🚆 Train Route Optimizer (Final Version)
# Accurate distances + looping train
# Author: Aaron Sood
# ===============================

import json, csv, math, os
import numpy as np
import rasterio
from shapely.geometry import LineString
from heapq import heappush, heappop
from scipy.ndimage import binary_dilation
import folium

# -----------------------------
# 📁 Hard-coded folder paths
# -----------------------------
GEOJSON_DIR = r"C:\ScienceFair\python\geojsons"
RASTER_DIR = r"C:\ScienceFair\python\rasters"
OUTPUT_DIR = r"C:\ScienceFair\python\outputs"
STATIC_DIR = r"C:\ScienceFair\python\static"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# -----------------------------
# 🌐 Haversine distance
# -----------------------------
def haversine(p1, p2):
    # p1 and p2 are (lon, lat)
    R = 6371  # km
    lon1, lat1 = math.radians(p1[0]), math.radians(p1[1])
    lon2, lat2 = math.radians(p2[0]), math.radians(p2[1])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    c = 2*math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c


# -----------------------------
# ⚖️ Segment cost
# -----------------------------
def compute_segment_cost(length_km, terrain_penalty=0.0, ridership_score=0.0,
                         terrain_weight=1.0, ridership_weight=5, corner_penalty=0.0):
    return length_km + terrain_penalty*terrain_weight - ridership_score*ridership_weight + corner_penalty

# -----------------------------
# 🌊 Load rasters efficiently
# -----------------------------
def load_rasters(water_mask_path, elevation_path):
    ds_w = rasterio.open(water_mask_path,'r')
    water_mask = ds_w.read(1, out_shape=(1024,1024))>0
    ds_e = rasterio.open(elevation_path,'r')
    elevation = ds_e.read(1, out_shape=(1024,1024)).astype(float)
    if ds_e.nodata is not None:
        elevation[np.isclose(elevation, ds_e.nodata)] = np.nan
    return water_mask, elevation, ds_w, ds_e

# -----------------------------
# 📍 Parse GeoJSON stations
# -----------------------------
def parse_geojson(filepath):
    with open(filepath, encoding='utf-8') as f:
        data = json.load(f)
    stations = []
    for feature in data.get('features', []):
        if feature.get('geometry', {}).get('type') != "Point": continue
        coords = feature['geometry']['coordinates']
        stations.append(((float(coords[0]), float(coords[1])),
                         feature.get('properties',{}).get('name','Unnamed')))
    return stations

# -----------------------------
# 🟩 Create grid automatically
# -----------------------------
def create_grid(stations, ds_water, resolution=0.0005, water_buffer_cells=1):
    lons_list = [s[0][0] for s in stations]
    lats_list = [s[0][1] for s in stations]
    min_lon, max_lon = min(lons_list), max(lons_list)
    min_lat, max_lat = min(lats_list), max(lats_list)

    lons = np.arange(min_lon, max_lon+resolution*0.5, resolution)
    lats = np.arange(min_lat, max_lat+resolution*0.5, resolution)
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    points = np.column_stack([lon_grid.ravel(), lat_grid.ravel()])
    water_samples = list(ds_water.sample(points))
    mask_grid = np.array([bool(w[0]>0) for w in water_samples], dtype=bool).reshape(lat_grid.shape)
    mask_grid = binary_dilation(mask_grid, iterations=water_buffer_cells)
    return lats, lons, mask_grid

def point_to_index(x, y, lats, lons):
    i = int(np.clip(np.searchsorted(lats, y)-1, 0, len(lats)-1))
    j = int(np.clip(np.searchsorted(lons, x)-1, 0, len(lons)-1))
    return i, j

def index_to_point(i,j,lats,lons):
    return float(lons[j]), float(lats[i])

# -----------------------------
# 🛤 Snap stations to land
# -----------------------------
def snap_to_land(x, y, mask_grid, lats, lons, max_radius=0.01):
    i0,j0 = point_to_index(x,y,lats,lons)
    if mask_grid[i0,j0]: return x,y
    max_steps = max(1,int(max_radius/max(abs(lats[1]-lats[0]),1e-6)))
    for r in range(1,max_steps+1):
        for di in range(-r,r+1):
            for dj in range(-r,r+1):
                if abs(di)!=r and abs(dj)!=r: continue
                ni,nj = i0+di,j0+dj
                if 0<=ni<mask_grid.shape[0] and 0<=nj<mask_grid.shape[1]:
                    if mask_grid[ni,nj]: return index_to_point(ni,nj,lats,lons)
    return x,y

# -----------------------------
# ⭐ A* pathfinding with cancel support
# -----------------------------
def astar(start, goal, mask_grid, lats, lons, cancel_flag=None):
    start_i,start_j = point_to_index(*start,lats,lons)
    goal_i,goal_j = point_to_index(*goal,lats,lons)
    visited = np.zeros_like(mask_grid,dtype=bool)
    heap = []
    heappush(heap,(0,(start_i,start_j),[(start_i,start_j)]))
    
    while heap:
        if cancel_flag and cancel_flag():  # <-- check here
            return []  # immediately exit if cancelled
        cost,(i,j),path = heappop(heap)
        if visited[i,j]: continue
        visited[i,j]=True
        if (i,j)==(goal_i,goal_j): 
            return [index_to_point(pi,pj,lats,lons) for pi,pj in path]
        for di in [-1,0,1]:
            for dj in [-1,0,1]:
                if di==0 and dj==0: continue
                ni,nj = i+di,j+dj
                if 0<=ni<mask_grid.shape[0] and 0<=nj<mask_grid.shape[1]:
                    if not mask_grid[ni,nj] or visited[ni,nj]: continue
                    g = cost + math.hypot(di,dj)
                    h = math.hypot(goal_i-ni, goal_j-nj)
                    heappush(heap,(g+h,(ni,nj),path+[(ni,nj)]))
    return [start, goal]


# -----------------------------
# ✨ Smooth path
# -----------------------------
def rdp_smooth(points, epsilon=0.0003):
    if len(points)<3: return points
    simplified = LineString(points).simplify(epsilon,preserve_topology=True)
    return [(pt[0],pt[1]) for pt in simplified.coords]

# -----------------------------
# 📄 Export GeoJSON
# -----------------------------
def export_geojson(route, stations, path_geojson):
    features=[]
    for (x,y),name in stations:
        features.append({"type":"Feature","geometry":{"type":"Point","coordinates":[x,y]},"properties":{"name":name}})
    features.append({"type":"Feature","geometry":{"type":"LineString","coordinates":route},"properties":{"type":"OptimizedRoute"}})
    with open(path_geojson,'w',encoding='utf-8') as f:
        json.dump({"type":"FeatureCollection","features":features},f,indent=2)

# -----------------------------
# 💾 Export CSV
# -----------------------------
def export_segment_details_csv(segment_details, path):
    with open(path,'w',newline='',encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=["start","end","length_km","cost"])
        writer.writeheader()
        for seg in segment_details: writer.writerow(seg)

# -----------------------------
# 🗺 Generate folium map with animated train
# -----------------------------
def export_route_map(route, stations, path_html):
    mid_lat = sum(pt[1] for pt in route)/len(route)
    mid_lon = sum(pt[0] for pt in route)/len(route)
    m = folium.Map(location=[mid_lat,mid_lon],zoom_start=13,tiles='cartodbpositron')

    # Route polyline
    folium.PolyLine([[pt[1],pt[0]] for pt in route], color='cyan', weight=4).add_to(m)

    # Station markers
    for coord,name in stations:
        folium.Marker([coord[1],coord[0]], popup=name, icon=folium.Icon(color='red')).add_to(m)

    # Train icon
    train_icon_path = os.path.join(STATIC_DIR, 'train.png')
    if os.path.exists(train_icon_path):
        train_icon = folium.CustomIcon(train_icon_path, icon_size=(32,32))
    else:
        train_icon = folium.Icon(icon='train', prefix='fa', color='blue')

    folium.Marker(location=[route[0][1],route[0][0]], icon=train_icon, popup="Train").add_to(m)

    # Looping train JS
    coords_js = [[pt[1],pt[0]] for pt in route]
    train_js = f"""
    var route = {coords_js};
    var map = {{map}};
    var trainIcon = L.icon({{iconUrl:'{train_icon_path.replace('\\\\','/')}', iconSize:[32,32]}});
    var marker = L.marker(route[0], {{icon: trainIcon}}).addTo(map);
    var index = 0;
    function moveTrain(){{
        marker.setLatLng(route[index]);
        index = (index + 1) % route.length;
        setTimeout(moveTrain, 100);
    }}
    moveTrain();
    """
    m.get_root().html.add_child(folium.Element(f"<script>{train_js}</script>"))
    m.save(path_html)

# -----------------------------
# 🚀 Run optimizer
# -----------------------------
def run_optimizer(geojson_path, streaming=False, cancel_flag=None):
    water_path = os.path.join(RASTER_DIR,"australasia.tif")
    elev_path  = os.path.join(RASTER_DIR,"elevation.tif")

    if streaming: yield "Loading rasters..."
    water_mask, elevation, ds_water, ds_elev = load_rasters(water_path,elev_path)
    if cancel_flag and cancel_flag(): yield "CANCELLED"; return

    if streaming: yield "Parsing GeoJSON..."
    stations = parse_geojson(geojson_path)
    if cancel_flag and cancel_flag(): yield "CANCELLED"; return

    if streaming: yield "Creating grid..."
    lats,lons,mask_grid = create_grid(stations, ds_water)
    if cancel_flag and cancel_flag(): yield "CANCELLED"; return

    if streaming: yield "Snapping stations to land..."
    snapped_coords = [snap_to_land(x,y,mask_grid,lats,lons) for x,y in [s[0] for s in stations]]

    full_route=[]
    segment_details=[]
    for i in range(len(snapped_coords)-1):
        if cancel_flag and cancel_flag(): yield "CANCELLED"; return
        if streaming: yield f"Finding path {i+1}/{len(snapped_coords)-1}..."
        segment = astar(snapped_coords[i], snapped_coords[i+1], mask_grid,lats,lons,cancel_flag=cancel_flag)
        if cancel_flag and cancel_flag(): yield "CANCELLED"; return
        if i>0: segment = segment[1:]
        full_route.extend(segment)
        seg_length = haversine(snapped_coords[i],snapped_coords[i+1])
        corner_pen = 0.01
        segment_details.append({
            "start": snapped_coords[i],
            "end": snapped_coords[i+1],
            "length_km": round(seg_length,2),
            "cost": compute_segment_cost(seg_length, corner_penalty=corner_pen)
        })


    if streaming: yield "Smoothing route..."
    full_route = rdp_smooth(full_route)

    csv_path = os.path.join(OUTPUT_DIR,"segment_details.csv")
    geojson_path_out = os.path.join(OUTPUT_DIR,"optimized_route.geojson")
    if streaming: yield "Exporting CSV..."
    export_segment_details_csv(segment_details,csv_path)
    if streaming: yield "Exporting GeoJSON..."
    export_geojson(full_route,stations,geojson_path_out)
    map_path = os.path.join(OUTPUT_DIR,"route_map.html")
    if streaming: yield "Exporting Map..."
    export_route_map(full_route,stations,map_path)
    if streaming: yield "done"
    return {"geojson": geojson_path_out,"csv":csv_path}
