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

# =============================================
# FFMPEG पाथ
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
app.logger.info(f'📦 yt-dlp वर्जन: {yt_dlp.version.__version__}')


def get_ydl_opts(extractor='generic', url=''):
    """हर साइट के लिए बेस्ट कॉन्फिग"""
    opts = {
        'quiet': True,
        'no_warnings': True,
        'ffmpeg_location': FFMPEG_LOCATION,
        'ignoreerrors': False,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
        }
    }

    extractor_lower = extractor.lower()

    # =============================================
    # 🎵 TIKTOK - सबसे एडवांस्ड कॉन्फिग
    # =============================================
    if 'tiktok' in extractor_lower:
        # TikTok के लिए मल्टीपल फॉलबैक स्ट्रैटेजी
        opts.update({
            'extractor_args': {
                'tiktok': {
                    # एक से ज़्यादा API होस्ट ट्राई करेंगे
                    'api_hostname': [
                        'api16-normal-c-useast1a.tiktokv.com',
                        'api22-normal-c-useast2a.tiktokv.com',
                        'api19-normal-c-useast1a.tiktokv.com',
                    ],
                    'app_version': ['35.0.3', '34.5.2', '33.5.3'],
                    'manifest_app_version': ['35.0.3'],
                    'device_id': ['7234567890123456789'],
                }
            },
            'http_headers': {
                # TikTok Android ऐप का असली User-Agent
                'User-Agent': 'com.zhiliaoapp.musically/35.0.3 (Linux; U; Android 13; en_US; Pixel 7; Build/TD1A.220804.031; Cronet/58.0.2991.0)',
                'Accept': 'application/json',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://www.tiktok.com/',
                'x-tt-params': '',
            },
            # कुकीज़ (अगर सेट की हों तो)
            'cookiefile': os.environ.get('TIKTOK_COOKIES', None),
        })

    # =============================================
    # 📺 YouTube
    # =============================================
    elif 'youtube' in extractor_lower:
        opts['extractor_args'] = {
            'youtube': {'player_client': ['android_vr', 'ios', 'web']}
        }

    # =============================================
    # 📸 Instagram
    # =============================================
    elif 'instagram' in extractor_lower:
        opts['http_headers']['User-Agent'] = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1'

    # =============================================
    # 📘 Facebook
    # =============================================
    elif 'facebook' in extractor_lower:
        opts['http_headers'].update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://www.facebook.com/',
        })

    return opts


def get_video_dimensions(filepath):
    if not FFPROBE_PATH:
        return None, None
    try:
        cmd = [FFPROBE_PATH, '-v', 'quiet', '-print_format', 'json',
               '-select_streams', 'v:0', '-show_entries', 'stream=width,height', filepath]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        data = json.loads(result.stdout)
        streams = data.get('streams', [])
        if streams:
            return streams[0].get('width'), streams[0].get('height')
    except Exception as e:
        app.logger.warning(f'ffprobe एरर: {e}')
    return None, None


def detect_watermark_area(filepath):
    """वॉटरमार्क एरिया ऑटो-डिटेक्ट (दाएं निचे कोना)"""
    width, height = get_video_dimensions(filepath)
    if not width or not height:
        return None
    return {
        'x': int(width * 0.60),
        'y': int(height * 0.82),
        'w': int(width * 0.38),
        'h': int(height * 0.16),
        'band': 10,
    }


