from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp
import os
import tempfile
import uuid
import traceback
import logging

# Flask ऐप सेटअप
app = Flask(__name__)
app.url_map.strict_slashes = False

# Gunicorn के लिए आवश्यक
application = app

# लॉगिंग सेटअप
logging.basicConfig(level=logging.INFO)
app.logger.setLevel(logging.INFO)

# टेम्परेरी डाउनलोड फोल्डर
DOWNLOAD_FOLDER = tempfile.mkdtemp()
app.logger.info(f'डाउनलोड फोल्डर: {DOWNLOAD_FOLDER}')


def get_best_ydl_opts(extractor='generic'):
    """
    हर एक्सट्रैक्टर के लिए बेस्ट कॉन्फिग रिटर्न करता है
    वॉटरमार्क-फ्री + बॉट डिटेक्शन बाईपास
    """
    # बेस कॉन्फिग - सभी के लिए कॉमन
    base_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'ignoreerrors': False,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
    }

    extractor_lower = extractor.lower()

    # ==================== YouTube ====================
    if 'youtube' in extractor_lower:
        # YouTube bot डिटेक्शन बाईपास: Android क्लाइंट का उपयोग
        base_opts.update({
            'extractor_args': {
                'youtube': {
                    # Android क्लाइंट कम ब्लॉक होता है
                    'player_client': ['android'],
                    'player_skip': ['configs', 'webpage'],
                    'skip': ['dash', 'hls'],
                }
            },
            'http_headers': {
                # Android YouTube ऐप का User-Agent
                'User-Agent': 'com.google.android.youtube/18.11.35 (Linux; U; Android 11; en_US; Pixel 4a; Build/RQ3A.211001.001) gzip',
                'Accept-Language': 'en-US,en;q=0.5',
            }
        })

    # ==================== TikTok ====================
    elif 'tiktok' in extractor_lower:
        base_opts.update({
            'extractor_args': {
                'tiktok': {
                    'api_hostname': ['api16-normal-c-useast1a.tiktokv.com'],
                    'app_version': ['35.0.3'],
                }
            },
            'http_headers': {
                'User-Agent': 'com.zhiliaoapp.musically/35.0.3 (Linux; U; Android 13; en_US; Pixel 7; Build/TD1A.220804.031; Cronet/58.0.2991.0)',
                'Referer': 'https://www.tiktok.com/',
            }
        })

    # ==================== Instagram ====================
    elif 'instagram' in extractor_lower:
        base_opts.update({
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
            }
        })

    # ==================== Facebook ====================
    elif 'facebook' in extractor_lower:
        base_opts.update({
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Referer': 'https://www.facebook.com/',
            }
        })

    return base_opts


@app.route('/')
def index():
    """होमपेज सर्व करें"""
    return render_template('index.html')


@app.route('/api/health', methods=['GET'])
def health_check():
    """हेल्थ चेक"""
    return jsonify({
        'status': 'OK',
        'yt_dlp_version': yt_dlp.version.__version__,
        'message': 'API काम कर रहा है!'
    })


