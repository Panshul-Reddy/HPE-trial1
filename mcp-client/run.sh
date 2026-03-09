#!/bin/bash

# Start a local socat proxy that listens on port 8080 (plaintext)
# and forwards all traffic to the mcp-server on port 8443 (TLS)
# verify=0 disables the strict certificate checking
socat TCP-LISTEN:8080,fork,reuseaddr openssl:mcp-server:8443,verify=0 &

# Give the proxy a second to start
sleep 2

# Run the Python client
python client.py