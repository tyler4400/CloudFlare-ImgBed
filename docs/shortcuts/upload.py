#!/usr/bin/env python3
"""CloudFlare ImgBed helper for macOS Shortcuts; Python 3 standard library only."""

import argparse
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile
from urllib.parse import quote, urlencode, urljoin, urlsplit


BASE = "https://your-imgbed.example"  # Or set IMGBED_BASE in EACH Shortcut.
ACCOUNT = "api-token"
MAX_RESPONSE = 4 * 1024 * 1024


class HelperError(Exception):
    pass


class HTTPError(HelperError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class Cancelled(Exception):
    pass


# Fixed source; all user/server values are data in argv, never executable code.
JXA = r'''
ObjC.import('AppKit');
function run(argv) {
    var app = Application.currentApplication();
    app.includeStandardAdditions = true;
    var data = JSON.parse(argv[1]);
    try {
        if (argv[0] === 'notify') {
            app.displayNotification(data, {withTitle: 'ImgBed'});
            return JSON.stringify({ok: true});
        }
        if (argv[0] === 'select') {
            var chosen = app.chooseFromList(data, {
                withPrompt: '选择最近的文件 / Select a recent file',
                defaultItems: [data[0]], multipleSelectionsAllowed: false,
                emptySelectionAllowed: false
            });
            if (chosen === false) return JSON.stringify({cancelled: true});
            return JSON.stringify({value: data.indexOf(chosen[0])});
        }
        if (argv[0] === 'action') {
            var actions = ['下载到指定文件夹', '复制链接'];
            var result = app.chooseFromList(actions, {
                withPrompt: '选择文件操作 / Choose an action',
                defaultItems: ['下载到指定文件夹'], multipleSelectionsAllowed: false,
                emptySelectionAllowed: false
            });
            if (result === false) return JSON.stringify({cancelled: true});
            return JSON.stringify({value:
                result[0] === '下载到指定文件夹' ? 'download' : 'copy'});
        }
        if (argv[0] === 'folder') {
            var folder = app.chooseFolder({withPrompt: '选择下载目录 / Download to'});
            return JSON.stringify({value: folder.toString()});
        }
        if (argv[0] === 'clipboard') {
            var pb = $.NSPasteboard.generalPasteboard;
            var png = pb.dataForType($.NSPasteboardTypePNG);
            if (!png || png.isNil()) {
                var img = $.NSImage.alloc.initWithPasteboard(pb);
                if (!img || img.isNil()) return JSON.stringify({error: 'no-image'});
                var rep = $.NSBitmapImageRep.imageRepWithData(img.TIFFRepresentation);
                if (!rep || rep.isNil()) return JSON.stringify({error: 'no-image'});
                png = rep.representationUsingTypeProperties($.NSBitmapImageFileTypePNG, $({}));
            }
            if (!png || png.isNil() || !png.writeToFileAtomically($(data), true)) {
                return JSON.stringify({error: 'png-write'});
            }
            return JSON.stringify({ok: true});
        }
        return JSON.stringify({error: 'unknown-action'});
    } catch (err) {
        if (Number(err.errorNumber) === -128 || Number(err.number) === -128) {
            return JSON.stringify({cancelled: true});
        }
        return JSON.stringify({error: 'macos-automation'});
    }
}
'''


def run_process(argv, **kwargs):
    try:
        return subprocess.run(argv, check=False, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, **kwargs)
    except subprocess.TimeoutExpired:
        raise HelperError("操作超时；若是上传，服务端可能已接收文件，请先查看后台。") from None
    except OSError:
        raise HelperError("无法启动 macOS 系统工具，请检查安装及系统权限。") from None


def jxa(action, data=None):
    result = run_process(
        ["/usr/bin/osascript", "-l", "JavaScript", "-e", JXA,
         action, json.dumps(data, ensure_ascii=True)], timeout=15 if action == "notify" else 300)
    if result.returncode:
        raise HelperError("macOS 自动化失败，请检查 Shortcuts/Terminal 的权限。")
    try:
        payload = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        raise HelperError("macOS 自动化返回了无法识别的结果。") from None
    if payload.get("cancelled"):
        raise Cancelled()
    if payload.get("error") == "no-image":
        raise HelperError("剪贴板中没有可读取的图片；请使用“复制图片”，而非复制图片地址。")
    if payload.get("error"):
        raise HelperError("macOS 图片转换或自动化失败，请检查权限和剪贴板内容。")
    return payload.get("value")


def notify(message):
    try:
        jxa("notify", message)
    except (HelperError, Cancelled):
        pass  # Notifications are best effort; never turn a successful upload into a failure.


def copy_text(value):
    result = run_process(["/usr/bin/pbcopy"], input=value.encode("utf-8"), timeout=15,
                         env={**os.environ, "LC_CTYPE": "UTF-8"})
    if result.returncode:
        raise HelperError("写入剪贴板失败；已完成的结果仍在标准输出中。")


def get_base():
    value = os.environ.get("IMGBED_BASE", BASE).strip().rstrip("/")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.path or parsed.query or parsed.fragment
            or any(c.isspace() or ord(c) < 32 for c in value)
            or parsed.hostname == "your-imgbed.example"):
        raise HelperError("请将 IMGBED_BASE 或 BASE 设置为实际图床的 HTTPS 站点地址（不含路径）。")
    return value


