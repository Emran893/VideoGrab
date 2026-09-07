from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp
import os
import tempfile
import uuid
import traceback
import imageio_ffmpeg

# ffmpeg path auto-set - Railway/Vercel/Render पर काम करेगा
os.environ["PATH"] = os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe()) + os.pathsep + os.environ.get("PATH", "")

app = Flask(__name__)
app.url_map.strict_slashes = False
application = app  # Gunicorn के लिए

DOWNLOAD_FOLDER = tempfile.mkdtemp()


def get_ydl_opts(extractor='generic'):
    """हर साइट के लिए बेस्ट कॉन्फिग"""
    opts = {
        'quiet': True,
        'no_warnings': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
        }
    }

    extractor_lower = extractor.lower()

    # YouTube - Android VR क्लाइंट (बॉट डिटेक्शन कम)
    if 'youtube' in extractor_lower:
        opts['extractor_args'] = {
            'youtube': {'player_client': ['android_vr', 'web']}
        }

    # TikTok - बिना वॉटरमार्क
    elif 'tiktok' in extractor_lower:
        opts['http_headers']['User-Agent'] = 'com.zhiliaoapp.musically/35.0.3 (Linux; Android 13; Pixel 7)'
        opts['http_headers']['Referer'] = 'https://www.tiktok.com/'

    # Instagram
    elif 'instagram' in extractor_lower:
        opts['http_headers']['User-Agent'] = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15'

    # Facebook
    elif 'facebook' in extractor_lower:
        opts['http_headers'].update({
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5'
        })

    return opts


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'OK', 'yt_dlp': yt_dlp.version.__version__})


@app.route('/api/get-formats', methods=['POST'])
def get_formats():
    try:
        data = request.get_json(force=True, silent=True) or {}
        url = data.get('url', '').strip()

        if not url:
            return jsonify({'error': 'कृपया वीडियो का URL डालें'}), 400

        # एक्सट्रैक्टर पहचानें
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            extractor = info.get('extractor', 'generic')

        # सही कॉन्फिग के साथ फिर से एक्सट्रैक्ट करें
        with yt_dlp.YoutubeDL(get_ydl_opts(extractor)) as ydl:
            info = ydl.extract_info(url, download=False)

            video_info = {
                'title': info.get('title', 'Video'),
                'thumbnail': info.get('thumbnail', ''),
                'duration': info.get('duration', 0),
                'extractor': extractor
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
                        'filesize_mb': round(filesize / 1048576, 1) if filesize else 'N/A'
                    })
            formats.sort(key=lambda x: x['height'], reverse=True)

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

        return jsonify({
            'video_info': video_info,
            'formats': formats,
            'audio': audio[:3]
        })

    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@app.route('/api/download', methods=['POST'])
def download():
    try:
        data = request.get_json(force=True, silent=True) or {}
        url = data.get('url', '').strip()
        fmt_id = data.get('format_id', 'best')
        is_audio = data.get('type') == 'audio'

        if not url:
            return jsonify({'error': 'URL खाली है'}), 400

        uid = str(uuid.uuid4())
        out = os.path.join(DOWNLOAD_FOLDER, f'{uid}.%(ext)s')

        # एक्सट्रैक्टर पहचानें
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            extractor = info.get('extractor', 'generic')
            video_title = info.get('title', 'video')

        # डाउनलोड कॉन्फिग
        opts = get_ydl_opts(extractor)
        opts.update({
            'outtmpl': out,
            'merge_output_format': 'mp4',
            'ffmpeg_location': imageio_ffmpeg.get_ffmpeg_exe()
        })

        if is_audio:
            opts['format'] = fmt_id
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192'
            }]
        else:
            opts['format'] = f'{fmt_id}+bestaudio[ext=m4a]/bestaudio'

        # डाउनलोड करें
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

        # डाउनलोड की गई फ़ाइल ढूंढें
        files = [os.path.join(DOWNLOAD_FOLDER, f) for f in os.listdir(DOWNLOAD_FOLDER) if f.startswith(uid)]
        if not files:
            return jsonify({'error': 'फ़ाइल नहीं बनी'}), 500

        filepath = max(files, key=os.path.getctime)
        safe_title = "".join(c for c in video_title if c.isalnum() or c in ' -_()[]')[:80]
        ext = os.path.splitext(filepath)[1]

        return send_file(filepath, as_attachment=True, download_name=f'{safe_title}{ext}')

    except Exception as e:
        app.logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
