FROM python:3.13-slim
WORKDIR /app
RUN pip install --no-cache-dir "gunicorn>=23,<30" && mkdir /data && chown 10001:10001 /data
COPY app.py index.html style.css ./
USER 10001:10001
CMD ["gunicorn", "--bind", "0.0.0.0:19641", "--access-logfile", "-", "app:application"]
