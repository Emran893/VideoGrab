from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp
import os
import tempfile
import uuid
import traceback
import shutil
import subprocess
import logging
import json
import re

# =============================================
# FFMPEG पाथ सेटअप
# =============================================
FFMPEG_PATH = None
FFPROBE_PATH = None

for possible_path in ['/usr/bin/ffmpeg', '/usr/local/bin/ffmpeg', '/bin/ffmpeg', shutil.which('ffmpeg')]:
    if possible_path and os.path.exists(possible_path):
        FFMPEG_PATH = possible_path
        break

for possible_path in ['/usr/bin/ffprobe', '/usr/local/bin/ffprobe', '/bin/ffprobe', shutil.which('ffprobe')]:
    if possible_path and os.path.exists(possible_path):
        FFPROBE_PATH = possible_path
        break

if not FFMPEG_PATH:
    try:
        import imageio_ffmpeg
        FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
        os.environ["PATH"] = os.path.dirname(FFMPEG_PATH) + os.pathsep + os.environ.get("PATH", "")
        FFPROBE_PATH = os.path.join(os.path.dirname(FFMPEG_PATH), 'ffprobe')
        if not os.path.exists(FFPROBE_PATH):
            FFPROBE_PATH = None
    except ImportError:
        pass

FFMPEG_LOCATION = os.path.dirname(FFMPEG_PATH) if FFMPEG_PATH else None

# Flask ऐप
app = Flask(__name__)
app.url_map.strict_slashes = False
application = app

logging.basicConfig(level=logging.INFO)
app.logger.setLevel(logging.INFO)

DOWNLOAD_FOLDER = tempfile.mkdtemp()
app.logger.info(f'📂 डाउनलोड फोल्डर: {DOWNLOAD_FOLDER}')
app.logger.info(f'🎬 FFMPEG: {FFMPEG_PATH}')


def get_ydl_opts(extractor='generic'):
    """हर साइट के लिए बेस्ट कॉन्फिग - वॉटरमार्क कम करने की कोशिश"""
    opts = {
        'quiet': True,
        'no_warnings': True,
        'ffmpeg_location': FFMPEG_LOCATION,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
        }
    }

    extractor_lower = extractor.lower()

    if 'youtube' in extractor_lower:
        opts['extractor_args'] = {
            'youtube': {'player_client': ['android_vr', 'web']}
        }

    elif 'tiktok' in extractor_lower:
        # TikTok - बिना वॉटरमार्क के लिए स्पेशल API
        opts['extractor_args'] = {
            'tiktok': {
                'api_hostname': ['api16-normal-c-useast1a.tiktokv.com'],
                'app_version': ['35.0.3'],
            }
        }
        opts['http_headers']['User-Agent'] = 'com.zhiliaoapp.musically/35.0.3 (Linux; Android 13; Pixel 7)'
        opts['http_headers']['Referer'] = 'https://www.tiktok.com/'

    elif 'instagram' in extractor_lower:
        opts['http_headers']['User-Agent'] = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1'

    elif 'facebook' in extractor_lower:
        # Facebook - वॉटरमार्क कम करने के लिए स्पेशल हेडर्स
        opts['http_headers'].update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://www.facebook.com/',
            'Origin': 'https://www.facebook.com',
            'Sec-Fetch-Site': 'same-origin',
        })

    return opts


