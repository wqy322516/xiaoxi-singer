# 发布到 GitHub

仓库本身已经就绪：`git status` 干净、7 个提交、`main` 分支、`.gitignore` 排除了模型权重。
**唯一卡住的是「建账号」这一步** —— GitHub 的注册页 `/signup` 在我们的出口 IP 上返回 403
（DataDome 风控），而这台机器的宽带 IP 和现有代理节点都被判定为高风险。登录页、API、
`git clone/push`、Release 下载全部正常，只有注册被单独拦。

## 一、注册（约 2 分钟）

1. 手机关掉 Wi-Fi，用 **4G/5G 流量**；
2. 手机浏览器打开 `github.com`，右上角把语言切成 **English**；
3. 用邮箱注册（Hotmail/Outlook/Gmail 都行），用户名建议 `xiaoxi-singer` 相关；
4. 收到邮件点验证；如果提示开 2FA，用手机自带的验证器 App 扫码。

> 为什么必须你来：注册需要收邮箱验证码、过人机验证，这两步没法由程序代做
> （自动注册也违反 GitHub 的服务条款）。

## 二、拿 token

电脑上登录 `github.com` → 右上头像 → **Settings** → 左下 **Developer settings** →
**Personal access tokens** → **Tokens (classic)** → **Generate new token (classic)**：

- Note: `xiaoxi-singer-publish`
- Expiration: 30 days（够用，之后可删）
- Scopes: ✅ `repo` ✅ `workflow`

生成后复制那串 `ghp_...`（只显示一次）。

## 三、发布（一条命令）

在仓库目录执行：

```bash
cd D:/UserProfile/wqy32/dsh/home/work/xiaoxi-singer
GITHUB_USER=<你的用户名> GITHUB_TOKEN=<ghp_...> bash scripts/publish.sh
```

脚本会：检查仓库是否存在 → 不存在就创建 → push `main` → 把 remote 改回不含 token 的地址。
输出最后一行就是仓库地址。之后打 tag：

```bash
git tag v0.1.0 && git push origin v0.1.0
```

`scripts/publish.sh` 已经用本地裸仓库演练过推送（`git push` 成功），只差一个真实远端。

## 四、验证

```bash
curl -s https://api.github.com/repos/<用户名>/xiaoxi-singer | grep -E '"(full_name|html_url|default_branch)"'
```

能返回仓库信息就说明公开可访问了。

## 五、备选：Gitee（国内，不用翻墙）

如果 GitHub 注册始终过不去，可以先发 Gitee：

1. 手机号注册 `gitee.com`；
2. 头像 → 设置 → **私人令牌** → 生成（勾 `projects`）；
3. 建一个空仓库 `xiaoxi-singer`；
4. 推：

```bash
git remote add gitee https://<用户名>:<token>@gitee.com/<用户名>/xiaoxi-singer.git
git push -u gitee main
```

Gitee 仓库可以之后「导入」到 GitHub，不用重来。

## 六、常见问题

| 现象 | 原因 / 处理 |
| --- | --- |
| 注册页「访问暂时受限」 | 出口 IP 被 DataDome 标高风险；换手机流量 / 住宅 IP 节点 / 别的 Wi-Fi |
| push 报 403 | token 没勾 `repo`，或过期；重新生成 |
| push 报 `Repository not found` | 用户名拼错，或 token 属于另一个账号 |
| 想撤销 token | Settings → Developer settings → 删除该 token |
