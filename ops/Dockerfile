FROM python:3.12-slim-bookworm
ARG DEBIAN_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian
ARG DEBIAN_SECURITY_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian-security
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Asia/Shanghai
RUN sed -i "s|http://deb.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g; s|http://deb.debian.org/debian|${DEBIAN_MIRROR}|g" /etc/apt/sources.list.d/debian.sources \
    && printf 'Acquire::Retries "3";\nAcquire::ForceIPv4 "true";\nAcquire::http::Timeout "30";\nAcquire::https::Timeout "30";\n' > /etc/apt/apt.conf.d/99deploy \
    && apt-get update && apt-get install -y --no-install-recommends git ca-certificates tzdata default-mysql-client \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/release
COPY requirements.lock ./
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip install --no-cache-dir --timeout 30 --retries 3 --require-hashes -r requirements.lock
COPY *.whl ./
RUN pip install --no-cache-dir --no-deps ./*.whl \
    && python -m compileall -q /usr/local/lib/python3.12/site-packages/app
COPY start_backend.sh verify.py ./
RUN chmod 755 start_backend.sh
WORKDIR /data
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=4 \
  CMD python -c "import json,os,urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:'+os.getenv('UVICORN_PORT','8081')+'/actuator/health',timeout=4))['status']=='UP'"
CMD ["/opt/release/start_backend.sh"]
