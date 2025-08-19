const runBtn = document.getElementById("run-btn");
const cancelBtn = document.getElementById("cancel-btn");
const fileInput = document.getElementById("file-input");
const demoSelect = document.getElementById("demo-files");
const progressBar = document.getElementById("progress-bar");
const progressText = document.getElementById("progress-text");
const mapPreview = document.getElementById("map-preview");
const downloadsDiv = document.getElementById("downloads");
const infoPanel = document.getElementById("info-panel");
const uploadBox = document.getElementById("upload-box");

let currentController = null;

// Drag & drop upload
uploadBox.addEventListener("click", () => fileInput.click());
uploadBox.addEventListener("dragover", e => { e.preventDefault(); uploadBox.style.background = "#111"; });
uploadBox.addEventListener("dragleave", e => { e.preventDefault(); uploadBox.style.background = "#0a0a0a"; });
uploadBox.addEventListener("drop", e => { e.preventDefault(); fileInput.files = e.dataTransfer.files; });

// Run optimizer
runBtn.addEventListener("click", async () => {
    if(currentController) currentController.abort();
    currentController = new AbortController();

    const file = fileInput.files[0];
    const demoFile = demoSelect.value;
    const formData = new FormData();
    if(file) formData.append("geojson_file", file);
    else formData.append("demo_file", demoFile);

    progressBar.style.width = "0%";
    progressText.textContent = "0%";
    downloadsDiv.innerHTML = "";
    mapPreview.innerHTML = "";
    infoPanel.innerHTML = "";

    try {
        const response = await fetch("/run", { method: "POST", body: formData, signal: currentController.signal });
        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        async function readStream() {
            const {done, value} = await reader.read();
            if(done) return;
            const text = decoder.decode(value);
            const lines = text.split("\n\n");
            for(const line of lines){
                if(!line) continue;

                if(line.includes("CANCELLED")){
                    infoPanel.innerHTML = "<p>Operation Cancelled!</p>";
                    progressBar.style.width = "0%";
                    progressText.textContent = "0%";
                    return;
                }

                if(line.startsWith("done")){
                    progressBar.style.width = "100%";
                    progressText.textContent = "100%";
                    downloadsDiv.innerHTML = `
                        <a href="/outputs/optimized_route.geojson" download>Download GeoJSON</a>
                        <a href="/outputs/segment_details.csv" download>Download CSV</a>
                        <a href="/outputs/route_map.html" download>Download Map</a>
                    `;
                    displayMap();
                } else {
                    progressText.textContent = line;
                    progressBar.style.width = (Math.random()*80 + 10).toFixed(0) + "%";
                }
            }
            readStream();
        }
        readStream();

    } catch(err) {
        if(err.name === "AbortError") {
            infoPanel.innerHTML = "<p>Operation Cancelled!</p>";
        } else {
            console.error(err);
        }
    }
});

// Cancel optimizer
cancelBtn.addEventListener("click", () => {
    if(currentController) currentController.abort();
});

// Display map with animated train
async function displayMap(){
    const res = await fetch("/outputs/optimized_route.geojson");
    const data = await res.json();
    const coords = data.features.find(f => f.geometry.type === "LineString").geometry.coordinates;
    const latlngs = coords.map(c => [c[1], c[0]]);
    const map = L.map('map-preview').setView(latlngs[0], 13);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; OpenStreetMap contributors' }).addTo(map);
    L.polyline(latlngs, {color:'cyan', weight:4}).addTo(map);

    const trainIcon = L.icon({
    iconUrl: '/static/train.png', // Flask serves anything in /static automatically
    iconSize: [32, 32]
});

    const marker = L.marker(latlngs[0], {icon: trainIcon}).addTo(map);

    let idx = 0;
    let totalDistance = 0;
    const speed = 60; // km/h

    function haversine(lat1, lon1, lat2, lon2){
        const R = 6371;
        const dLat = (lat2-lat1)*Math.PI/180;
        const dLon = (lon2-lon1)*Math.PI/180;
        const a = Math.sin(dLat/2)**2 + Math.cos(lat1*Math.PI/180)*Math.cos(lat2*Math.PI/180)*Math.sin(dLon/2)**2;
        const c = 2*Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
        return R*c;
    }

    function updateStats(){
        if(idx === 0) return;
        totalDistance += haversine(latlngs[idx-1][0], latlngs[idx-1][1], latlngs[idx][0], latlngs[idx][1]);
        const mins = Math.floor((totalDistance / speed) * 60);
        infoPanel.innerHTML = `<p>Distance: ${totalDistance.toFixed(2)} km | Time: ${mins} min | Avg Speed: ${speed} km/h</p>`;
    }

    const interval = setInterval(()=>{
        if(idx >= latlngs.length){
            clearInterval(interval);
            return;
        }
        marker.setLatLng(latlngs[idx]);
        updateStats();
        idx++;
    }, 200);
}
