#!/bin/bash

# Array of targets mixing different types of HTTPS traffic
URLS=(
    "https://api.github.com/events"                       # Small/Medium JSON API
    "https://hacker-news.firebaseio.com/v0/topstories.json" # Small JSON API
    "https://en.wikipedia.org/wiki/Special:Random"        # Variable HTML Web Browsing
    "https://proof.ovh.net/files/10Mb.dat"                # 10MB Bulk Download
    "https://ash-speed.hetzner.com/100MB.bin"                  # 100MB Bulk Download
)

echo "Starting HTTPS background noise generator..."

while true; do
    # Pick a random target
    RANDOM_INDEX=$((RANDOM % ${#URLS[@]}))
    TARGET=${URLS[$RANDOM_INDEX]}
    
    echo "Noise: Fetching $TARGET"
    
    # curl the target silently, follow redirects, and dump the payload to /dev/null
    # We only care about generating the network packets, not saving the data
    curl -s -L -o /dev/null "$TARGET"
    
    # Sleep for a random interval (1 to 6 seconds) to mimic organic background tasks
    SLEEP_TIME=$(( (RANDOM % 6) + 1 ))
    echo "Noise: Sleeping for $SLEEP_TIME seconds..."
    sleep $SLEEP_TIME
done