def get_token():
    service = os.environ.get("IMGBED_KEYCHAIN_SERVICE", "imgbed")
    if not service or any(ord(c) < 32 for c in service):
        raise HelperError("IMGBED_KEYCHAIN_SERVICE 不能为空或含控制字符。")
    result = run_process(["/usr/bin/security", "find-generic-password", "-s", service,
                          "-a", ACCOUNT, "-w"], timeout=120)
    if result.returncode:
        if b"user canceled" in result.stderr.lower() or b"user cancelled" in result.stderr.lower():
            raise Cancelled()
        raise HelperError("无法读取 Keychain：请检查 service、account、钥匙串解锁状态及访问授权。")
    try:
        token = result.stdout.decode("utf-8").rstrip("\r\n")
    except UnicodeError:
        raise HelperError("Keychain 中的 Token 编码无效。") from None
    if not token or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in token):
        raise HelperError("Keychain 中的 Token 为空或含空白/控制字符，请重新保存。")
    return token


def config_quote(value):
    """Quote a curl config value, including a nested, quoted multipart form."""
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace(
        '\r', '\\r').replace('\n', '\\n').replace('\t', '\\t') + '"'


def curl_to_file(url, output, token=None, form=None, download=False):
    # -q MUST be first: ignore ~/.curlrc (logging/proxy/redirect options).
    options = ["silent", "show-error", "globoff", 'connect-timeout = "15"',
               'max-time = "300"', 'proxy = ""', 'noproxy = "*"',
               'proto = "=http,https"', 'proto-redir = "=http,https"',
               'write-out = "%{http_code}"', "url = " + config_quote(url),
               "output = " + config_quote(output)]
    if token:
        options.append("header = " + config_quote("Authorization: Bearer " + token))
    if form:
        options.extend(['request = "POST"', "form = " + config_quote(form)])
    if download:
        if token:
            raise HelperError("下载不应携带 API Token。")
        options.extend(["location", 'max-redirs = "5"'])
    env = {key: value for key, value in os.environ.items()
           if not key.lower().endswith("_proxy")}
    result = run_process(["/usr/bin/curl", "-q", "--config", "-"],
                         input=("\n".join(options) + "\n").encode("utf-8"),
                         env=env, timeout=315)
    if result.returncode:
        # Never print curl stderr, config, response bodies, or subprocess exceptions:
        # they may contain credentials reflected by a server or local configuration.
        raise HelperError("网络请求失败（curl 退出码 %s）；请检查网络、HTTPS 证书及文件大小。"
                          "上传可能已完成，请先查看后台再重试。" % result.returncode)
    status = result.stdout.decode("ascii", errors="replace").strip()
    if status in ("401", "403"):
        raise HTTPError(int(status), "HTTP %s：检查 Token 权限/有效期；随机图还需检查功能开关及允许目录。" % status)
    if not status.isdigit() or not 200 <= int(status) < 300:
        raise HTTPError(int(status) if status.isdigit() else None,
                        "HTTP %s：请求未成功（API 重定向不会自动跟随）；请检查站点配置。" %
                        (status if status.isdigit() else "未知"))


