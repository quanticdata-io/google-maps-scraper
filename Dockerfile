# Image with both engines. The Playwright base image ships Chromium and its system libraries.
#   docker build -t gmaps-places .
#   docker run --rm -e QUANTICDATA_API_KEY -v "$PWD:/out" gmaps-places search "pizza" -l "Brooklyn, NY" -o /out/pizza.csv
FROM mcr.microsoft.com/playwright/python:v1.65.2-noble

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir ".[browser]" && python -m playwright install chromium

WORKDIR /out
ENTRYPOINT ["gmaps-places"]
