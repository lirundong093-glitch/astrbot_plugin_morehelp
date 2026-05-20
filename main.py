import json
import os
import platform
import traceback
from PIL import Image, ImageDraw, ImageFont
from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.event.filter import EventMessageType
from astrbot.api.star import Context, Star
from astrbot.api import logger
from astrbot.api.message_components import Image as CompImage


class HelpPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        if config is None:
            config = {}

        # 持久化目录 → data/plugin_data/
        self.data_dir = os.path.join("data", "plugin_data", "astrbot_plugin_morehelp")
        os.makedirs(self.data_dir, exist_ok=True)
        self.commands_file = os.path.join(self.data_dir, "commands.json")

        self.pending_add = {}
        self.pending_add_skip_msg = {}
        self._load_commands()
        self.font_path = self._get_system_font()
        self.admin_id = str(config.get("admin_id", ""))

        # 清理旧缓存图片
        old_cache = os.path.join(os.path.dirname(__file__), "help_temp.png")
        if os.path.exists(old_cache):
            try:
                os.remove(old_cache)
            except OSError:
                pass
        logger.info(f"[MoreHelp] 初始化完成，管理员ID: {self.admin_id}")

    # ----- 数据层 -----
    def _load_commands(self):
        if os.path.exists(self.commands_file):
            try:
                with open(self.commands_file, "r", encoding="utf-8") as f:
                    self.commands = json.load(f)
            except Exception as e:
                logger.error(f"[MoreHelp] 加载指令失败: {e}")
                self.commands = {}
        else:
            self.commands = {}

    def _save_commands(self):
        try:
            with open(self.commands_file, "w", encoding="utf-8") as f:
                json.dump(self.commands, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[MoreHelp] 保存指令失败: {e}")

    def _is_admin(self, user_id: str) -> bool:
        return str(user_id) == self.admin_id

    # ----- 字体 -----
    def _get_system_font(self) -> str:
        plugin_dir = os.path.dirname(__file__)
        local_font = os.path.join(plugin_dir, "fonts", "qweather-icons.ttf")
        if os.path.exists(local_font):
            return local_font
        system = platform.system()
        if system == "Windows":
            font_dir = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts")
            paths = [os.path.join(font_dir, f) for f in ["msyh.ttc", "simhei.ttf", "simsun.ttc"]]
        elif system == "Darwin":
            paths = ["/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Light.ttc"]
        else:
            paths = [
                "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
                "/usr/share/fonts/truetype/noto/NotoSerifCJK-Regular.ttc",
                "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ]
        for p in paths:
            if os.path.exists(p):
                return p
        return ""

    def _get_font(self, size: int) -> ImageFont.FreeTypeFont:
        if self.font_path:
            try:
                return ImageFont.truetype(self.font_path, size)
            except Exception:
                pass
        return ImageFont.load_default()

    # ===== 指令入口 =====
    @filter.command("帮助")
    async def help_command(self, event: AstrMessageEvent):
        msg = event.message_str.strip()
        tokens = msg.split()
        if tokens and tokens[0] in ("帮助", "/帮助"):
            tokens = tokens[1:]

        if not tokens:
            user_id = str(event.get_sender_id())
            logger.info(f"[MoreHelp] /帮助 请求，来自 {user_id}")
            try:
                img_path = self._generate_help_image()
                if img_path and os.path.exists(img_path):
                    yield event.chain_result([CompImage(file=img_path)])
                else:
                    yield event.plain_result("生成帮助图片失败。")
            except Exception as e:
                logger.error(f"[MoreHelp] 生成图片出错: {e}\n{traceback.format_exc()}")
                yield event.plain_result(f"生成帮助图片时出错: {e}")
            return

        sub_cmd = tokens[0].lower()
        args = tokens[1:]

        if sub_cmd == "add":
            if not self._is_admin(event.get_sender_id()):
                yield event.plain_result("权限不足，仅管理员可添加指令。")
                return
            if not args:
                yield event.plain_result("用法: /帮助 add <指令名称>")
                return
            raw_cmd = " ".join(args).strip()
            cmd_key = "/" + raw_cmd.lstrip("/")
            session_id = event.get_session_id()
            self.pending_add[session_id] = (cmd_key, raw_cmd)
            self.pending_add_skip_msg[session_id] = event.message_str.strip()
            yield event.plain_result("请发送该指令的说明：")

        elif sub_cmd == "remove":
            if not self._is_admin(event.get_sender_id()):
                yield event.plain_result("权限不足，仅管理员可删除指令。")
                return
            if not args:
                yield event.plain_result("用法: /帮助 remove <指令名称>")
                return
            raw_cmd = " ".join(args).strip()
            cmd_key = "/" + raw_cmd.lstrip("/")
            if cmd_key in self.commands:
                del self.commands[cmd_key]
                self._save_commands()
                yield event.plain_result(f"指令 {raw_cmd} 已删除。")
            else:
                yield event.plain_result(f"未找到指令 {raw_cmd}。")
        else:
            yield event.plain_result(f"未知子命令: {sub_cmd}，可用: add, remove")

    # ===== 接收指令说明 =====
    @filter.event_message_type(EventMessageType.ALL)
    async def handle_message(self, event: AstrMessageEvent):
        if str(event.get_self_id()) == str(event.get_sender_id()):
            return
        session_id = event.get_session_id()
        if session_id not in self.pending_add:
            return

        msg_text = event.message_str.strip()
        if session_id in self.pending_add_skip_msg and msg_text == self.pending_add_skip_msg[session_id]:
            return

        if not self._is_admin(event.get_sender_id()):
            self.pending_add.pop(session_id, None)
            self.pending_add_skip_msg.pop(session_id, None)
            yield event.plain_result("权限不足，操作已取消。")
            return

        cmd_key, cmd_display = self.pending_add.pop(session_id)
        self.pending_add_skip_msg.pop(session_id, None)

        if not msg_text or msg_text.startswith("请发送"):
            yield event.plain_result("说明不能为空，操作已取消。")
            return

        self.commands[cmd_key] = msg_text
        self._save_commands()
        yield event.plain_result(f"指令 {cmd_display} 已成功添加。")

    # ===== 图片生成 =====
    def _generate_help_image(self) -> str:
        img_path = os.path.join(self.data_dir, "help_temp.png")
        title_font = self._get_font(22)
        header_font = self._get_font(18)
        font = self._get_font(18)

        bg_color = (253, 246, 227)
        header_bg = (238, 232, 213)
        header_text_color = (92, 79, 60)
        line_color = (214, 202, 176)
        desc_color = (79, 74, 66)
        cmd_color = (107, 88, 118)

        def text_size(txt, fnt):
            bbox = fnt.getbbox(txt)
            return bbox[2] - bbox[0], bbox[3] - bbox[1]

        left_margin, top_margin = 30, 20
        title_bottom_spacing = 20
        col_padding_h, row_padding_v, line_width = 12, 8, 2

        metrics = font.getmetrics()
        row_height = metrics[0] + metrics[1] + 2 * row_padding_v
        commands = list(self.commands.items()) if self.commands else [("暂无指令", "")]
        empty_mode = not self.commands

        max_cmd_w = max_desc_w = 0
        for cmd, desc in commands:
            max_cmd_w = max(max_cmd_w, text_size(cmd, font)[0])
            max_desc_w = max(max_desc_w, text_size(desc, font)[0])
        max_cmd_w = max(max_cmd_w, text_size("Commands", header_font)[0])
        max_desc_w = max(max_desc_w, text_size("Description", header_font)[0])

        cmd_col_w = max_cmd_w + 2 * col_padding_h
        desc_col_w = max_desc_w + 2 * col_padding_h
        table_width = cmd_col_w + desc_col_w

        title_w, title_h = text_size("指令表", title_font)
        img_width = max(title_w, table_width) + 2 * left_margin
        table_x = left_margin
        table_y = top_margin + title_h + title_bottom_spacing
        img_height = table_y + row_height + len(commands) * row_height + 20

        img = Image.new("RGB", (img_width, img_height), bg_color)
        draw = ImageDraw.Draw(img)

        draw.text(((img_width - title_w) // 2, top_margin), "指令表", fill=header_text_color, font=title_font)
        draw.rectangle((table_x, table_y, table_x + table_width, table_y + row_height), fill=header_bg)
        draw.text((table_x + col_padding_h, table_y + row_padding_v), "Commands", fill=header_text_color, font=header_font)
        desc_header_x = table_x + cmd_col_w + col_padding_h
        draw.text((desc_header_x, table_y + row_padding_v), "Description", fill=header_text_color, font=header_font)

        y = table_y + row_height
        for i, (cmd, desc) in enumerate(commands):
            draw.text((table_x + col_padding_h, y + row_padding_v), cmd, fill=cmd_color, font=font)
            if empty_mode:
                dw, _ = text_size("暂无指令", font)
                draw.text((table_x + (table_width - dw) // 2, y + row_padding_v), "暂无指令", fill=desc_color, font=font)
            else:
                draw.text((desc_header_x, y + row_padding_v), desc, fill=desc_color, font=font)
            y += row_height

        line_x = table_x + cmd_col_w
        draw.line((line_x, table_y, line_x, table_y + row_height + len(commands) * row_height), fill=line_color, width=line_width)
        if not empty_mode and len(commands) > 1:
            for i in range(len(commands) - 1):
                ly = table_y + row_height + (i + 1) * row_height
                draw.line((table_x, ly, table_x + table_width, ly), fill=line_color, width=line_width)

        img.save(img_path)
        logger.info(f"[MoreHelp] 图片已保存: {img_path}")
        return img_path

    async def terminate(self):
        pass