def get_video_dimensions(filepath):
    """ffprobe से वीडियो की width, height निकालें"""
    if not FFPROBE_PATH:
        return None, None
    try:
        cmd = [
            FFPROBE_PATH, '-v', 'quiet', '-print_format', 'json',
            '-select_streams', 'v:0', '-show_entries', 'stream=width,height', filepath
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        data = json.loads(result.stdout)
        streams = data.get('streams', [])
        if streams:
            return streams[0].get('width'), streams[0].get('height')
    except Exception as e:
        app.logger.warning(f'ffprobe एरर: {e}')
    return None, None


def detect_watermark_area(filepath):
    """
    वॉटरमार्क का एरिया ऑटो-डिटेक्ट करें
    आमतौर पर वॉटरमार्क निचे दाएं या निचे बाएं कोने में होता है
    """
    width, height = get_video_dimensions(filepath)
    if not width or not height:
        return None

    # वॉटरमार्क आमतौर पर निचे के 12% हिस्से में होता है
    # और दाएं कोने में (Facebook/Instagram) या बाएं (कुछ साइटें)
    watermark_height = int(height * 0.12)  # निचे का 12%
    watermark_width = int(width * 0.35)    # चौड़ाई का 35%

    # delogo filter के लिए पैरामीटर:
    # x, y = वॉटरमार्क का टॉप-लेफ्ट कोना
    # w, h = वॉटरमार्क की चौड़ाई और ऊंचाई
    # band, show = डिटेक्शन के लिए

    # दाएं निचे का कोना (सबसे आम)
    return {
        'x': width - watermark_width - 10,   # दाएं से थोड़ा अंदर
        'y': height - watermark_height - 5,  # निचे से थोड़ा अंदर
        'w': watermark_width,
        'h': watermark_height,
        'band': 10,
        'crop_bottom': int(height * 0.08)
    }


def clean_video_with_ffmpeg(input_path, output_path, method='delogo'):
    """
    ffmpeg से वॉटरमार्क हटाएं + मेटाडेटा साफ़ करें
    
    तरीके (methods):
    - 'delogo' : ffmpeg का delogo filter (सबसे अच्छा)
    - 'blur'   : वॉटरमार्क एरिया को ब्लर करें
    - 'crop'   : निचे का हिस्सा काट दें
    - 'none'   : सिर्फ मेटाडेटा हटाएं, वॉटरमार्क नहीं छुएं
    """
    if not FFMPEG_PATH:
        return False, "ffmpeg उपलब्ध नहीं है"

    try:
        wm_area = detect_watermark_area(input_path)
        width, height = get_video_dimensions(input_path)

        # ffmpeg कमांड
        cmd = [FFMPEG_PATH, '-y', '-i', input_path]

        # वीडियो फिल्टर बनाएं
        vf_parts = []

        if method == 'delogo' and wm_area:
            # delogo filter - सबसे बेहतरीन
            vf_parts.append(
                f"delogo=x={wm_area['x']}:y={wm_area['y']}:w={wm_area['w']}:h={wm_area['h']}:band={wm_area['band']}"
            )
            app.logger.info(f'🎯 Delogo filter: x={wm_area["x"]} y={wm_area["y"]} w={wm_area["w"]} h={wm_area["h"]}')

        elif method == 'blur' and wm_area:
            # blur filter - वॉटरमार्क एरिया को धुंधला करें
            x, y, w, h = wm_area['x'], wm_area['y'], wm_area['w'], wm_area['h']
            vf_parts.append(
                f"[0:v]crop={w}:{h}:{x}:{y},boxblur=10:10[blurred];"
                f"[0:v][blurred]overlay={x}:{y}"
            )
            app.logger.info(f'🌫️ Blur filter: x={x} y={y} w={w} h={h}')

        elif method == 'crop' and height:
            # crop - निचे का हिस्सा काटें
            crop_amount = int(height * 0.08)
            new_h = height - crop_amount
            vf_parts.append(f'crop=iw:{new_h}:0:0')
            app.logger.info(f'✂️ Crop filter: निचे का {crop_amount}px काटा गया')

        # method == 'none' → कोई वीडियो फिल्टर नहीं, सिर्फ मेटाडेटा हटाएं

        # सभी मेटाडेटा हटाएं
        cmd += ['-map_metadata', '-1']

        # वीडियो फिल्टर लगाएं
        if vf_parts:
            if method == 'blur':
                # blur के लिए -filter_complex चाहिए
                cmd += ['-filter_complex', vf_parts[0]]
            else:
                cmd += ['-vf', ','.join(vf_parts)]

        # सभी मेटाडेटा टैग खाली करें
        cmd += [
            '-metadata', 'title=',
            '-metadata', 'artist=',
            '-metadata', 'album_artist=',
            '-metadata', 'album=',
            '-metadata', 'date=',
            '-metadata', 'comment=',
            '-metadata', 'description=',
            '-metadata', 'encoded_by=',
            '-metadata', 'encoder=',
            '-metadata', 'copyright=',
            '-metadata', 'publisher=',
            '-metadata:s:v', 'title=',
            '-metadata:s:a', 'title=',
        ]

        # क्वालिटी बनाए रखें
        cmd += ['-c:v', 'libx264', '-preset', 'fast', '-crf', '18']
        cmd += ['-c:a', 'aac', '-b:a', '192k']
        cmd += ['-movflags', '+faststart']
        cmd += [output_path]

        app.logger.info(f'🧹 ffmpeg कमांड चल रहा है (method={method})...')

        # चलाएं
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

        if result.returncode != 0:
            app.logger.error(f'ffmpeg एरर (आखरी 500 अक्षर): {result.stderr[-500:]}')
            return False, f'ffmpeg एरर: {result.stderr[-200:]}'

        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            return False, 'साफ़ की गई फ़ाइल बनी नहीं'

        file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
        app.logger.info(f'✅ साफ़ वीडियो तैयार: {file_size_mb:.1f} MB')

        return True, 'सफल'

    except subprocess.TimeoutExpired:
        return False, 'समय सीमा पूरी (बड़ा वीडियो हो सकता है)'
    except Exception as e:
        app.logger.error(f'क्लीनिंग एरर: {traceback.format_exc()}')
        return False, str(e)


# =============================================
# Flask Routes
# =============================================

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'OK',
        'yt_dlp': yt_dlp.version.__version__,
        'ffmpeg_path': FFMPEG_PATH,
        'ffmpeg_found': FFMPEG_PATH is not None,
    })


