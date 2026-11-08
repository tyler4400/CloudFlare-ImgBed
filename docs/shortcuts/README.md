# macOS 快捷指令：从 Finder 上传到 CloudFlare ImgBed

这是一份社区教程：用 macOS 自带的 **Shortcuts（快捷指令）** 调用一个 Python 脚本，选中文件后即可上传，返回的链接自动进入剪贴板。无需安装大型图床客户端，也没有第三方 Python 依赖。上传是主要用途；浏览最近文件、下载和随机图是可选扩展。

同一条快捷指令可以放进 Finder 的 **Quick Actions（快速操作）**、菜单栏，或绑定快捷键；也可以直接在终端、自己的 shell 脚本中调用。本文提供配置步骤和 [upload.py](upload.py)，不提供预制 `.shortcut` 文件。

## 准备条件

- 一台带 Shortcuts 的 Mac（macOS 12 或更新版本），以及可以运行的 `python3`。不要假设 macOS 一定预装了可用的 Python；先运行 `python3 --version`。
- 已部署并配置好可用上传渠道的 CloudFlare ImgBed，具有 HTTPS 地址，可以登录管理界面。部署步骤见[官方文档](https://cfbed.sanyue.de/)。
- 脚本使用系统自带的 `/usr/bin/curl`、`security`、`osascript`、`pbcopy` 和 AppKit。无需 `pip install`。

本文于 **2026-11-08** 核对官方文档及本仓库提交 `85636c5bc7393e80e0fe229a8f73538ad5c65ee4` 的源码。验证环境为 Linux；**未实际测试 macOS UI、钥匙串授权弹窗、JXA 图片转换或真实上传/下载**。不同 macOS 和 ImgBed 版本的界面名称可能不同，文末列出了已知差异。

## 1. 创建最小权限 API Token

登录图床管理界面，进入 **系统设置 → 安全设置 → API Token 管理**。点击该标题旁的 **＋**，填写便于识别的名称，选择所需权限及有效期，再创建并保存完整 Token。路径和完整 Token 仅在创建时展示的行为见[官方 API 介绍](https://cfbed.sanyue.de/api/)；本仓库的[安全设置界面源码映射](https://github.com/MarSeventh/CloudFlare-ImgBed/blob/85636c5bc7393e80e0fe229a8f73538ad5c65ee4/frontend-dist/js/77.299b40eb.js.map)也确认了加号入口和四个权限选项。

| 使用方式 | Token 精确权限值 |
| --- | --- |
| 只上传文件、文件夹或剪贴板图片 | `upload` |
| 上传并使用最近文件列表 | `upload`、`list` |
| 单独使用最近文件列表 | `list` |
| 使用 `check` 进行只读鉴权检查 | `list`；不能验证 `upload` 权限 |
| 单独使用随机图 | 无需 Token；管理员需要先开启随机图功能 |

本教程不需要 `delete` 或 `manage`。`manage` 用于 Token 管理和其他管理接口，不是上述权限的替代品；校验器逐项检查所需权限。已核对[管理接口权限分派](https://github.com/MarSeventh/CloudFlare-ImgBed/blob/85636c5bc7393e80e0fe229a8f73538ad5c65ee4/functions/api/manage/_middleware.js)、[Token 权限与过期校验](https://github.com/MarSeventh/CloudFlare-ImgBed/blob/85636c5bc7393e80e0fe229a8f73538ad5c65ee4/functions/utils/auth/tokenValidator.js)及[上传鉴权](https://github.com/MarSeventh/CloudFlare-ImgBed/blob/85636c5bc7393e80e0fe229a8f73538ad5c65ee4/functions/upload/index.js)。

在 **Terminal（终端）** 中执行下面的命令。`-w` 必须放在末尾，后面不要填写 Token；按交互提示粘贴 Token，输入不会回显：

```sh
/usr/bin/security add-generic-password -U \
  -s "${IMGBED_KEYCHAIN_SERVICE:-imgbed}" \
  -a api-token -w
```

这会把 Token 存入默认钥匙串，service 默认为 `imgbed`，account 固定为 `api-token`；`-U` 可更新已有项。交互提示方式可避免 Token 出现在 shell 历史和命令行参数里，参见 [Apple 的 security 工具源码说明](https://github.com/apple-oss-distributions/Security/blob/main/SecurityTool/macOS/security.c)。不要将 Token 写进快捷指令、环境变量、脚本常量或截图，也不要启用 `set -x` 调试。

多站点可在保存命令前设置 `IMGBED_KEYCHAIN_SERVICE`，并在对应的每条快捷指令中设置同样的值。service 只是本地条目的标识，不能代替站点地址。建议根据用途和有效期分别创建 Token。

<!-- TODO: 添加已去除域名、账号及 Token 的截图。 -->
![TODO：API Token 创建界面，只展示 upload 权限](images/token-settings.png)

## 2. 安装脚本并配置地址

在本仓库根目录运行：

```sh
mkdir -p "$HOME/bin/imgbed"
cp docs/shortcuts/upload.py "$HOME/bin/imgbed/upload.py"
chmod 700 "$HOME/bin/imgbed/upload.py"
python3 "$HOME/bin/imgbed/upload.py" --help
```

也可以手动将本目录的 `upload.py` 保存为 `~/bin/imgbed/upload.py`。所有示例都用 `$HOME`，不需要填写 Mac 用户名。

将下面示例中的 `https://your-imgbed.example` 替换为你部署的图床 HTTPS 站点地址，不带 `/upload`、其他路径、查询参数或账号密码。它是占位地址，脚本会拒绝直接使用。

配置有两种方式：在**每一条快捷指令**里 `export IMGBED_BASE=...`，或者修改已安装脚本顶部的 `BASE` 常量。环境变量优先于常量。终端里的 `export` 不会自动传给 Shortcuts；上一条快捷指令设置的环境变量也不会持久化到下一条。`IMGBED_KEYCHAIN_SERVICE` 的自定义值同样需要逐条设置。

### 可选：只读鉴权检查

若 Token 具有 `list` 权限，可在终端执行：

```sh
export IMGBED_BASE="https://your-imgbed.example"
export IMGBED_KEYCHAIN_SERVICE="imgbed"
python3 "$HOME/bin/imgbed/upload.py" check
```

`check` 使用 `GET /api/manage/batch/list?limit=1&includeValue=false`，先携带钥匙串中的 Bearer Token 请求，确认响应包含 `success: true` 和 `records` 数组（空数组也正常），再发出不带 Token 的请求。只有带 Token 的请求成功且匿名请求返回 401/403，才报告检查通过；不显示文件记录，不操作剪贴板。此检查不能证明具有上传权限或上传渠道可用。

**仅有 `upload` 权限的 Token 被此接口拒绝是预期情况，不能据此判定 Token 无效或无法上传。** 上传用户可以跳过 `check`，不必为检查额外授予 `list` 权限。401/403 也可能来自 Token 过期或站点访问规则；脚本不会把这些情况一概标为“Token 无效”。若匿名请求也成功，检查会提示无法确认 Token 有效性；若返回 404，应核对部署版本。

此批量读取端点及 `list` 权限要求已分别核对[处理器源码](https://github.com/MarSeventh/CloudFlare-ImgBed/blob/85636c5bc7393e80e0fe229a8f73538ad5c65ee4/functions/api/manage/batch/list.js)和[管理端中间件](https://github.com/MarSeventh/CloudFlare-ImgBed/blob/85636c5bc7393e80e0fe229a8f73538ad5c65ee4/functions/api/manage/_middleware.js)。它没有上传、删除或过期清理操作。普通[列表处理器](https://github.com/MarSeventh/CloudFlare-ImgBed/blob/85636c5bc7393e80e0fe229a8f73538ad5c65ee4/functions/api/manage/list.js)会调用过期文件清理，因此不用于这项只读探测。批量端点未在本次核对的[官方列表文档](https://cfbed.sanyue.de/api/list.html)中单列，兼容性依据为上述仓库源码；检查不会自动回退到普通列表端点。

若把 `check` 单独做成快捷指令，接收 **Nothing（无输入）**，**Pass Input → to stdin（到标准输入）**；使用下面上传快捷指令同样的 HOME、PATH、站点及钥匙串配置，将最后一行改为 `python3 "$HOME/bin/imgbed/upload.py" check`。

## 3. 创建上传快捷指令（推荐先完成这一条）

1. 打开 **Shortcuts（快捷指令）**，新建快捷指令，命名为“上传到 ImgBed”。
2. 在 **Details（详细信息，ⓘ）** 中启用 **Use as Quick Action（用作快速操作）**，勾选 **Finder（访达）**。
3. 在顶部输入设置中，将 **Receive（接收）** 设为 **Files and Folders（文件和文件夹）**，来源为 **Finder**。某些版本需要分别勾选 Files 和 Folders；无输入时选择停止，不要把“没有文件”当成剪贴板图片。
4. 添加 **Run Shell Script（运行 Shell 脚本）** 动作，设置如下：

| 选项 | 值 |
| --- | --- |
| Shell | `/bin/zsh` |
| Input（输入） | **Shortcut Input（快捷指令输入）** |
| Pass Input（传递输入） | **as arguments（作为参数）** |

将以下内容粘贴到脚本框，并替换站点占位地址：

```zsh
export HOME="${HOME:?无法确定用户主目录}"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export IMGBED_BASE="https://your-imgbed.example"
export IMGBED_KEYCHAIN_SERVICE="imgbed"
python3 "$HOME/bin/imgbed/upload.py" upload "$@"
```

`"$@"` 会逐个传递文件路径，保留空格和中文；不要换成 `$*`，也不要让路径经过 `eval`。将 `/opt/homebrew/bin` 放在 PATH 前面，可找到常见 Apple Silicon Python 安装；`/usr/local/bin` 兼顾其他安装位置。

在 Finder 中选择一张小图片，右键 → **Quick Actions（快速操作）** → “上传到 ImgBed”。成功后，脚本将链接输出到快捷指令结果，并通过 `pbcopy` 复制到剪贴板；多个文件的链接每行一条。通知只是提示，通知权限被关闭不影响上传结果。

<!-- TODO: 在 Mac 上实测后添加上传快捷指令截图；当前没有实拍图片。 -->
![TODO：接收 Finder 文件和文件夹，运行 Shell 脚本并作为参数传入](images/upload-shortcut.png)

### 文件夹如何处理

选择 `相册` 文件夹，其中有 `旅行/海边.png`，脚本会提交 `uploadFolder=相册/旅行` 和原始文件名 `海边.png`。直接选择一个文件则上传到根目录。对所选项目本身和递归遇到的后代，跳过点号隐藏项目、macOS 隐藏标记项目、符号链接及非普通文件；空文件夹不会上传。同一次调用中重复的文件路径只处理一次，重叠选择以先遇到的路径结构为准。

不会仅因显式路径的祖先目录隐藏或为符号链接而跳过输入，例如 `/tmp/相册/a.png`、`/var/folders/.../a.png` 仍可选用。直接选择符号链接本身仍会跳过，递归也不会进入遇到的符号链接目录；上传读取文件时保留 `O_NOFOLLOW` 检查，防止文件本身在枚举后变成符号链接。

脚本使用 `uploadNameType=origin` 请求保留原名和相对层级，但**服务端不保证逐字保留名称**：特殊字符可能被替换，重名会生成后缀，部分 `%` 名称还受服务端解码规则影响。实际链接以响应为准，详见[文件名与目录处理源码](https://github.com/MarSeventh/CloudFlare-ImgBed/blob/85636c5bc7393e80e0fe229a8f73538ad5c65ee4/functions/upload/uploadTools.js)。

这是逐个文件的普通 multipart 上传，不做客户端分块、图片压缩或自动重试。上传格式、大小和有效期受部署及渠道配置限制。中途失败会停止；已完成的链接仍在标准输出中，不会回滚已上传文件，剪贴板只在整批成功后更新。超时也可能发生在服务端已保存之后，重试前先查看后台。

### 菜单栏、快捷键和脚本

在快捷指令详情中可开启 **Pin in Menu Bar（固定到菜单栏）**、配置 **Add Keyboard Shortcut（添加键盘快捷键）**。文件上传需要输入：在 Finder 选中文件后使用快速操作；从菜单栏独立运行时，可以先增加 **Select File（选择文件）** 或 **Select Folder（选择文件夹）** 动作，并把其结果接到 Shell 动作。列表、随机图和下面的剪贴板快捷指令适合直接放在菜单栏或绑定热键。

终端或 shell 脚本也能调用同一个入口：

```sh
export IMGBED_BASE="https://your-imgbed.example"
python3 "$HOME/bin/imgbed/upload.py" upload "$HOME/Pictures/示例图片.png"
python3 "$HOME/bin/imgbed/upload.py" upload "$HOME/Pictures/相册" "$HOME/Downloads/另一张.png"
# 文件名以 - 开头时，用 -- 结束选项解析
python3 "$HOME/bin/imgbed/upload.py" upload -- ./-example.png
```

## 4. 可选：上传剪贴板图片

新建另一条快捷指令。将接收类型设为 **Nothing（无输入）**，Shell 仍为 `/bin/zsh`，**Pass Input → to stdin（到标准输入）**；脚本不读取这个 stdin。使用：

```zsh
export HOME="${HOME:?无法确定用户主目录}"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export IMGBED_BASE="https://your-imgbed.example"
export IMGBED_KEYCHAIN_SERVICE="imgbed"
python3 "$HOME/bin/imgbed/upload.py" clipboard
```

例如在 Chrome 中右键图片，选择 **Copy Image（复制图片）**，然后运行快捷指令。不要选 **Copy Image Address（复制图片地址）**。也可以用 macOS 截图快捷键配合 Control 将截图复制到剪贴板。

脚本通过 JXA/AppKit 读取剪贴板 PNG；必要时将 AppKit 可识别的图片转为 PNG，写入临时目录，再上传为 `clipboard.png`。不是网页截图工具，也不会下载剪贴板里的 URL。浏览器、图片格式和剪贴板表示的兼容性仍需在目标 Mac 上确认；没有可读取图片时会明确报错。

<!-- TODO: 添加剪贴板上传快捷指令截图。 -->
![TODO：无输入的剪贴板图片上传快捷指令](images/clipboard-shortcut.png)

## 5. 可选：最近文件 → 下载或复制链接

需要具有 `list` 权限的 Token。新建快捷指令，输入设为 **Nothing（无输入）**，Shell 为 `/bin/zsh`，**Pass Input → to stdin（到标准输入）**：

```zsh
export HOME="${HOME:?无法确定用户主目录}"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export IMGBED_BASE="https://your-imgbed.example"
export IMGBED_KEYCHAIN_SERVICE="imgbed"
python3 "$HOME/bin/imgbed/upload.py" list
```

脚本查询最多 25 条最近记录，在第一个 JXA `chooseFromList` 对话框中显示文件名和路径，默认选中第一条。确认文件后打开**第二个 `chooseFromList`**，选项严格按以下顺序显示：

1. **下载到指定文件夹**（默认选中）
2. **复制链接**

第二个列表的 `defaultItems` 为 `["下载到指定文件夹"]`。确认“下载到指定文件夹”后，再打开目录选择器，代码使用 `chooseFolder(...).toString()` 获取路径，**没有使用 `POSIXPath` 属性**。任一列表或目录选择器中取消都会停止操作，不会改为执行默认动作。

下载先写临时目录，成功后以原子排他创建方式保存到目标目录；已有同名文件或符号链接时自动尝试 `名称 (1).扩展名` 等后缀，不覆盖已有内容，也不使用“先检查存在、再普通写入”的竞态写法。复制和下载均使用经过路径编码的 `/file/{name}`；列表接口并不保证返回上传时的 `publicUrl`。

可通过参数跳过部分对话框：

```sh
# 下列示例假定当前终端已经设置 IMGBED_BASE
python3 "$HOME/bin/imgbed/upload.py" list --action copy
python3 "$HOME/bin/imgbed/upload.py" list --first --action copy
python3 "$HOME/bin/imgbed/upload.py" list --first --action download --destination "$HOME/Downloads"
```

普通文件读取通常无需 Token，但仍受站点访问规则限制；脚本不会把管理 Token 转发到文件下载或其重定向目标。具有 `list` 权限不代表能下载所有文件，见[官方读取 API](https://cfbed.sanyue.de/api/file.html)。

<!-- TODO: 添加列表快捷指令和选择文件对话框截图。 -->
![TODO：最近文件列表；第二个列表依次为下载到指定文件夹、复制链接，默认选择第一项](images/list-shortcut.png)

## 6. 可选：随机图链接

管理员先在图床后台的系统设置中开启随机图功能并配置允许目录；具体开关位置以部署版本为准。此接口源码没有 Token 校验，脚本**不会读取钥匙串，也不会发送 Authorization**。这是对随机图接口鉴权的核对结论，不是漏配权限。参见[官方 API 概览](https://cfbed.sanyue.de/api/)和[随机图中间件](https://github.com/MarSeventh/CloudFlare-ImgBed/blob/85636c5bc7393e80e0fe229a8f73538ad5c65ee4/functions/random/_middleware.js)。

快捷指令接收 **Nothing（无输入）**，Shell 为 `/bin/zsh`，**Pass Input → to stdin（到标准输入）**：

```zsh
export HOME="${HOME:?无法确定用户主目录}"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export IMGBED_BASE="https://your-imgbed.example"
python3 "$HOME/bin/imgbed/upload.py" random
```

脚本调用 `/random?type=url&form=text`，校验结果是 URL 后输出并复制。若关闭功能或当前目录不在允许范围，可能返回 403；没有匹配图片时，当前源码即使请求文本也会返回 `{}`，脚本会提示无结果。默认请求根目录；如果站点只开放特定子目录，需要管理员调整配置或自行扩展请求的 `dir` 参数。见[随机图文档](https://cfbed.sanyue.de/api/random.html)及[实现](https://github.com/MarSeventh/CloudFlare-ImgBed/blob/85636c5bc7393e80e0fe229a8f73538ad5c65ee4/functions/random/index.js)。

<!-- TODO: 添加随机图快捷指令截图。 -->
![TODO：获取随机图链接的快捷指令](images/random-shortcut.png)

## 接口与响应核对

| 操作 | 本脚本的请求 | 已核对的响应 |
| --- | --- | --- |
| 上传 | `POST /upload?returnFormat=full&responseFormat=object`，另加 `uploadNameType=origin`、必要时 `uploadFolder`；multipart 字段 `file`；Bearer Token | 单文件对象的 `publicUrl`（可选）或 `src`；兼容单元素数组 |
| 列表 | `GET /api/manage/list?start=0&count=25&recursive=true`；Bearer Token | `{ "files": [{ "name": "相册/a.png", "metadata": { "TimeStamp": 123 } }] }`，另有分页、目录等字段 |
| 只读检查 | `GET /api/manage/batch/list?limit=1&includeValue=false`；先带 Bearer Token，再匿名请求 | 带 Token 时 `{ "success": true, "records": [] }` 等结构；匿名须返回 401/403 才判为通过；要求 `list` 权限 |
| 随机图 | `GET /random?type=url&form=text`；无 Token | URL 文本；无匹配项时当前实现返回 `{}` |

上传成功后优先使用非空 `publicUrl`，否则取 `src`；`/file/...` 或 `file/...` 相对地址会补上站点地址。`returnFormat` 控制链接形式，`responseFormat` 控制 JSON 外层结构，两者不同。官方依据为[上传文档](https://cfbed.sanyue.de/api/upload.html)、[列表文档](https://cfbed.sanyue.de/api/list.html)；实现依据为[上传响应构建](https://github.com/MarSeventh/CloudFlare-ImgBed/blob/85636c5bc7393e80e0fe229a8f73538ad5c65ee4/functions/upload/uploadTools.js)、[列表接口](https://github.com/MarSeventh/CloudFlare-ImgBed/blob/85636c5bc7393e80e0fe229a8f73538ad5c65ee4/functions/api/manage/list.js)及[列表记录序列化](https://github.com/MarSeventh/CloudFlare-ImgBed/blob/85636c5bc7393e80e0fe229a8f73538ad5c65ee4/functions/utils/metadata/metadataView.js)。表中的响应是结构示意，不是实测数据。

已知差异和不确定点：

- [Token 文档](https://cfbed.sanyue.de/api/token.html)仍有管理员 Basic Auth 的描述；本次仓库的[认证核心](https://github.com/MarSeventh/CloudFlare-ImgBed/blob/85636c5bc7393e80e0fe229a8f73538ad5c65ee4/functions/utils/auth/authCore.js)使用管理员会话或 API Token。本教程通过登录后的 UI 创建 Token，不依赖 Basic Auth。
- 随机图文档正文提到 `data.url`，但其示例和源码实际是顶层 `{ "url": ... }`。本脚本选择 `form=text`，不猜测 JSON 包装层。
- “最近”依赖服务器索引。当前[索引实现](https://github.com/MarSeventh/CloudFlare-ImgBed/blob/85636c5bc7393e80e0fe229a8f73538ad5c65ee4/functions/utils/indexManager.js)按时间倒序组织文件，脚本还会对返回记录按 `metadata.TimeStamp` 排序并截取 25 条。但索引延迟、缺失时间戳以及 `isIndexedResponse=false` 的回退路径可能影响分页、递归和排序，不能保证总是全站最新 25 条。
- 旧部署可能缺少 `publicUrl` 或忽略 `responseFormat=object`，脚本兼容常见的单元素数组。其他返回结构会报错，需按实际部署核对；外层登录网关、额外鉴权和渠道可用性未实测。
- 截图都是明确标记的 TODO 占位，`images/.gitkeep` 仅保留目录；应在目标 Mac 实测、去除个人信息后补图。

## 常见问题

**终端可以运行，快捷指令提示 `python3: command not found`？** 重新检查每条快捷指令的 PATH。终端运行 `command -v python3` 查明位置；自定义安装路径可以加入 PATH，或将 `python3` 改为它的绝对路径。Shortcuts 通常不读取交互式 `.zshrc`。

**提示文件或自动化权限不足？** 检查 Shortcuts 的设置是否允许 **Allow Running Scripts（允许运行脚本）**，并按系统提示授予实际需要的文件夹访问/自动化权限。不同 macOS 版本可能将它放在 **Settings/Preferences → Advanced（设置/偏好设置 → 高级）**。目录授权与通知授权是不同的；不要仅凭通知没出现判断上传失败。

**Keychain 找不到条目或弹窗被拒绝？** 在 **Keychain Access（钥匙串访问）** 中确认 service、account 与脚本一致，钥匙串已解锁；第一次运行时可能询问是否允许 `security` 读取。只运行随机图无需保存 Token。重置 Token 后重新执行交互式保存命令，不要运行会把密码打印到终端的诊断命令。

**401/403？** 核对站点地址、Token 有效期和所需的 `upload`/`list` 权限。`check` 和 `list` 被拒绝不能证明仅有 `upload` 权限的 Token 无效；`check` 的匿名对照请求被拒绝则是预期结果。随机图还需核对开关及允许目录；文件下载还需核对访问规则。脚本不输出服务器原始错误正文，以免代理或服务端回显敏感信息。

**代理环境影响请求？** 脚本固定使用 `/usr/bin/curl`，清除大小写各种 `*_proxy` 环境变量、显式禁用 curl 代理，并以首个 `-q` 参数禁用 `.curlrc`。系统 VPN/网络路由仍可能生效；只能通过代理访问的站点不适用于这份默认配置。连接超时为 15 秒，单次传输最多 300 秒。

**Token 会出现在进程列表或临时文件里吗？** 上传/列表/检查的 Token 从 `security` 输出捕获到内存，通过 `curl --config -` 的标准输入管道传递；不写 curl 配置文件，不放在 argv、URL 或通知里。请求正文、下载、响应和剪贴板 PNG 使用 `TemporaryDirectory`，正常结束或可处理异常时清理；强制终止进程可能留下临时内容。API 请求不自动跟随重定向，下载重定向不携带 Token。此设计减少凭据落盘和日志暴露，不承诺对有权读取进程内存的程序保密。

**按取消为什么没输出链接？** 文件/目录/操作选择的取消与运行错误分开处理：取消或 Ctrl-C 输出“已取消。”并返回 `130`；一般运行错误为 `1`，命令行参数错误为 `2`，成功为 `0`。Shortcuts 可能仍将非零退出显示为动作停止；不要把取消当成失败后自动重试。

## 验证范围

已执行 `py_compile` 和 Linux 离线 mock 检查，覆盖命令参数、上传对象/数组响应、相对 URL、目录结构、隐藏文件/符号链接跳过、允许符号链接或隐藏祖先的显式输入、curl 凭据管道及代理清理、列表响应、只读鉴权检查的成功/拒绝/匿名开放/无效响应、两个列表的顺序及取消分支，以及下载重名处理。测试没有向网络上传文件，没有读写实际 macOS 钥匙串，也不能替代 Mac 上对快捷指令、AppKit 和系统授权的实际验收。