def clean_video_with_ffmpeg(input_path, output_path, method='delogo'):
    """वॉटरमार्क + मेटाडेटा हटाएं"""
    if not FFMPEG_PATH:
        return False, "ffmpeg उपलब्ध नहीं है"

    try:
        wm_area = detect_watermark_area(input_path)
        width, height = get_video_dimensions(input_path)

        cmd = [FFMPEG_PATH, '-y', '-i', input_path]
        vf_parts = []

        if method == 'delogo' and wm_area:
            vf_parts.append(
                f"delogo=x={wm_area['x']}:y={wm_area['y']}:w={wm_area['w']}:h={wm_area['h']}:band={wm_area['band']}"
            )
        elif method == 'blur' and wm_area:
            x, y, w, h = wm_area['x'], wm_area['y'], wm_area['w'], wm_area['h']
            vf_parts.append(
                f"[0:v]crop={w}:{h}:{x}:{y},boxblur=10:10[blurred];"
                f"[0:v][blurred]overlay={x}:{y}"
            )
        elif method == 'crop' and height:
            new_h = height - int(height * 0.08)
            vf_parts.append(f'crop=iw:{new_h}:0:0')

        cmd += ['-map_metadata', '-1']

        if vf_parts:
            if method == 'blur':
                cmd += ['-filter_complex', vf_parts[0]]
            else:
                cmd += ['-vf', ','.join(vf_parts)]

        cmd += [
            '-metadata', 'title=', '-metadata', 'artist=',
            '-metadata', 'album=', '-metadata', 'date=',
            '-metadata', 'comment=', '-metadata', 'description=',
            '-metadata', 'encoded_by=', '-metadata', 'encoder=',
            '-metadata', 'copyright=', '-metadata', 'publisher=',
        ]

        cmd += ['-c:v', 'libx264', '-preset', 'fast', '-crf', '18']
        cmd += ['-c:a', 'aac', '-b:a', '192k']
        cmd += ['-movflags', '+faststart', output_path]

        app.logger.info(f'🧹 ffmpeg {method} चल रहा है...')
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

        if result.returncode != 0:
            app.logger.error(f'ffmpeg एरर: {result.stderr[-400:]}')
            return False, f'ffmpeg एरर: {result.stderr[-200:]}'

        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            return False, 'साफ़ की गई फ़ाइल बनी नहीं'

        return True, 'सफल'

    except subprocess.TimeoutExpired:
        return False, 'समय सीमा पूरी'
    except Exception as e:
        app.logger.error(f'क्लीनिंग एरर: {traceback.format_exc()}')
        return False, str(e)


# =============================================
# ROUTES
# =============================================

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'OK',
        'yt_dlp': yt_dlp.version.__version__,
        'ffmpeg_found': FFMPEG_PATH is not None,
    })


@app.route('/api/get-formats', methods=['POST'])
def get_formats():
    try:
        data = request.get_json(force=True, silent=True) or {}
        url = data.get('url', '').strip()

        if not url:
            return jsonify({'error': 'कृपया वीडियो का URL डालें'}), 400

        app.logger.info(f'🔍 URL: {url[:80]}...')

        # Step 1: एक्सट्रैक्टर पहचानें
        try:
            with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
                info = ydl.extract_info(url, download=False)
                extractor = info.get('extractor', 'generic')
        except Exception as e:
            app.logger.warning(f'पहली कोशिश फेल: {e}')
            # अगर पहली कोशिश फेल हो तो बेहतर कॉन्फिग के साथ ट्राई करें
            extractor = 'generic'
            if 'tiktok' in url.lower():
                extractor = 'tiktok'
            elif 'youtube' in url.lower():
                extractor = 'youtube'
            elif 'instagram' in url.lower():
                extractor = 'instagram'
            elif 'facebook' in url.lower():
                extractor = 'facebook'

        app.logger.info(f'📱 एक्सट्रैक्टर: {extractor}')

        # Step 2: साइट-स्पेसिफिक कॉन्फिग के साथ एक्सट्रैक्ट करें
        opts = get_ydl_opts(extractor, url)

        # TikTok के लिए मल्टीपल अटेम्प्ट
        max_attempts = 1
        if 'tiktok' in extractor:
            max_attempts = 3

        info = None
        last_error = None

        for attempt in range(1, max_attempts + 1):
            try:
                app.logger.info(f'🔄 एक्सट्रैक्ट अटेम्प्ट {attempt}/{max_attempts}...')
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    break
            except Exception as e:
                last_error = e
                app.logger.warning(f'अटेम्प्ट {attempt} फेल: {str(e)[:100]}')
                # अगले अटेम्प्ट के लिए थोड़ा बदलाव
                if attempt == 1 and 'tiktok' in extractor:
                    opts['http_headers']['User-Agent'] = 'com.ss.android.ugc.trill/35.0.3 (Linux; U; Android 13; en_US; SM-G991B; Build/TP1A.220624.014; Cronet/58.0.2991.0)'

        if not info:
            raise last_error or Exception('वीडियो की जानकारी नहीं मिल सकी')

        video_info = {
            'title': info.get('title', 'Video'),
            'thumbnail': info.get('thumbnail', ''),
            'duration': info.get('duration', 0),
            'extractor': extractor,
            'max_quality': '',
            'max_format_id': ''
        }

        # वीडियो फॉर्मेट
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

        # ऑडियो फॉर्मेट
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
        err_msg = str(e)
        app.logger.error(f'❌ एरर: {err_msg}')
        app.logger.error(traceback.format_exc())

        # यूजर-फ्रेंडली मैसेज
        if 'tiktok' in err_msg.lower() or 'status code 0' in err_msg.lower():
            friendly = ('TikTok का वीडियो अभी उपलब्ध नहीं है। '
                       'कुछ देर बाद फिर प्रयास करें या वीडियो लिंक की जाँच करें।')
        elif 'not available' in err_msg.lower() or 'private' in err_msg.lower():
            friendly = 'यह वीडियो प्राइवेट है या उपलब्ध नहीं है।'
        else:
            friendly = err_msg

        return jsonify({'error': friendly}), 500


