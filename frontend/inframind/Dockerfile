FROM node:20-alpine

# Install Nginx and create run directories
RUN apk add --no-cache nginx && mkdir -p /run/nginx

WORKDIR /app

# Install Node dependencies
COPY package*.json ./
RUN npm install

# Copy source and explicitly force Nitro to build a standalone Node server
COPY . .
RUN NITRO_PRESET=node-server npm run build

# Copy custom Nginx config to Alpine's specific http.d directory
COPY nginx.conf /etc/nginx/http.d/default.conf

EXPOSE 80

# Start the generated Node server in the background and Nginx in the foreground
CMD ["sh", "-c", "PORT=3000 HOST=127.0.0.1 node .output/server/index.mjs & nginx -g 'daemon off;'"]