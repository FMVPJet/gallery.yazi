[English](./README.md) | 简体中文

# gallery.yazi

一个运行在 [Yazi](https://github.com/sxyazi/yazi) 中的终端图片画廊插件。

`gallery.yazi` 会在与 Yazi 相同的终端会话里打开一个网格化图片浏览器，适合做文件夹图片浏览、轻量筛图和选择工作流。它不会替换 Yazi 原本的 preview pane，也不会跳到单独的 GUI 应用里。

## 特性亮点

- 终端原生缩略图网格
- 支持 `hjkl`、`gg`、`G` 的 `vim` 风格导航
- 使用 `Space` 标记图片
- 使用 `m` 切换到只看已标记图片
- 支持带元数据的单图查看
- 退出时会把标记结果和当前位置同步回 Yazi

## 它能做什么

- 使用 `\g` 在终端里打开图片网格
- 浏览当前目录或当前悬停目录中的图片
- 如果当前悬停的是图片，会尽量从那张图附近开始
- 同时支持方向键和 `vim` 风格导航
- 可以在画廊里用 `Space` 直接标记图片
- 退出后将标记结果同步回 Yazi
- 支持 `Marked-only` 过滤，方便做快速筛选
- 内置终端内单图查看模式，并显示图片元信息

## 依赖

- macOS
- [Yazi](https://github.com/sxyazi/yazi)
- 支持 Kitty graphics protocol 的终端
  - [Ghostty](https://ghostty.org/) 表现良好
- `python3`
- `sips`
- `zsh`

## 安装

把仓库克隆到 Yazi 的插件目录：

```sh
git clone git@github.com:FMVPJet/gallery.yazi.git \
  ~/.config/yazi/plugins/gallery.yazi
```

或者手动放到：

```sh
~/.config/yazi/plugins/gallery.yazi
```

然后在 `~/.config/yazi/keymap.toml` 中加入：

```toml
[[mgr.prepend_keymap]]
on   = [ "\\", "g" ]
run  = [
  "plugin gallery -- prepare_selection",
  "shell '/bin/zsh -f ~/.config/yazi/plugins/gallery.yazi/gallery.zsh %h' --block",
  "plugin gallery -- apply_selection"
]
desc = "Gallery"
```

## 快速开始

1. 在 Yazi 中进入一个包含图片的目录。
2. 按 `\g`。
3. 使用方向键或 `hjkl` 移动。
4. 使用 `Space` 标记图片。
5. 按 `q` 返回 Yazi，并保留筛选结果。

## 使用说明

### 打开方式

- 在 Yazi 中按 `\g`
- 如果当前悬停项是目录，画廊会打开该目录
- 如果当前悬停项是图片，画廊会打开当前目录，并尽量从该图片附近开始
- 如果你已经在同一目录里用 `Space` 选中过图片，画廊会以 `Selection` 模式启动

### 网格导航

- `Left` / `Right` / `Up` / `Down`：移动选中项
- `h` / `j` / `k` / `l`：使用 `vim` 键位移动
- `gg`：跳到第一张图片
- `G`：跳到最后一张图片
- `n`：向前跳一屏
- `p` 或 `Backspace`：向后跳一屏
- `q` 或 `Esc`：退出并返回 Yazi

### 标记与过滤

- `Space`：标记或取消标记当前图片
- `m`：当已标记图片存在时，切换 `Marked-only` 过滤模式
- 退出画廊时，会把已标记图片同步回 Yazi
- 退出画廊时，也会把 Yazi 光标恢复到你最后聚焦的图片上

### 单图模式

- `Enter`：以更大的终端内视图打开当前图片
- `Left` / `Right` 或 `h` / `l`：切换上一张 / 下一张
- `Space`：标记或取消标记当前图片
- `Enter`、`Esc` 或 `q`：返回网格

单图模式底部会显示：

- 当前模式
- 当前序号
- 标记状态
- 分辨率
- 文件大小
- 文件格式
- 修改时间

## 交互模型

- `Directory` 模式表示正在浏览当前目标目录中的全部图片
- `Selection` 模式表示正在浏览你在 Yazi 中对该目录已经选中的那部分图片
- 网格是连续滚动的，并不是严格锁在分页上的固定布局

## 限制

- 目前实现偏向 macOS
- 渲染依赖支持 Kitty graphics protocol 的终端
- 当前范围有意保持为本地、终端内图片浏览
- 这个插件更偏向图片筛选，不是文件编辑器或元数据编辑器

## 建议补充到 GitHub 的内容

- 添加一张截图或一个 GIF，展示网格和单图模式
- 给仓库加上 `yazi`、`yazi-plugin`、`terminal`、`gallery`、`macos` 等 topics

## 仓库说明

- 当前实现以终端优先
- 画廊会尽量留在与 Yazi 相同的终端会话中
- 插件优先采用低依赖和 macOS 原生工具链

## License

[MIT](./LICENSE)
