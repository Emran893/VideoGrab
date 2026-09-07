# =============================================
# VideoGrab Dockerfile v2
# ffmpeg के साथ - 100% गारंटी
# =============================================

FROM python:3.11-slim

LABEL maintainer="VideoGrab"
LABEL description="वीडियो डाउनलोडर - ffmpeg के साथ"

# Step 1: सिस्टम अपडेट और ffmpeg इंस्टॉल करें
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg build-essential && \
    # ✅ Verify कि ffmpeg सही से इंस्टॉल हुआ है
    ffmpeg -version && \
    which ffmpeg && \
    # साफ़ करें ताकि इमेज हल्की रहे
    rm -rf /var/lib/apt/lists/*

# कार्यशील डायरेक्टरी
WORKDIR /app

# Python डिपेंडेंसी
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    # ✅ imageio-ffmpeg भी verify करें
    python -c "import imageio_ffmpeg; print('imageio-ffmpeg:', imageio_ffmpeg.get_ffmpeg_exe())"

# बाकी कोड
COPY . .

# पोर्ट
EXPOSE 8080

# हेल्थ चेक
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/health')" || exit 1

# सर्वर चलाएं
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "120", "app:app"]
