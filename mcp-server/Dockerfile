FROM node:20-alpine

# Install openssl to generate self-signed certs, and sqlite
RUN apk add --no-cache openssl sqlite

WORKDIR /app
COPY package*.json ./
RUN npm install

# Generate self-signed TLS certificate
RUN openssl req -nodes -new -x509 -keyout key.pem -out cert.pem -days 365 \
    -subj "/C=US/ST=State/L=City/O=Organization/CN=mcp-server"

COPY server.js .

# Create a dummy SQLite database with a table and 10,000 random rows for realistic query payloads
RUN sqlite3 dummy.db "CREATE TABLE logs (id INTEGER PRIMARY KEY, message TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP);" && \
    awk 'BEGIN{for(i=1;i<=10000;i++) print "INSERT INTO logs (message) VALUES ('random log data " i " padding to increase payload size');"}' | sqlite3 dummy.db

EXPOSE 8443
CMD ["node", "server.js"]