def request_text(url, token=None, form=None):
    with tempfile.TemporaryDirectory(prefix="imgbed-response-") as tmp:
        output = Path(tmp) / "response"
        curl_to_file(url, output, token, form)
        with output.open("rb") as stream:
            content = stream.read(MAX_RESPONSE + 1)
        if len(content) > MAX_RESPONSE:
            raise HelperError("API 响应过大，无法解析。")
        try:
            return content.decode("utf-8")
        except UnicodeError:
            raise HelperError("API 没有返回 UTF-8 文本。") from None


def parse_json(text):
    try:
        return json.loads(text)
    except (ValueError, UnicodeError):
        raise HelperError("API 返回的不是 JSON；请检查地址、部署版本或登录拦截页面。") from None


def public_url(base, value):
    if not isinstance(value, str) or not value.strip():
        raise HelperError("API 响应缺少文件 URL。")
    value = value.strip()
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise HelperError("API 返回的 URL 含控制字符。")
    if not value.startswith(("https://", "http://", "/", "file/")):
        raise HelperError("API 返回的不是有效文件 URL。")
    result = urljoin(base + "/", value)
    parsed = urlsplit(result)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username is not None or parsed.password is not None):
        raise HelperError("API 返回的 URL 格式无效。")
    return quote(result, safe=":/?#[]@!$&'()*+,;=%")


def upload_url(base, text):
    data = parse_json(text)
    if isinstance(data, list) and len(data) == 1:
        data = data[0]  # Older releases can ignore responseFormat=object.
    if not isinstance(data, dict) or data.get("error") or data.get("success") is False:
        raise HelperError("上传响应结构无效或服务端报告失败。")
    return public_url(base, data.get("publicUrl") or data.get("src"))


def hidden_or_link(path):
    info = path.lstat()
    return (path.name.startswith(".") or stat.S_ISLNK(info.st_mode)
            or bool(getattr(info, "st_flags", 0) & getattr(stat, "UF_HIDDEN", 0)))


def collect_files(arguments):
    """Keep the selected folder name, then its relative descendants; deduplicate paths."""
    files, seen = [], set()

    def add(path, relative):
        if path not in seen and path.is_file() and not hidden_or_link(path):
            seen.add(path)
            files.append((path, relative))

    def walk_error(_error):
        raise HelperError("无法遍历所选目录，请检查文件访问权限。")

    for argument in arguments:
        path = Path(os.path.abspath(os.path.expanduser(argument)))
        # Only inspect the selected entry and traversed descendants. Ancestors may
        # legitimately be symlinks (macOS /tmp, /var) or hidden directories.
        if hidden_or_link(path):
            print("跳过隐藏项目或符号链接。", file=sys.stderr)
            continue
        if path.is_file():
            add(path, PurePosixPath(path.name))
        elif path.is_dir():
            if path == path.parent:
                raise HelperError("请选择具体文件夹，不要选择文件系统根目录。")
            for current, dirs, names in os.walk(path, followlinks=False, onerror=walk_error):
                root = Path(current)
                dirs[:] = sorted(d for d in dirs if not hidden_or_link(root / d))
                for name in sorted(names):
                    item = root / name
                    add(item, PurePosixPath(item.relative_to(path.parent).as_posix()))
        else:
            raise HelperError("输入不是普通文件或文件夹。")
    if not files:
        raise HelperError("没有可上传的普通文件（隐藏文件、符号链接和空文件夹会被跳过）。")
    return files