@app.route('/api/get-formats', methods=['POST', 'GET'])
def get_formats():
    """URL से उपलब्ध सभी क्वालिटी निकालें"""
    
    # GET रिक्वेस्ट के लिए सिर्फ जानकारी
    if request.method == 'GET':
        return jsonify({
            'status': 'API काम कर रहा है!',
            'how_to_use': 'POST रिक्वेस्ट भेजें JSON body में {"url": "वीडियो_का_लिंक"}'
        })

    try:
        # JSON डेटा पार्स करें
        data = request.get_json(force=True, silent=True) or {}
        url = data.get('url', '').strip()

        if not url:
            return jsonify({'error': 'कृपया वीडियो का URL डालें'}), 400

        app.logger.info(f'🔍 प्रोसेस हो रहा URL: {url[:80]}...')

        # ===== Step 1: एक्सट्रैक्टर का नाम जानें =====
        probe_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }

        with yt_dlp.YoutubeDL(probe_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            extractor = info.get('extractor', 'generic')

        app.logger.info(f'📱 एक्सट्रैक्टर पहचाना गया: {extractor}')

        # ===== Step 2: एक्सट्रैक्टर के अनुसार कॉन्फिग लगाएं =====
        ydl_opts = get_best_ydl_opts(extractor)

        # ===== Step 3: वीडियो की जानकारी निकालें =====
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            video_info = {
                'title': info.get('title', 'Unknown'),
                'thumbnail': info.get('thumbnail', ''),
                'duration': info.get('duration', 0),
                'extractor': extractor,
                'view_count': info.get('view_count', 0),
            }

            # ===== वीडियो फॉर्मेट एक्सट्रैक्ट करें =====
            formats = []
            seen_resolutions = set()

            for f in info.get('formats', []):
                height = f.get('height')
                # केवल वैलिड वीडियो फॉर्मेट लें
                if (height and height >= 144 and 
                    f.get('vcodec') != 'none' and 
                    height not in seen_resolutions):
                    
                    filesize = f.get('filesize') or f.get('filesize_approx') or 0
                    formats.append({
                        'format_id': f['format_id'],
                        'resolution': f'{height}p',
                        'height': height,
                        'ext': f.get('ext', 'mp4'),
                        'filesize_mb': round(filesize / (1024 * 1024), 1) if filesize else 'N/A',
                        'fps': f.get('fps', 30),
                        'type': 'video',
                        'has_audio': f.get('acodec') != 'none'
                    })
                    seen_resolutions.add(height)

            # ===== ऑडियो फॉर्मेट एक्सट्रैक्ट करें =====
            audio_formats = []
            seen_bitrates = set()

            for f in info.get('formats', []):
                if (f.get('acodec') != 'none' and 
                    f.get('vcodec') == 'none'):
                    abr = f.get('abr', 0)
                    if abr and abr not in seen_bitrates and abr >= 48:
                        filesize = f.get('filesize') or f.get('filesize_approx') or 0
                        audio_formats.append({
                            'format_id': f['format_id'],
                            'abr': abr,
                            'ext': f.get('ext', 'm4a'),
                            'filesize_mb': round(filesize / (1024 * 1024), 1) if filesize else 'N/A',
                            'type': 'audio'
                        })
                        seen_bitrates.add(abr)

            # उच्च से निचे क्रम में सॉर्ट करें
            formats.sort(key=lambda x: x.get('height', 0), reverse=True)
            audio_formats.sort(key=lambda x: x.get('abr', 0), reverse=True)

            app.logger.info(f'✅ {len(formats)} वीडियो + {len(audio_formats)} ऑडियो फॉर्मेट मिले')

            return jsonify({
                'video_info': video_info,
                'video_formats': formats,
                'audio_formats': audio_formats[:4]  # टॉप 4 ऑडियो क्वालिटी
            })

    except Exception as e:
        error_msg = str(e)
        app.logger.error(f'❌ एरर: {error_msg}')
        app.logger.error(traceback.format_exc())

        # यूजर-फ्रेंडली एरर मैसेज
        if 'bot' in error_msg.lower() or 'sign in' in error_msg.lower():
            friendly_error = ('YouTube ने बॉट डिटेक्शन ट्रिगर कर दिया। '
                             'कृपया कुछ देर बाद फिर प्रयास करें या कोई दूसरा वीडियो आज़माएं।')
        elif '403' in error_msg or 'forbidden' in error_msg.lower():
            friendly_error = 'यह वीडियो डाउनलोड के लिए उपलब्ध नहीं है (403 Forbidden)।'
        elif '404' in error_msg or 'not found' in error_msg.lower():
            friendly_error = 'वीडियो नहीं मिला। कृपया URL चेक करें।'
        elif 'private' in error_msg.lower():
            friendly_error = 'यह प्राइवेट वीडियो है, डाउनलोड नहीं कर सकते।'
        else:
            friendly_error = error_msg

        return jsonify({'error': friendly_error}), 500


@app.route('/api/download', methods=['POST'])
def download():
    """वीडियो/ऑडियो डाउनलोड करें"""
    try:
        data = request.get_json(force=True, silent=True) or {}
        url = data.get('url', '').strip()
        format_id = data.get('format_id', 'best')
        download_type = data.get('type', 'video')

        if not url:
            return jsonify({'error': 'URL गायब है'}), 400

        app.logger.info(f'⬇️ डाउनलोड शुरू: type={download_type}, format={format_id}')

        unique_id = str(uuid.uuid4())
        output_template = os.path.join(DOWNLOAD_FOLDER, f'{unique_id}.%(ext)s')

        # एक्सट्रैक्टर जानें और कॉन्फिग सेट करें
        probe_opts = {'quiet': True, 'no_warnings': True}
        with yt_dlp.YoutubeDL(probe_opts) as ydl:
            info_probe = ydl.extract_info(url, download=False)
            extractor = info_probe.get('extractor', '')

        # डाउनलोड कॉन्फिग
        if download_type == 'audio':
            ydl_opts = {
                'format': format_id,
                'outtmpl': output_template,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'quiet': True,
            }
        else:
            ydl_opts = {
                'format': f'{format_id}+bestaudio/best',
                'outtmpl': output_template,
                'merge_output_format': 'mp4',
                'quiet': True,
            }

        # एक्सट्रैक्टर-वाइज़ कॉन्फिग जोड़ें
        ydl_opts.update(get_best_ydl_opts(extractor))

        # डाउनलोड करें
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_title = info.get('title', 'video')

        # डाउनलोड की गई फ़ाइल ढूंढें
        downloaded_files = []
        for f in os.listdir(DOWNLOAD_FOLDER):
            if f.startswith(unique_id):
                full_path = os.path.join(DOWNLOAD_FOLDER, f)
                if os.path.isfile(full_path):
                    downloaded_files.append(full_path)

        if not downloaded_files:
            return jsonify({'error': 'डाउनलोड की गई फ़ाइल नहीं मिली'}), 500

        # सबसे बड़ी फ़ाइल चुनें (वो असली वीडियो/ऑडियो होगी)
        downloaded_files.sort(key=os.path.getsize, reverse=True)
        filename = downloaded_files[0]

        # सेफ फ़ाइलनेम बनाएं
        safe_title = "".join(c for c in video_title if c.isalnum() or c in ' -_()[]')[:80]
        file_ext = os.path.splitext(filename)[1]
        final_name = f'{safe_title}{file_ext}'

        app.logger.info(f'✅ डाउनलोड पूरा: {final_name}')

        return send_file(
            filename,
            as_attachment=True,
            download_name=final_name
        )

    except Exception as e:
        app.logger.error(f'❌ डाउनलोड एरर: {str(e)}')
        app.logger.error(traceback.format_exc())
        return jsonify({'error': f'डाउनलोड में गड़बड़: {str(e)}'}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.logger.info(f'🚀 सर्वर पोर्ट {port} पर शुरू हो रहा है...')
    app.run(host='0.0.0.0', port=port, debug=False)
