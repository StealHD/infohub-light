# Inteliscope Nginx Basic Auth 发布配置

适合已有 Nginx 的服务器：Nginx 对公网提供 80/443，反代到本机 `127.0.0.1:8080`，整站用 Basic Auth 保护。

## 1. 确认 Docker 只监听本机

`.env` 建议保持：

```bash
HORIZON_WEB_BIND=127.0.0.1
HORIZON_WEB_PORT=8080
```

然后重启：

```bash
./scripts/up-latest.sh
docker compose ps
```

这样公网不能绕过 Nginx 直接访问 `:8080`。

## 2. 生成 Basic Auth 密码文件

使用 `openssl` 生成 Apache MD5 格式密码：

```bash
USER_NAME=friend
sudo sh -c 'printf "%s:%s\n" "$1" "$(openssl passwd -apr1)" >> /etc/nginx/.htpasswd_inteliscope' sh "$USER_NAME"
sudo chmod 640 /etc/nginx/.htpasswd_inteliscope
```

命令会提示输入密码。需要多个朋友共用账号时，只生成一个账号即可；需要多个账号就重复执行并换用户名。

如果服务器有 `htpasswd`：

```bash
sudo htpasswd -c /etc/nginx/.htpasswd_inteliscope friend
sudo htpasswd /etc/nginx/.htpasswd_inteliscope another_friend
```

## 3. 启用 Nginx 站点

复制模板：

```bash
sudo cp deploy/nginx/inteliscope-basic-auth.conf /etc/nginx/sites-available/inteliscope
sudo ln -sf /etc/nginx/sites-available/inteliscope /etc/nginx/sites-enabled/inteliscope
```

编辑域名：

```bash
sudo nano /etc/nginx/sites-available/inteliscope
```

把 `radar.example.com` 改成你的域名。如果已有 HTTPS 证书，启用模板里的 443 server block，并改证书路径。

检查并重载：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 4. 验证

本机应能访问后端：

```bash
curl -I http://127.0.0.1:8080
```

公网域名未带账号密码应返回 `401`：

```bash
curl -I http://你的域名
```

带账号密码应返回 `200`：

```bash
curl -I -u friend:你的密码 http://你的域名
```

## 注意

- Basic Auth 会保护整站，包括信息流和配置页。
- 账号密码会被浏览器缓存；朋友退出通常需要关闭浏览器或访问无效账号覆盖缓存。
- 强烈建议配合 HTTPS 使用，否则 Basic Auth 密码会以可被中间人解码的形式传输。
- 如果你同时开启应用内鉴权，访问站点会先过 Nginx Basic Auth，再过应用后台登录；只想省事可以关闭应用内鉴权，只保留 Nginx。