def form_quote(value):
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise HelperError("文件名不能包含控制字符。")
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def upload_one(base, token, path, relative):
    query = {"returnFormat": "full", "responseFormat": "object", "uploadNameType": "origin"}
    if relative.parent != PurePosixPath("."):
        query["uploadFolder"] = str(relative.parent)
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    # Snapshot the file, refusing a leaf symlink even if it changed after enumeration.
    with tempfile.TemporaryDirectory(prefix="imgbed-upload-") as tmp:
        snapshot = Path(tmp) / "payload"
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise HelperError("上传源已不再是普通文件。")
            with snapshot.open("wb") as target:
                shutil.copyfileobj(source, target)
        form = "file=@%s;filename=%s;type=%s" % (
            form_quote(str(snapshot)), form_quote(relative.name), mime)
        return upload_url(base, request_text(base + "/upload?" + urlencode(query), token, form))


def upload_many(base, files):
    token = get_token()
    urls = []
    try:
        for path, relative in files:
            url = upload_one(base, token, path, relative)
            urls.append(url)
            print(url, flush=True)
    except (HelperError, OSError, KeyboardInterrupt):
        if urls:
            print("中途停止；已上传 %d 个文件，其链接保留在标准输出中。" % len(urls), file=sys.stderr)
        raise
    copy_text("\n".join(urls))
    notify("已上传 %d 个文件，链接已复制。" % len(urls))


def recent_files(text):
    data = parse_json(text)
    if not isinstance(data, dict) or data.get("error") or not isinstance(data.get("files"), list):
        raise HelperError("列表响应应为包含 files 数组的对象。")
    files = data["files"]
    for item in files:
        if (not isinstance(item, dict) or not isinstance(item.get("name"), str)
                or not item["name"] or not isinstance(item.get("metadata", {}), dict)):
            raise HelperError("列表条目缺少有效的 name/metadata。")

    def timestamp(item):
        try:
            return int(item.get("metadata", {}).get("TimeStamp", 0))
        except (ValueError, TypeError, OverflowError):
            return 0

    return sorted(files, key=timestamp, reverse=True)[:25]


def safe_filename(name):
    # Server filenames are untrusted; never use their directory components locally.
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join("_" if ord(c) < 32 or ord(c) == 127 or c == ":" else c for c in name)
    if name in ("", ".", ".."):
        return "download"
    # Keep ample room for numeric collision suffixes on common macOS filesystems.
    while len(name.encode("utf-8")) > 180:
        name = name[:-1]
    return name


def save_unique(source, folder, name):
    name = safe_filename(name)
    stem, suffix = os.path.splitext(name)
    for index in range(10000):
        target = folder / (name if index == 0 else "%s (%d)%s" % (stem, index, suffix))
        try:
            # Atomic exclusive creation: never use exists() followed by ordinary open().
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        try:
            with os.fdopen(fd, "wb") as dest, source.open("rb") as src:
                shutil.copyfileobj(src, dest)
        except BaseException:
            target.unlink()
            raise
        return target
    raise HelperError("下载目录中重名文件过多，请选择其他目录。")


def list_files(base, args):
    files = recent_files(request_text(
        base + "/api/manage/list?start=0&count=25&recursive=true", get_token()))
    if not files:
        print("没有可选择的文件。", file=sys.stderr)
        return
    # Include an index and path to distinguish equal original filenames.
    labels = ["%d. %s — %s" % (i + 1, item.get("metadata", {}).get("FileName") or
                               item["name"].rsplit("/", 1)[-1], item["name"])
              for i, item in enumerate(files)]
    chosen = 0 if args.first else jxa("select", labels)
    if not isinstance(chosen, int) or not 0 <= chosen < len(files):
        raise HelperError("文件选择结果无效。")
    item = files[chosen]
    name = item["name"]
    if name.startswith("/") or any(part in (".", "..") for part in name.split("/")):
        raise HelperError("列表中的文件路径无效。")
    url = base + "/file/" + quote(name, safe="/")
    action = args.action or jxa("action")
    if action == "copy":
        print(url, flush=True)
        copy_text(url)
        notify("文件链接已复制。")
        return
    folder = Path(args.destination).expanduser() if args.destination else Path(jxa("folder"))
    if not folder.is_dir():
        raise HelperError("下载目标必须是已存在的目录。")
    with tempfile.TemporaryDirectory(prefix="imgbed-download-") as tmp:
        source = Path(tmp) / "download"
        curl_to_file(url, source, download=True)  # Public read; never forward the token.
        target = save_unique(source, folder, name)
    print(str(target), flush=True)
    notify("文件已下载。")


