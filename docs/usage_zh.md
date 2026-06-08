# Inteliscope 使用说明

这份说明面向日常使用和小范围分享。当前部署入口为：

- 公网入口：`https://www.stealhd.xyz/`
- 服务器目录：`/opt/inteliscope`
- Docker Web 端口：`127.0.0.1:8080`

## 1. 登录访问

如果 Nginx 已开启 Basic Auth，首次访问会弹出浏览器原生登录框。

- 用户名和密码由管理员单独提供。
- 这个密码是站点访问密码，不是 AI API Key。
- 浏览器会缓存 Basic Auth 登录状态；要退出通常需要关闭浏览器，或清理站点登录缓存。

注意：如果只启用 Nginx Basic Auth，拿到站点密码的人可以访问整个 Inteliscope，包括「配置」页。需要区分只读用户和管理员时，再启用应用内后台鉴权。

## 2. 信息流页面

顶部标签用于切换阅读视图：

- `精选`：今天达到精选阈值的内容，适合默认扫读。
- `个人关注`：带个人标签的内容，不一定参与 AI 行业评分。
- `全部`：今天进入信息流的所有内容。
- `稍后读`：本机浏览器保存的待读列表，只存在当前浏览器 localStorage。
- `历史`：昨天及更早的归档内容，今天内容不会立刻进入历史。
- `日报`：达到每日推送阈值的内容。
- `配置`：维护信源、标签、AI 模型、阈值和推送设置。

左侧筛选支持：

- 关键词搜索：匹配标题、摘要、理由、标签。
- 最低分：按 AI 分数过滤。
- 标签：包含 AI 固定大类和个人标签。
- 来源：按具体信源过滤。
- 只看收藏：只显示本机收藏内容。

条目按钮：

- `打开原文`：跳到原始链接。
- `站内预览`：在当前页面预览原文。
- `加入收藏`：保存到当前浏览器 localStorage。
- `稍后读`：保存到当前浏览器 localStorage。
- `复制摘要`：复制当前条目的中文摘要和判断。
- 右下角 `关联分析`：读取预生成的 `article-graph.json`，展示高分文章之间的主题、实体、时间线或同事件关系；点击按钮不会实时调用 AI。

## 3. 今日与历史规则

Inteliscope 使用两个数据层：

- `data/site/today-data.json`：今天累计抓到的内容。
- `data/site/history-data.json`：历史归档内容。

规则：

- 今天抓到的内容保留在今日文件里。
- 到第二天再把前一天今日内容归档到历史。
- 首页显示“今日 N 条 / 历史 M 条”。
- 历史页只用于回看过去日期，不混入当天内容。

## 4. 配置页面

配置页用于维护项目行为，不建议随便改。

常用区域：

- AI 模型：配置 provider、model、base URL、API Key 环境变量名。
- AI 固定大类：用于评分 Prompt 和精选逻辑，建议保持稳定。
- 个人标签：自由添加个人偏好标签，只用于关注和筛选。
- 评分阈值：控制精选、每日推送和首页最低分。
- 信源配置：新增 RSS、GitHub、Reddit、Telegram、Apify 社交订阅等。
- Webhook：配置每日推送目标。

保存规则：

- 页面只保存配置结构，不保存真实密钥。
- 真实密钥放在 `.env`。
- 后台会校验 URL、标签、环境变量名和订阅类型。
- 保存失败时页面会返回原因。

## 5. Apify 社交订阅

当前 Apify 用于抓公开社交平台内容，例如：

- X 公开账号或关键词。
- Instagram 公开主页或 hashtag。
- Facebook 公开 Page、公开 Group、公开帖子 URL。
- Telegram 公开频道。

限制：

- 不抓私密频道、私密群组、好友流。
- 不使用 cookie、账号密码或 session。
- Apify 会消耗额度，测试订阅也会消耗少量额度。

如果额度紧张：

- 只保留必要订阅。
- 把个人兴趣类内容设置为 `个人关注（跳过 AI）`。
- 降低每个订阅的抓取数量。

## 6. AI 模型用途

AI Key 主要用于：

- 给内容打 0-10 分。
- 生成中文摘要。
- 生成推荐理由。
- 生成“我该关注什么”。
- 归类到固定大类。
- 判断是否进入精选和每日推送。

个人标签不会进入行业评分 Prompt；它只表达个人偏好和筛选需求。

## 7. 文章关联分析

关联分析默认关闭，适合管理员确认成本后再开启。

开启后系统会：

- 把分析后的轻量文章索引写入 `data/horizon.db`。
- 默认只处理高分精品文章。
- 可选抓取少量原文全文，失败只记日志，不影响信息流。
- 基于标题、摘要、标签、实体和发布时间生成关系边。
- 输出 `data/site/article-graph.json` 给右下角按钮读取。

最小配置：

```json
{
  "premium_analysis": {
    "enabled": true,
    "full_fetch_score_threshold": 8.5,
    "max_full_fetch_per_run": 10
  },
  "article_graph": {
    "enabled": true,
    "premium_score_threshold": 8.5,
    "relation_top_k": 3,
    "min_relation_score": 0.55
  }
}
```

第一版不做 embedding、不做实时模型分析、不做大图谱，只服务右下角的决策面板。

## 8. 每日推送

默认规则：

- 时区：`Asia/Shanghai`
- 每天 `08:30` 生成每日推送。
- 分数高于每日推送阈值的内容进入推送。
- 增量轮询期间只更新 Web 页面，不重复发每日推送。

手动测试：

```bash
cd /opt/inteliscope
docker compose run --rm horizon --hours 24
```

查看日志：

```bash
cd /opt/inteliscope
docker compose logs -f horizon-scheduler
```

## 9. 管理员运维

进入服务器：

```bash
ssh vps-tokyo
cd /opt/inteliscope
```

查看服务：

```bash
docker compose ps
```

查看日志：

```bash
docker compose logs -f horizon-web horizon-scheduler
```

重新部署最新版：

```bash
./scripts/up-latest.sh
```

检查本机反代目标：

```bash
curl -I http://127.0.0.1:8080/
```

## 10. Nginx 项目密码

只给 Inteliscope 这个项目加密码时，把 Basic Auth 放到反代 `127.0.0.1:8080` 的 `location /` 中。

核心配置：

```nginx
location / {
    auth_basic "Inteliscope";
    auth_basic_user_file /etc/nginx/.htpasswd_inteliscope;

    proxy_pass http://127.0.0.1:8080;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;
}
```

生成密码文件：

```bash
sudo apt install -y apache2-utils
sudo htpasswd -c /etc/nginx/.htpasswd_inteliscope friend
sudo nginx -t
sudo systemctl reload nginx
```

验证：

```bash
curl -I https://www.stealhd.xyz/
curl -I -u friend:你的密码 https://www.stealhd.xyz/
```

预期：

- 不带账号密码返回 `401`。
- 带账号密码返回 `200`。

## 11. 常见问题

页面看不到内容：

- 点右上角清除筛选按钮。
- 检查最低分是否过高。
- 切到 `全部` 或 `历史` 视图。
- 查看 `docker compose logs -f horizon-scheduler`。

配置保存失败：

- 检查 URL 格式。
- 检查标签是否在固定大类或个人标签库中。
- 检查 `.env` 是否有对应环境变量。

社交源抓不到：

- 确认目标是公开内容。
- 确认 `APIFY_TOKEN` 已设置。
- 降低抓取数量后再测试。

AI 摘要没有生成：

- 确认模型 API Key 已设置。
- 检查 `ai.provider`、`ai.model`、`ai.base_url` 是否匹配。
- 查看 scheduler 日志中的模型请求错误。
