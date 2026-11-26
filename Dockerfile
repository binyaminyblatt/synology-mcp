FROM python:3.12-slim

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -e .

EXPOSE 8765

# Defaults to stdio unless MCP_HTTP=true or --http is passed
CMD ["python", "-m", "synology_mcp"]
