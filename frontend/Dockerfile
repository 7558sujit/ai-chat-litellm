FROM node:20-alpine AS build
ARG API_URL=http://localhost:8000
ENV API_URL=$API_URL
WORKDIR /app
COPY package.json build.js index.html ./
RUN node build.js

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
