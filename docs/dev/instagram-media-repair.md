# Instagram 指定帖子补图

适用于已存在、未归档且归属明确的 Instagram 文章。它不是免费来源批量 `content_repair`，不会启动 Actor、创建费用预留、调用 AI、通知、创建文章或 Feed 快照、推进来源水位。图片仍通过当前用户权限隔离的 `/api/media/…` 展示。

## 先预览，再明确执行

在当前 checkout 使用其 Python 环境；数据目录必须包含既有 `service.db`，不会初始化或迁移数据库。每次只指定一个 workspace、user、source、article，不支持通配或全量补图。

```sh
.venv/bin/python scripts/repair_instagram_media.py \
  --data-dir /absolute/path/to/data \
  --workspace-id WORKSPACE_ID --user-id USER_ID \
  --source-id SOURCE_ID --article-id ARTICLE_ID
```

预览返回安全原因、可用图片数量、已知总数和 `preview` 摘要，不下载图片、不写文章，也不输出远程地址或原始 Dataset 行。确认预览中的具体文章后，再执行同一命令并增加：

```sh
--apply --expected-preview PREVIEW_DIGEST
```

执行会重新生成预览并验证摘要；原始图片地址、来源绑定、文章版本或候选证据改变时拒绝覆盖。此时重新预览，不复用旧摘要。成功返回 `succeeded`，部分下载失败返回 `partial`，没有可确认媒体返回 `skipped`。部分失败可再次预览并重试；正文、分析和用户状态保持不变，历史快照不可变。SQLite 事务失败时删除本次新增孤立文件。

## 数据来源和边界

优先使用该用户文章已保存的远程图片地址（包括其私有媒体资产记录），否则检查同来源、同绑定版本和目标指纹的最近 5 个成功、已验证且费用最终结算的 Fetch Attempt。只读取与原 Run 和原凭据版本精确关联的既有 Dataset；每次 GET 最多 100 行、8 MiB，不追随重定向。帖子必须再次通过冻结 Manifest 的身份、URL、时间和正文校验，且与指定文章唯一匹配。不得自动重新付费抓取。

单图、图集与视频封面共用缓存；最多 6 张，视频本体不下载。受限媒体扫描最多检查 100 个子项/尺寸候选，越界尾部不虚构数量。图集优先子项，父封面不重复插入；不扫描头像、评论或推荐内容。保存地址失效时显示未缓存数量；没有地址且 Dataset 不可用时，无法凭空恢复图片。

常见安全原因：`instagram_dataset_unavailable`（既有 Dataset 请求失败）、`instagram_dataset_credential_missing`（原凭据不可用）、`instagram_dataset_identity_unproven`（Run/来源/帖子归属无法确认）、`instagram_dataset_request_changed`（冻结请求不匹配）、`instagram_media_missing`（无支持的图片）、`instagram_media_preview_changed`（预览过期）。

本次验证中，两个既有成功 Dataset 的有界只读请求不可用，因此真实上游字段尚未确认；固定样例用于验证已列出的别名，不宣称历史 Dataset 必含图片。新别名需补充 Schema 或脱敏结构证据后再扩展。Instagram 抓取启动失败是独立问题。
