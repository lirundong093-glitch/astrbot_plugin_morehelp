# 更多的帮助(astrbot_plugin_morehelp)

一个 AstrBot 自定义帮助插件，支持管理员动态增删指令并生成帮助图片。
<p align="center">
  <img src="https://img.shields.io/badge/version-v1.0.0-blue" alt="Version">
  <img src="https://img.shields.io/badge/Python-3.8%2B-blue" alt="Python">
  <img src="https://img.shields.io/badge/AstrBot-%E6%8F%92%E4%BB%B6%E6%A1%86%E6%9E%B6-brightgreen" alt="AstrBot">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
</p>
<div align="center">

[![Morehelp](https://count.getloli.com/get/@lirundong093-glitch?theme=gelbooru)](https://github.com/lirundong093-glitch/astrbot_plugin_morehelp)

</div>

## 功能

- **图片化帮助菜单**：发送 `/帮助` 自动生成包含所有已注册指令及说明的 PNG 图片
- **动态添加指令**：管理员使用 `/帮助 add <指令>` 后，按提示发送描述即可实时添加
- **动态删除指令**：管理员使用 `/帮助 remove <指令>` 即可删除
- **权限控制**：添加/删除操作仅限配置中指定的管理员 ID
- **跨平台字体适配**：自动检测系统并使用合适的中文字体，确保显示正常

## 生成图片示例
<div align="center">

![image_to_show](https://github.com/lirundong093-glitch/astrbot_plugin_morehelp/blob/master/image_to_show.png?raw=true)

</div>

## 安装

将本仓库克隆或下载到 AstrBot 的 `plugins` 目录，或在 AstrBot 插件市场搜索 `morehelp` 安装。

## 配置

在插件配置中设置 `admin_id`（管理员的 QQ 号或其他平台 ID 字符串），例如："admin_id": "123456789"

## 使用

| 命令 | 说明 |
|------|------|
| `/帮助` | 查看当前所有帮助指令（生成图片） |
| `/帮助 add <指令>` | 添加一个新指令，随后按提示发送指令说明 |
| `/帮助 remove <指令>` | 删除一个已添加的指令 |

> 注意：添加与删除操作需要管理员权限，指令名称请勿带 `/` 前缀。

所有存储信息都在commands.json里面，直接按照示例格式修改再刷新插件亦可更改配置

## 示例

1. 管理员发送：  
   `/帮助 add 签到`  
   插件回复：“请发送该指令的说明：”  
   管理员发送：“每日签到获取积分”  
   插件回复：“指令 签到 已成功添加。”

2. 任意用户发送 `/帮助`，即可看到包含 `签到` 及说明的帮助图片。

## 📝 许可证

[MIT License](LICENSE)

---

## Supports

- [AstrBot Repo](https://github.com/AstrBotDevs/AstrBot)
- [AstrBot Plugin Development Docs (Chinese)](https://docs.astrbot.app/dev/star/plugin-new.html)
- [AstrBot Plugin Development Docs (English)](https://docs.astrbot.app/en/dev/star/plugin-new.html)

<p align="center">Made with ❤️ by <a href="https://github.com/lirundong093-glitch">Lucy</a></p>
