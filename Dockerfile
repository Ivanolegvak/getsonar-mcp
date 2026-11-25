FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app/src

# Default: stdio, the transport every directory and local client uses
# (`docker run -i --rm -e SONAR_API_KEY=... <image>`). Since 0.3.3 the image
# no longer starts the HTTP transport on 0.0.0.0 without auth: anyone who
# reached the port could spend the SONAR_API_KEY balance.
#
# HTTP (self-hosted, single user): inside a container the server must bind
# 0.0.0.0, so it needs the explicit opt-in and a bearer token, and the port
# should be published on loopback only:
#   docker run --rm -p 127.0.0.1:8080:8080 \
#     -e SONAR_API_KEY=... -e SONAR_MCP_HTTP_TOKEN=<32+ random chars> \
#     -e MCP_HOST=0.0.0.0 -e SONAR_MCP_ALLOW_REMOTE=1 \
#     <image> python -m getsonar_mcp.http_server
EXPOSE 8080

CMD ["python", "-m", "getsonar_mcp"]