def random_file(base):
    text = request_text(base + "/random?type=url&form=text").strip()
    if text == "{}":
        raise HelperError("随机图没有匹配文件；请检查允许目录及图片类型。")
    url = public_url(base, text)
    print(url, flush=True)
    copy_text(url)
    notify("随机图链接已复制。")


def check_auth(base):
    # The ordinary list handler can trigger expired-file cleanup. This batch GET
    # only reads records; limit=1 and includeValue=false keep the probe small.
    url = base + "/api/manage/batch/list?limit=1&includeValue=false"
    token = get_token()
    try:
        data = parse_json(request_text(url, token))
    except HTTPError as error:
        if error.status in (401, 403):
            raise HelperError(
                "check 被拒绝（HTTP %s）：此只读检查要求 list 权限。仅有 upload 权限的 Token "
                "也会被拒绝，不能据此判定 Token 无效或无法上传；还需核对有效期及站点访问规则。"
                % error.status) from None
        if error.status == 404:
            raise HelperError("check 端点不存在（HTTP 404）；请核对部署版本，不能据此判定 Token 无效。") from None
        raise
    if (not isinstance(data, dict) or data.get("success") is not True
            or not isinstance(data.get("records"), list)):
        raise HelperError("check 响应应包含 success: true 和 records 数组，尚未验证鉴权。")
    # A deployment without admin authentication can accept even an invalid token.
    # Require rejection of an anonymous request before reporting auth success.
    try:
        request_text(url)
    except HTTPError as error:
        if error.status not in (401, 403):
            raise
    else:
        raise HelperError("check 端点允许匿名读取，无法确认 Token 有效性；请检查管理端认证配置。")
    print("check 通过：携带 Token 的只读 list 请求成功，匿名请求被拒绝；未验证 upload 权限或实际上传。")


def make_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    upload = commands.add_parser("upload", help="递归上传文件/文件夹，并复制链接")
    upload.add_argument("paths", metavar="FILE_OR_FOLDER", nargs="+")
    commands.add_parser("clipboard", help="将剪贴板图片转为 PNG 后上传")
    listing = commands.add_parser("list", help="选择最近文件，再下载或复制链接")
    listing.add_argument("--first", action="store_true", help="跳过列表，使用返回结果中的第一项")
    listing.add_argument("--action", choices=("download", "copy"), help="跳过操作选择")
    listing.add_argument("--destination", metavar="FOLDER", help="下载到已存在的目录，跳过目录选择")
    commands.add_parser("random", help="复制随机图 URL（无需 Token）")
    commands.add_parser("check", help="只读鉴权检查（要求 list 权限，不能验证 upload 权限）")
    return parser


def main(argv=None):
    parser = make_parser()
    args = parser.parse_args(argv)
    if args.command == "list" and args.destination and args.action == "copy":
        parser.error("--destination 不能与 --action copy 一起使用")
    try:
        if sys.platform != "darwin":
            raise HelperError("此脚本的实际运行需要 macOS；--help 可在其他平台查看。")
        base = get_base()
        if args.command == "upload":
            upload_many(base, collect_files(args.paths))
        elif args.command == "clipboard":
            with tempfile.TemporaryDirectory(prefix="imgbed-clipboard-") as tmp:
                path = Path(tmp) / "clipboard.png"
                jxa("clipboard", str(path))
                with path.open("rb") as png:
                    signature = png.read(8)
                if signature != b"\x89PNG\r\n\x1a\n":
                    raise HelperError("剪贴板转换未生成有效 PNG 文件。")
                upload_many(base, [(path, PurePosixPath(path.name))])
        elif args.command == "list":
            list_files(base, args)
        elif args.command == "check":
            check_auth(base)
        else:
            random_file(base)
        return 0
    except (Cancelled, KeyboardInterrupt):
        print("已取消。", file=sys.stderr)
        return 130
    except HelperError as error:
        print("错误：" + str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print("错误：文件访问或配置无效，请检查路径、权限及 URL。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
