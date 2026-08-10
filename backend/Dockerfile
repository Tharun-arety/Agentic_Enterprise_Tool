FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --create-home --uid 10001 magnotherm
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/var && chown -R magnotherm:magnotherm /app
USER magnotherm
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=3)"
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--proxy-headers"]
