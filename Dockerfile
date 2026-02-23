FROM python:3.9-slim
WORKDIR /app

# Install FFmpeg untuk potong video
RUN apt-get update && apt-get install -y ffmpeg

# Install modul Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy semua file proyek ke server
COPY . .

# Buka port dan jalankan
EXPOSE 7860
CMD ["python", "main.py"]