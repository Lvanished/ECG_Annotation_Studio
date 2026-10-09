FROM node:22-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
ENV API_PROXY_TARGET=http://backend:8000
CMD ["npm","run","dev"]
