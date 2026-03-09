FROM python:3.11-slim

# Install socat to act as our local TLS proxy
RUN apt-get update && apt-get install -y socat && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY client.py .
COPY run.sh .
RUN chmod +x run.sh

# Run the proxy and the client together
CMD ["./run.sh"]