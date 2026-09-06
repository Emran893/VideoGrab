from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp
import os
import tempfile
import uuid

app = Flask(__name__)

# टेम्परेरी डाउनलोड फोल्डर
DOWNLOAD_FOLDER = tempfile.mkdtemp()

def get_best_ydl_opts(extractor='generic'):
    """वॉटरमार्क-फ्री डाउनलोड के लिए बेस्ट कॉन्फिग"""
    base_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }
    
    if 'tiktok' in extractor.lower():
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
    elif 'instagram' in extractor.lower():
        base_opts.update({
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
            }
        })
    
    return base_opts

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/get-formats', methods=['POST'])
def get_formats():
    """URL से उपलब्ध सभी क्वालिटी निकालें"""
    data = request.json
    url = data.get('url', '').strip()
    
    if not url:
        return jsonify({'error': 'कृपया URL डालें'}), 400
    
    try:
        # पहले एक्सट्रैक्टर का नाम जानें
        probe_opts = {'quiet': True, 'no_warnings': True}
        with yt_dlp.YoutubeDL(probe_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            extractor = info.get('extractor', 'generic')
        
        # वॉटरमार्क-फ्री कॉन्फिग के साथ फिर से एक्सट्रैक्ट करें
        opts = get_best_ydl_opts(extractor)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            video_info = {
                'title': info.get('title', 'Unknown'),
                'thumbnail': info.get('thumbnail', ''),
                'duration': info.get('duration', 0),
                'extractor': extractor,
            }
            
            formats = []
            seen_resolutions = set()
            
            # वीडियो फॉर्मेट
            for f in info.get('formats', []):
                height = f.get('height')
                if height and height not in seen_resolutions:
                    filesize = f.get('filesize') or f.get('filesize_approx') or 0
                    formats.append({
                        'format_id': f['format_id'],
                        'resolution': f'{height}p',
                        'height': height,
                        'ext': f.get('ext', 'mp4'),
                        'filesize_mb': round(filesize / (1024 * 1024), 1) if filesize else 'N/A',
                        'fps': f.get('fps', 30),
                        'type': 'video'
                    })
                    seen_resolutions.add(height)
            
            # ऑडियो-ओनली फॉर्मेट
            audio_formats = []
            for f in info.get('formats', []):
                if f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                    abr = f.get('abr', 0)
                    if abr and abr not in [a.get('abr') for a in audio_formats]:
                        audio_formats.append({
                            'format_id': f['format_id'],
                            'abr': abr,
                            'ext': f.get('ext', 'm4a'),
                            'filesize_mb': round((f.get('filesize') or 0) / (1024 * 1024), 1),
                            'type': 'audio'
                        })
            
            formats.sort(key=lambda x: x.get('height', 0), reverse=True)
            audio_formats.sort(key=lambda x: x.get('abr', 0), reverse=True)
            
            return jsonify({
                'video_info': video_info,
                'video_formats': formats,
                'audio_formats': audio_formats[:3]
            })
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/download', methods=['POST'])
def download():
    """वीडियो डाउनलोड करें और फ़ाइल भेजें"""
    data = request.json
    url = data.get('url', '').strip()
    format_id = data.get('format_id', 'best')
    download_type = data.get('type', 'video')
    
    if not url:
        return jsonify({'error': 'URL गायब है'}), 400
    
    try:
        unique_id = str(uuid.uuid4())
        output_path = os.path.join(DOWNLOAD_FOLDER, f'{unique_id}.%(ext)s')
        
        if download_type == 'audio':
            ydl_opts = {
                'format': format_id,
                'outtmpl': output_path,
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
                'outtmpl': output_path,
                'merge_output_format': 'mp4',
                'quiet': True,
            }
        
        # एक्सट्रैक्टर के अनुसार वॉटरमार्क-फ्री कॉन्फिग
        probe_opts = {'quiet': True}
        with yt_dlp.YoutubeDL(probe_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            extractor = info.get('extractor', '')
        
        if 'tiktok' in extractor.lower():
            ydl_opts.update(get_best_ydl_opts('tiktok'))
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            # अगर MP3 में कनवर्ट हुआ हो तो एक्सटेंशन बदलें
            if download_type == 'audio':
                filename = os.path.splitext(filename)[0] + '.mp3'
            
            if not os.path.exists(filename):
                # अन्य एक्सटेंशन चेक करें
                base = os.path.splitext(filename)[0]
                for ext in ['.mp4', '.mkv', '.webm', '.mp3', '.m4a']:
                    if os.path.exists(base + ext):
                        filename = base + ext
                        break
            
            safe_title = "".join(c for c in info.get('title', 'video') if c.isalnum() or c in ' -_')
            ext = os.path.splitext(filename)[1]
            
            return send_file(
                filename,
                as_attachment=True,
                download_name=f'{safe_title}{ext}'
            )
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
