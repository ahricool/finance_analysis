# 用户头像

头像独立保存到 PostgreSQL `user_avatar` 表：`user_id` 为关联 `users.id` 的主键/外键，
`data` 为 BYTEA，另有随机 `version` 与 UTC `updated_at`。用户删除时级联删除头像。
`users.avatar_url` 只保留图片 URL；普通用户查询不会 join 或读取头像二进制。

## API 与处理

- `POST /api/v1/auth/avatar`：复用 multipart `file`，仅当前登录用户可上传。
- `GET /api/v1/auth/avatar/{uid}.webp`：仅本人可读，直接返回 `image/webp` 二进制。
- `DELETE /api/v1/auth/avatar`：幂等删除本人的头像，同时清空 URL，返回与上传一致的 `{ok, user}`。
- 旧 `{uid}.jpg` 路径仅作为兼容路由，读取数据库并返回 `image/webp`，不读取本地文件。

文件最大 5 MiB（5 × 1024 × 1024 字节）；仅接受 JPEG、PNG、静态 WebP，并核对 MIME 与实际格式。
验证文件完整性后，按 EXIF 修正朝向，居中裁剪/缩放为 256×256，以 WebP quality=82 编码，
保留透明度并去除原图元数据。超过 1600 万像素、动画、伪造或损坏图片均拒绝。
格式/内容错误返回 400，文件超限返回 413，存储异常返回 500 且不暴露内部异常信息。
新图和 URL 在同一事务中写入；上传/删除持有用户行锁以避免初次上传及并发操作冲突。
其他媒体存储逻辑不变。现有前端选择、裁剪界面保持不变，源文件与裁剪结果均校验 5 MiB 上限。

每次成功上传生成新的 `?v=` URL。前端沿用上传后刷新用户资料的行为，使个人中心与顶栏同步。
读取返回 `Cache-Control: private, no-cache`、ETag 和 `Vary: Cookie`：浏览器可存储图片，
再次读取时鉴权并条件校验，未变更返回 304。删除后返回 404/no-store。
不使用 Base64，也不添加 UI 删除按钮；前端 API 已提供删除方法。
nginx 只为头像上传路径放宽到 6 MiB 请求体（含 multipart 开销）；API 仍校验 5 MiB 文件上限。

## 升级

迁移 `0071_user_avatar` 创建新表，并导入当前 `DATA_DIR/uploads/avatars/{uid}.jpg` 中
由现有用户头像 URL 引用的有效文件。迁移不删除旧文件。

部署迁移时需要挂载原数据目录。缺失或无效的旧图会记录 `Legacy avatar unavailable`，
保留旧 URL 以便恢复，但在成功导入前 API 无法提供其图片。
恢复原数据目录后可幂等补导入：

```bash
uv run python scripts/import_legacy_avatars.py
```

补导入只处理旧 JPG URL，不覆盖已上传的新头像。回滚会删除头像表并清空新的 WebP URL；
仅存在数据库中的新头像不会还原成文件，回滚前应备份数据库。

验证：`uv run pytest tests/test_auth_api.py tests/test_user_avatar.py -q`。
迁移及仓储测试使用独立临时 SQLite 数据库，另断言 SQLAlchemy 在 PostgreSQL 上编译为 BYTEA。
