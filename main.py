import os
import time
import requests
import subprocess 
from flask import Flask, jsonify, request, Response, stream_with_context, send_file
from flask_cors import CORS
import yt_dlp
import imageio_ffmpeg
from datetime import datetime

app = Flask(__name__)
CORS(app)

# --- KONFIGURASI FINAL (60 DETIK & 2X LIMIT) ---
MAX_DOWNLOADS = 2       # LIMIT: 2x Sehari
MAX_DURATION = 60       # DURASI: 60 Detik
SECRET_CODE = "Digital123#" 

OPEN_HOUR = 13  
CLOSE_HOUR = 24 
DELETE_AFTER = 600 
USER_LIMITS = {} 

BASE_DIR = os.path.dirname(os.path.abspath(__file__)).replace('\\', '/')
OUTPUT_FOLDER = f"{BASE_DIR}/output_clips"
if not os.path.exists(OUTPUT_FOLDER): os.makedirs(OUTPUT_FOLDER)

try:
    FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
    print(f"✅ Engine Ready: {FFMPEG_EXE}")
except:
    FFMPEG_EXE = None

def is_store_open():
    now = datetime.now().hour
    if OPEN_HOUR <= now < CLOSE_HOUR: return True
    return False

def cleanup_old_files():
    now = time.time()
    for f in os.listdir(OUTPUT_FOLDER):
        f_path = os.path.join(OUTPUT_FOLDER, f)
        if os.path.isfile(f_path) and (now - os.path.getmtime(f_path) > DELETE_AFTER):
            try: os.remove(f_path)
            except: pass

def get_visitor_ip():
    if request.headers.getlist("X-Forwarded-For"):
        return request.headers.getlist("X-Forwarded-For")[0]
    return request.remote_addr

def is_admin(req_data):
    if req_data.get('secret_key') == SECRET_CODE: return True
    return False

def log_activity(action, details="", admin_status=False):
    ip = get_visitor_ip()
    waktu = datetime.now().strftime("%H:%M:%S")
    status = "👑 ADMIN" if admin_status else "👤 USER"
    print(f"🕵️ [{waktu}] IP: {ip} [{status}] | {action} {details}")

@app.route('/')
def home(): 
    if os.path.exists('index.html'): return send_file('index.html')
    return "<h1>AO Studio Ready</h1>"

@app.route('/logo.png')
def serve_logo():
    if os.path.exists('logo.png'): return send_file('logo.png')
    return "", 404

@app.route('/qris.jpg')
def serve_qris():
    if os.path.exists('qris.jpg'): return send_file('qris.jpg')
    return "", 404

@app.route('/check-key', methods=['POST'])
def check_key():
    if request.json.get('key') == SECRET_CODE: return jsonify({'valid': True})
    return jsonify({'valid': False})

@app.route('/get-stream-url', methods=['POST'])
def get_video_info():
    global current_video_url
    data = request.json
    url = data.get('url')
    admin_access = is_admin(data)
    
    if not is_store_open() and not admin_access:
        return jsonify({'error': f"😴 CLOSED. OPEN: {OPEN_HOUR}.00 - {CLOSE_HOUR}.00 WIB"}), 403

    if not admin_access:
        ip = get_visitor_ip()
        if USER_LIMITS.get(ip, 0) >= MAX_DOWNLOADS:
            return jsonify({'error': f"❌ LIMIT HABIS (Max {MAX_DOWNLOADS}x/Hari). Upgrade ke VIP!"}), 403

    log_activity("LOAD", f"Video: {url}", admin_access)
    
    ydl_opts = {'format': '18', 'quiet': True, 'force_ipv4': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            current_video_url = info['url']
            
            meta = {
                'title': info.get('title', 'Unknown Title'),
                'uploader': info.get('uploader', 'Unknown Channel'),
                'duration': info.get('duration_string', '0:00'),
                'thumbnail': info.get('thumbnail', '')
            }
            return jsonify({'success': True, 'stream_url': '/stream_proxy', 'meta': meta})
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/stream_proxy')
def stream_video():
    if not current_video_url: return "No URL", 404
    req = requests.get(current_video_url, stream=True)
    return Response(stream_with_context(req.iter_content(chunk_size=1024*256)), content_type='video/mp4')

@app.route('/process-clip', methods=['POST'])
def process_clip():
    cleanup_old_files()
    ip = get_visitor_ip()
    data = request.json
    start = float(data.get('start'))
    end = float(data.get('end'))
    ratio = data.get('ratio', 'original')
    position = float(data.get('position', 50)) / 100 
    
    admin_access = is_admin(data)

    if not is_store_open() and not admin_access:
         return jsonify({'error': f"😴 CLOSED."}), 403

    if not admin_access:
        usage_count = USER_LIMITS.get(ip, 0)
        if usage_count >= MAX_DOWNLOADS:
            return jsonify({'error': f"⛔ LIMIT HABIS! Max {MAX_DOWNLOADS}x download."}), 403
        
        duration = end - start
        if duration > MAX_DURATION:
            return jsonify({'error': f"⚠️ FREE LIMIT: Max {MAX_DURATION} Detik!"}), 400

    log_activity("CUT", f"-> {start}-{end}s ({ratio})", admin_access)

    safe_ratio = ratio.replace(':', '-')
    final_filename = f"clip_{safe_ratio}_{int(time.time())}.mp4"
    final_filepath = f"{OUTPUT_FOLDER}/{final_filename}"
    temp_filename = f"temp_{int(time.time())}.mp4"
    
    ydl_opts = {
        'format': '22/18/best[ext=mp4]', 'outtmpl': temp_filename,
        'download_ranges': lambda _, __: [{'start_time': start, 'end_time': end}],
        'ffmpeg_location': FFMPEG_EXE, 'quiet': True, 'force_keyframes_at_cuts': True
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl: ydl.download([data.get('url')])
        if not os.path.exists(temp_filename): raise Exception("Download Failed")
        
        if ratio == 'original':
            if os.path.exists(final_filepath): os.remove(final_filepath)
            os.rename(temp_filename, final_filepath)
        else:
            crop = f"crop=ih*(9/16):ih:(iw-ow)*{position}:0" if ratio == '9:16' else f"crop=ih:ih:(iw-ow)*{position}:0"
            subprocess.run([FFMPEG_EXE, '-y', '-i', temp_filename, '-vf', crop, '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'copy', final_filepath], check=True)
            if os.path.exists(temp_filename): os.remove(temp_filename)
            
        if not admin_access: USER_LIMITS[ip] = USER_LIMITS.get(ip, 0) + 1
        return jsonify({'success': True, 'download_url': f"/download/{final_filename}"})

    except Exception as e:
        print(e)
        return jsonify({'error': "Processing Failed."}), 500

@app.route('/download/<path:filename>')
def download_file(filename):
    return send_file(os.path.join(OUTPUT_FOLDER, filename), as_attachment=True)

if __name__ == '__main__':
    print(f"🎬 AO STUDIO V19.3 (FINAL) READY!")
    app.run(host='0.0.0.0', port=5050, threaded=True)