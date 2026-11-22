FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends nodejs chromium fonts-noto-cjk && rm -rf /var/lib/apt/lists/*
COPY requirements.lock /tmp/requirements.lock
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir -r /tmp/requirements.lock
ARG APT_MIRROR=deb.debian.org
RUN sed -i "s@http://deb.debian.org@https://${APT_MIRROR}@g" /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends poppler-utils git ripgrep curl \
    && rm -rf /var/lib/apt/lists/*
ENV HOME=/tmp PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/tmp/matplotlib
WORKDIR /workspace
USER 65534:65534
CMD ["python", "--version"]
