# ===============================
# 🚆 Train Route Optimizer Web Server
# Author: Aaron Sood
# ===============================

from flask import Flask, render_template, request, send_from_directory, jsonify
from main import run_optimizer, GEOJSON_DIR, OUTPUT_DIR
import os

app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

# -----------------------------
# 🧩 Globals for streaming/cancel
# -----------------------------
cancel_flag = False

# -----------------------------
# 🏠 Routes
# -----------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/run", methods=["POST"])
def run():
    global cancel_flag
    cancel_flag = False

    geojson_file = request.files.get("geojson_file")
    demo_file = request.form.get("demo_file")

    # Determine file path
    if geojson_file:
        path = os.path.join(GEOJSON_DIR, geojson_file.filename)
        geojson_file.save(path)
    else:
        path = os.path.join(GEOJSON_DIR, demo_file)

    # Stream progress
    def generator():
        for msg in run_optimizer(path, streaming=True, cancel_flag=lambda: cancel_flag):
           yield f"{msg}\n\n"


    return app.response_class(generator(), mimetype='text/plain')

@app.route("/cancel", methods=["POST"])
def cancel():
    global cancel_flag
    cancel_flag = True
    return "Cancelled"

# -----------------------------
# 📁 File downloads
# -----------------------------
@app.route("/outputs/<path:filename>")
def download_file(filename):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)

@app.route("/geojsons/<path:filename>")
def serve_geojson(filename):
    return send_from_directory(GEOJSON_DIR, filename)

@app.route("/static/<path:filename>")
def serve_static(filename):
    # Serve static train icon
    static_dir = r"C:\ScienceFair\python\static"
    return send_from_directory(static_dir, filename)

# -----------------------------
# 🚀 Run app
# -----------------------------
if __name__ == "__main__":
    app.run(debug=True)