def _download_raw(url, fmt_id, is_audio):
    """वीडियो डाउनलोड करें"""
    uid = str(uuid.uuid4())
    out = os.path.join(DOWNLOAD_FOLDER, f'{uid}.%(ext)s')

    # एक्सट्रैक्टर पहचानें
    extractor = 'generic'
    if 'tiktok' in url.lower():
        extractor = 'tiktok'
    elif 'youtube' in url.lower():
        extractor = 'youtube'
    elif 'instagram' in url.lower():
        extractor = 'instagram'
    elif 'facebook' in url.lower():
        extractor = 'facebook'

    try:
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            extractor = info.get('extractor', extractor)
            video_title = info.get('title', 'video')
    except:
        video_title = 'video'

    opts = get_ydl_opts(extractor, url)
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
    """⭐ साफ़ वीडियो"""
    try:
        data = request.get_json(force=True, silent=True) or {}
        url = data.get('url', '').strip()
        fmt_id = data.get('format_id', 'best')
        method = data.get('method', 'delogo')

        if not url:
            return jsonify({'error': 'URL खाली है'}), 400

        if not FFMPEG_PATH:
            return jsonify({'error': 'ffmpeg उपलब्ध नहीं है'}), 500

        valid_methods = ['delogo', 'blur', 'crop', 'none']
        if method not in valid_methods:
            method = 'delogo'

        app.logger.info(f'🧹 साफ़ वीडियो शुरू, तरीका={method}')

        filepath, safe_title, err = _download_raw(url, fmt_id, is_audio=False)
        if err:
            return jsonify({'error': err}), 500

        clean_uid = str(uuid.uuid4())
        clean_path = os.path.join(DOWNLOAD_FOLDER, f'{clean_uid}_CLEAN.mp4')

        success, clean_err = clean_video_with_ffmpeg(filepath, clean_path, method)

        try:
            os.remove(filepath)
        except:
            pass

        if not success:
            return jsonify({'error': f'साफ़ करने में गड़बड़: {clean_err}'}), 500

        suffix = {'delogo': '_CLEAN', 'blur': '_BLUR', 'crop': '_CROPPED', 'none': '_NOMETA'}
        return send_file(clean_path, as_attachment=True,
                        download_name=f'{safe_title}{suffix.get(method, "_CLEAN")}.mp4')

    except Exception as e:
        app.logger.error(f'❌ क्लीन डाउनलोड एरर: {str(e)}')
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.logger.info(f'🚀 सर्वर पोर्ट {port} पर शुरू हो रहा है...')
    app.run(host='0.0.0.0', port=port, debug=False)
