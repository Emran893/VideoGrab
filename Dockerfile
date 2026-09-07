# =============================================
# VideoGrab Dockerfile
# Railway/Vercel/Render सभी पर काम करेगा
# =============================================

# आधार इमेज - Python 3.11 slim (हल्का और स्थिर)
FROM python:3.11-slim

# लेबल
LABEL maintainer="VideoGrab"
LABEL description="वीडियो डाउनलोडर - ffmpeg के साथ"

# सिस्टम डिपेंडेंसी इंस्टॉल करें
# ffmpeg वीडियो merge करने के लिए ज़रूरी है
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# कार्यशील डायरेक्टरी सेट करें
WORKDIR /app

# Python डिपेंडेंसी पहले इंस्टॉल करें (कैश के लिए)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# बाकी कोड कॉपी करें
COPY . .

# पोर्ट एक्सपोज़ करें
EXPOSE 8080

# हेल्थ चेक (वैकल्पिक)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/health')" || exit 1

# सर्वर चलाने का कमांड
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "120", "app:app"]