@app.route('/api/get-formats', methods=['POST'])
def get_formats():
    try:
        data = request.get_json(force=True, silent=True) or {}
        url = data.get('url', '').strip()

        if not url:
            return jsonify({'error': 'कृपया वीडियो का URL डालें'}), 400

        app.logger.info(f'🔍 प्रोसेस हो रहा URL: {url[:80]}...')

        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            extractor = info.get('extractor', 'generic')

        app.logger.info(f'📱 एक्सट्रैक्टर: {extractor}')

        with yt_dlp.YoutubeDL(get_ydl_opts(extractor)) as ydl:
            info = ydl.extract_info(url, download=False)

            video_info = {
                'title': info.get('title', 'Video'),
                'thumbnail': info.get('thumbnail', ''),
                'duration': info.get('duration', 0),
                'extractor': extractor,
                'max_quality': '',
                'max_format_id': ''
            }

            formats = []
            seen = set()
            for f in info.get('formats', []):
                h = f.get('height')
                if h and h not in seen:
                    seen.add(h)
                    filesize = f.get('filesize') or f.get('filesize_approx') or 0
                    formats.append({
                        'format_id': f['format_id'],
                        'resolution': f'{h}p',
                        'height': h,
                        'ext': f.get('ext', 'mp4'),
                        'fps': f.get('fps', 30),
                        'filesize_mb': round(filesize / 1048576, 1) if filesize else 'N/A',
                    })
            formats.sort(key=lambda x: x['height'], reverse=True)

            if formats:
                video_info['max_quality'] = formats[0]['resolution']
                video_info['max_format_id'] = formats[0]['format_id']

            audio = []
            seen_abr = set()
            for f in info.get('formats', []):
                if f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                    abr = f.get('abr', 0)
                    if abr and abr not in seen_abr:
                        seen_abr.add(abr)
                        audio.append({
                            'format_id': f['format_id'],
                            'abr': round(abr),
                            'ext': f.get('ext', 'm4a')
                        })
            audio.sort(key=lambda x: x['abr'], reverse=True)

        app.logger.info(f'✅ {len(formats)} वीडियो + {len(audio)} ऑडियो फॉर्मेट')
        return jsonify({
            'video_info': video_info,
            'formats': formats,
            'audio': audio[:3]
        })

    except Exception as e:
        app.logger.error(f'❌ एरर: {str(e)}')
        app.logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


