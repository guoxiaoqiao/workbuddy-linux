#!/usr/bin/env bash
# Verify an installed WorkBuddy deb on the target machine:
# package integrity, maintainer-script behaviour, desktop registration.
# Dev/test/verification environment: Ubuntu 26.04; other environments unverified.
set -euo pipefail

fail() { echo "FAIL: $*" >&2; exit 1; }

dpkg-query -W -f='${Status}\n' workbuddy 2>/dev/null | grep -q 'install ok installed' \
  || fail 'workbuddy 未安装或未完成配置'

echo '== dpkg -V 完整性（md5sums） =='
differences=$(dpkg -V workbuddy || true)
if [ -n "$differences" ]; then
  echo "$differences"
  fail 'dpkg -V 发现文件差异'
fi
echo '干净'

echo '== 启动器内容 =='
expected=$'#!/bin/sh\nexec /opt/WorkBuddy/launch-workbuddy "$@"'
[ "$(cat /usr/bin/workbuddy)" = "$expected" ] || fail '/usr/bin/workbuddy 内容不符'
echo '正确'

echo '== 官方提取资产 =='
[ "$(ls /usr/share/icons/hicolor/*/apps/workbuddy.png 2>/dev/null | wc -l)" -eq 9 ] \
  || fail 'hicolor 图标不是官方的 9 个尺寸'
for path in /usr/share/doc/workbuddy/changelog.gz /usr/share/doc/workbuddy/NOTICE \
            /opt/WorkBuddy/resources/tray-linux.png /opt/WorkBuddy/resources/default_app.asar; do
  [ -e "$path" ] || fail "缺少 $path"
done
echo '齐备'

echo '== 内置运行时不打包（有意偏离官方布局） =='
[ ! -e /opt/WorkBuddy/resources/runtime ] || fail 'resources/runtime 不应存在（该运行时已改为系统解释器/按需下载）'
grep -q 'DEFAULT_BUNDLED_RUNTIME_CONFIG={enabled:!1,' /opt/WorkBuddy/resources/app.asar.unpacked/main/main-bootstrap.js \
  || fail 'bundledRuntime 默认值未改为关闭'
echo '符合预期'

echo '== postinst 启动器自愈 =='
backup=$(mktemp)
cp /usr/bin/workbuddy "$backup"
sudo rm /usr/bin/workbuddy
sudo /var/lib/dpkg/info/workbuddy.postinst configure
diff "$backup" /usr/bin/workbuddy >/dev/null || fail 'postinst 未恢复启动器'
rm "$backup"
echo '已恢复'

echo '== postrm upgrade 守卫 =='
sudo /var/lib/dpkg/info/workbuddy.postrm upgrade
[ -e /usr/bin/workbuddy ] || fail 'postrm upgrade 删除了启动器（正是官方包的缺陷）'
echo '守卫生效'

echo '== GIO/GTK 桌面注册 =='
if python3 -c 'import gi' 2>/dev/null; then
  python3 - <<'PY'
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gio
info = Gio.DesktopAppInfo.new('workbuddy.desktop')
assert info and info.should_show(), 'GIO 未列出 workbuddy.desktop'
theme = Gtk.IconTheme.get_default()
for size in (48, 128, 512):
    assert theme.lookup_icon('workbuddy', size, 0), f'图标 {size} 不可解析'
print('应用注册与图标解析正常')
PY
else
  echo 'python3-gi 不可用，跳过（非致命）'
fi

echo
echo '全部通过。窗口验证：DISPLAY=:0 workbuddy'
