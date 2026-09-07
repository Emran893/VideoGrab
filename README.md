# 🎬 VideoGrab - वीडियो डाउनलोडर v3

**सबसे नया अपडेटेड वर्जन** - ffmpeg इनबिल्ट, YouTube बॉट फिक्स, बिना वॉटरमार्क

## ✨ विशेषताएं
- ✅ **ffmpeg इनबिल्ट** - `imageio-ffmpeg` के जरिए स्वतः इंस्टॉल
- ✅ **YouTube बॉट डिटेक्शन फिक्स** - Android VR क्लाइंट
- ✅ **बिना वॉटरमार्क** - TikTok, Instagram आदि के लिए
- ✅ **सभी क्वालिटी** - 144p से 4K तक
- ✅ **MP3 ऑडियो** - अलग से ऑडियो डाउनलोड
- ✅ **1000+ साइटें** - yt-dlp के जरिए
- ✅ **आधुनिक UI** - Tailwind CSS से बना

## 🚀 Railway.app पर डिप्लॉय (सबसे अच्छा)

### GitHub पर अपलोड करें:
सभी फ़ाइलें सीधे रिपॉजिटरी के **रुट (मुख्य फोल्डर)** में अपलोड करें:
```
आपकी_रिपॉजिटरी/
├── app.py
├── requirements.txt
├── vercel.json
├── render.yaml
├── README.md
└── templates/
    └── index.html
```

### Railway सेटिंग्स:
| सेटिंग | वैल्यू |
|--------|--------|
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `gunicorn --bind 0.0.0.0:8080 app:app` |
| **Variables** | `PORT` = `8080` |

## 🚀 Render.com पर डिप्लॉय
| सेटिंग | वैल्यू |
|--------|--------|
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `gunicorn --bind 0.0.0.0:10000 app:app` |
| **Variables** | `PORT` = `10000` |

## 🚀 Vercel पर डिप्लॉय
- GitHub से इम्पोर्ट करें, `vercel.json` पहले से कॉन्फिगर्ड है
- Variable: `PORT` = `3000`

## 💻 लोकली चलाने के लिए
```bash
pip install -r requirements.txt
python app.py
```
फिर ब्राउज़र में: `http://localhost:8080`

## ⚠️ महत्वपूर्ण नोट
- YouTube कभी-कभी क्लाउड सर्वर IP ब्लॉक कर सकता है
- अगर "Sign in to confirm you're not a bot" आए तो कुछ देर बाद फिर प्रयास करें
- या Railway के अलग रीजन से डिप्लॉय करें

## 📜 कानूनी नोट
केवल वे वीडियो डाउनलोड करें जिनके आप मालिक हैं या अनुमति है। कॉपीराइट सामग्री अवैध है।
