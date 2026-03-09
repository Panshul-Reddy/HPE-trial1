FROM alpine:latest

# Install curl and bash
RUN apk add --no-cache curl bash

WORKDIR /app
COPY noise.sh .
RUN chmod +x noise.sh

CMD ["./noise.sh"]