def _download_raw(url, fmt_id, is_audio):
    """वीडियो डाउनलोड करें और फ़ाइल का पाथ लौटाएं"""
    uid = str(uuid.uuid4())
    out = os.path.join(DOWNLOAD_FOLDER, f'{uid}.%(ext)s')

    with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
        info = ydl.extract_info(url, download=False)
        extractor = info.get('extractor', 'generic')
        video_title = info.get('title', 'video')

    opts = get_ydl_opts(extractor)
    opts.update({
        'outtmpl': out,
        'merge_output_format': 'mp4',
    })

    if is_audio:
        opts['format'] = fmt_id
        opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192'
        }]
    else:
        if not FFMPEG_PATH:
            opts['format'] = f'best[ext=mp4]/best'
        else:
            opts['format'] = f'{fmt_id}+bestaudio[ext=m4a]/bestaudio/best[ext=mp4]/best'

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    files = [os.path.join(DOWNLOAD_FOLDER, f) for f in os.listdir(DOWNLOAD_FOLDER) if f.startswith(uid)]
    if not files:
        return None, None, 'फ़ाइल नहीं बनी'

    filepath = max(files, key=os.path.getctime)
    safe_title = "".join(c for c in video_title if c.isalnum() or c in ' -_()[]')[:80]
    return filepath, safe_title, None


@app.route('/api/download', methods=['POST'])
def download():
    """सामान्य डाउनलोड"""
    try:
        data = request.get_json(force=True, silent=True) or {}
        url = data.get('url', '').strip()
        fmt_id = data.get('format_id', 'best')
        is_audio = data.get('type') == 'audio'

        if not url:
            return jsonify({'error': 'URL खाली है'}), 400

        filepath, safe_title, err = _download_raw(url, fmt_id, is_audio)
        if err:
            return jsonify({'error': err}), 500

        ext = os.path.splitext(filepath)[1]
        return send_file(filepath, as_attachment=True, download_name=f'{safe_title}{ext}')

    except Exception as e:
        app.logger.error(f'❌ डाउनलोड एरर: {str(e)}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/download-clean', methods=['POST'])
def download_clean():
    """⭐ साफ़ वीडियो डाउनलोड - वॉटरमार्क + मेटाडेटा हटाकर"""
    try:
        data = request.get_json(force=True, silent=True) or {}
        url = data.get('url', '').strip()
        fmt_id = data.get('format_id', 'best')
        method = data.get('method', 'delogo')  # delogo / blur / crop / none

        if not url:
            return jsonify({'error': 'URL खाली है'}), 400

        if not FFMPEG_PATH:
            return jsonify({'error': 'ffmpeg उपलब्ध नहीं है'}), 500

        valid_methods = ['delogo', 'blur', 'crop', 'none']
        if method not in valid_methods:
            method = 'delogo'

        app.logger.info(f'🧹 साफ़ वीडियो शुरू, तरीका={method}')

        # Step 1: डाउनलोड करें
        filepath, safe_title, err = _download_raw(url, fmt_id, is_audio=False)
        if err:
            return jsonify({'error': err}), 500

        # Step 2: ffmpeg से साफ़ करें
        clean_uid = str(uuid.uuid4())
        clean_path = os.path.join(DOWNLOAD_FOLDER, f'{clean_uid}_CLEAN.mp4')

        success, clean_err = clean_video_with_ffmpeg(filepath, clean_path, method)

        # असली फ़ाइल हटाएं
        try:
            os.remove(filepath)
        except:
            pass

        if not success:
            return jsonify({'error': f'साफ़ करने में गड़बड़: {clean_err}'}), 500

        method_suffix = {'delogo': '_CLEAN', 'blur': '_BLUR', 'crop': '_CROPPED', 'none': '_NOMETA'}
        suffix = method_suffix.get(method, '_CLEAN')

        return send_file(
            clean_path,
            as_attachment=True,
            download_name=f'{safe_title}{suffix}.mp4'
        )

    except Exception as e:
        app.logger.error(f'❌ क्लीन डाउनलोड एरर: {str(e)}')
        app.logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.logger.info(f'🚀 सर्वर पोर्ट {port} पर शुरू हो रहा है...')
    app.run(host='0.0.0.0', port=port, debug=False)
