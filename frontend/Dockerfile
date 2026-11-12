FROM node:20-alpine AS build
WORKDIR /app

# 用国内镜像加速 npm 安装
COPY package*.json ./
RUN npm install --registry https://registry.npmmirror.com

COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
