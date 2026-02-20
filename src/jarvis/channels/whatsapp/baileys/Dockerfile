FROM node:22-alpine

WORKDIR /app

# Install apk deps needed for some Node libraries (like node-gyp if required)
# Baileys sometimes needs Python/make for native modules, but we can try without first.
RUN apk add --no-cache git tzdata

COPY package.json package-lock.json* ./
RUN npm install --omit=dev

COPY server.js .

EXPOSE 8081

CMD ["node", "server.js"]
