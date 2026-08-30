FROM python:3.11-slim

# tesseract-ocr: pytesseract fallback in app/services/extraction.py
# poppler-utils: PDF raster helpers if needed alongside pdfplumber
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run injects PORT (default 8080)
ENV PORT=8080
ENV COOKIE_SECURE=true
EXPOSE 8080

CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
