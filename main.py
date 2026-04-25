import json
import os
import platform
import traceback
from PIL import Image, ImageDraw, ImageFont
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

@register("astrbot_plugin_morehelp", "Lucy", "自定义帮助插件，支持指令增删并生成图片", "1.0.0")
class HelpPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.commands_file = os.path.join(os.path.dirname(__file__), "commands.json")
        self.pending_add = {}
        self._load_commands()
        self.font_path = self._get_system_font()
        self.pending_add_skip_msg = {}

        if config is None:
            config = {}
        self.config = config
        self.admin_id = str(config.get("admin_id", ""))

         # ----- 清理上一次生成的帮助图片缓存 -----
        img_cache = os.path.join(os.path.dirname(__file__), "help_temp.png")
        if os.path.exists(img_cache):
            try:
                os.remove(img_cache)
                logger.info("[MoreHelp] 已删除旧的 help_temp.png 缓存")
            except Exception as e:
                logger.warning(f"[MoreHelp] 删除旧图片缓存失败: {e}")
                
        logger.info(f"[MoreHelp] 插件初始化完成，管理员ID: {self.admin_id}，字体路径: {self.font_path}")

    # ----- 数据层 -----
    def _load_commands(self):
        if os.path.exists(self.commands_file):
            try:
                with open(self.commands_file, "r", encoding="utf-8") as f:
                    self.commands = json.load(f)
            except Exception as e:
                logger.error(f"[MoreHelp] 加载指令文件失败: {e}")
                self.commands = {}
        else:
            self.commands = {}

    def _save_commands(self):
        try:
            with open(self.commands_file, "w", encoding="utf-8") as f:
                json.dump(self.commands, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[MoreHelp] 保存指令文件失败: {e}")

    def _is_admin(self, user_id: str) -> bool:
        return str(user_id) == self.admin_id

    # ----- 字体 -----
    def _get_system_font(self) -> str:
        plugin_dir = os.path.dirname(__file__)
        local_font = os.path.join(plugin_dir, "fonts", "qweather-icons.ttf")
        if os.path.exists(local_font):
            logger.info(f"[MoreHelp] 使用本地字体: {local_font}")
            return local_font
        
        system = platform.system()
        font_paths = []
        if system == "Windows":
            font_dir = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts")
            font_paths = [
                os.path.join(font_dir, "msyh.ttc"),
                os.path.join(font_dir, "simhei.ttf"),
                os.path.join(font_dir, "simsun.ttc"),
            ]
        elif system == "Darwin":
            font_paths = [
                "/System/Library/Fonts/PingFang.ttc",
                "/System/Library/Fonts/STHeiti Light.ttc",
                "/Library/Fonts/Arial Unicode.ttf",
            ]
        elif system == "Linux":
            font_paths = [
                "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
                "/usr/share/fonts/truetype/noto/NotoSerifCJK-Regular.ttc",
                "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
                "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ]
        for path in font_paths:
            if os.path.exists(path):
                logger.info(f"[MoreHelp] 使用系统路径找到字体: {path}")
                return path
        logger.warning("[MoreHelp] 未找到任何中文字体，将使用默认字体。")
        return ""

    def _get_font(self, size: int) -> ImageFont.FreeTypeFont:
        font_path = self.font_path
        if font_path:
            try:
                return ImageFont.truetype(font_path, size)
            except Exception as e:
                logger.error(f"[MoreHelp] 无法加载字体 {font_path}: {e}")
        return ImageFont.load_default()

    # ===== 唯一入口 =====
    @filter.command("帮助")
    async def help_command(self, event: AstrMessageEvent):
        """统一处理 /帮助、/帮助 add、/帮助 remove"""
        msg = event.message_str.strip()
        tokens = msg.split()
        if tokens and tokens[0] in ("帮助", "/帮助"):
            tokens = tokens[1:]   # 去掉命令本身

        if not tokens:
            # 纯 /帮助 → 生成图片
            user_id = str(event.get_sender_id())
            logger.info(f"[MoreHelp] 收到 /帮助 指令，来自用户: {user_id}")
            try:
                img_path = self._generate_help_image()
                if img_path and os.path.exists(img_path):
                    yield event.image_result(img_path)
                else:
                    yield event.plain_result("生成帮助图片失败：图片文件不存在。")
            except Exception as e:
                logger.error(f"[MoreHelp] 生成帮助图片出错: {e}\n{traceback.format_exc()}")
                yield event.plain_result(f"生成帮助图片时出错: {str(e)}")
            return

        # 以下代码必须在 if not tokens 同级（即缩进 8 空格，在方法内部直接定义）
        sub_cmd = tokens[0].lower()
        args = tokens[1:]

        if sub_cmd == "add":
            if not self._is_admin(event.get_sender_id()):
                yield event.plain_result("权限不足，仅管理员可添加指令。")
                return
            if not args:
                yield event.plain_result("用法: /帮助 add <指令名称>")
                return
            # 将剩余参数全部拼成指令名称（例如 "weather 城市"）
            raw_cmd = " ".join(args).strip()
            cmd_display = raw_cmd.lstrip("/")
            cmd_key = "/" + cmd_display

            session_id = event.get_session_id()
            self.pending_add[session_id] = (cmd_key, cmd_display)
            self.pending_add_skip_msg[session_id] = event.message_str.strip()
            yield event.plain_result("请发送该指令的说明：")

        elif sub_cmd == "remove":
            if not self._is_admin(event.get_sender_id()):
                yield event.plain_result("权限不足，仅管理员可删除指令。")
                return
            if not args:
                yield event.plain_result("用法: /帮助 remove <指令名称>")
                return
            # 同样拼接完整指令名
            raw_cmd = " ".join(args).strip()
            cmd_display = raw_cmd.lstrip("/")
            cmd_key = "/" + cmd_display

            if cmd_key in self.commands:
                del self.commands[cmd_key]
                self._save_commands()
                yield event.plain_result(f"指令 {cmd_display} 已删除。")
            else:
                yield event.plain_result(f"未找到指令 {cmd_display}，请检查输入是否正确。")

        else:
            yield event.plain_result(f"未知子命令: {sub_cmd}，可用命令: add, remove")

    # ===== 接收指令说明（第二步）=====
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_message(self, event: AstrMessageEvent):
        # 忽略机器人自己的消息
        if str(event.get_self_id()) == str(event.get_sender_id()):
            return

        session_id = event.get_session_id()
        msg_text = event.message_str.strip()

        # 核心修复：跳过触发 /帮助 add 的那条原始消息，防止它被当作说明
        if session_id in self.pending_add_skip_msg and msg_text == self.pending_add_skip_msg[session_id]:
            return

        # 没有待添加的指令，不做处理
        if session_id not in self.pending_add:
            self.pending_add_skip_msg.pop(session_id, None)
            return

        # 再次校验管理员权限
        if not self._is_admin(event.get_sender_id()):
            del self.pending_add[session_id]
            self.pending_add_skip_msg.pop(session_id, None)
            yield event.plain_result("权限不足，操作已取消。")
            return

        cmd_key, cmd_display = self.pending_add.pop(session_id)
        description = msg_text
        self.pending_add_skip_msg.pop(session_id, None)

        if not description or description.startswith("请发送"):
            yield event.plain_result("说明不能为空，操作已取消。")
            return

        self.commands[cmd_key] = description
        self._save_commands()
        yield event.plain_result(f"指令 {cmd_display} 已成功添加。")

    # ===== 图片生成 =====
    def _generate_help_image(self) -> str:
        img_path = os.path.join(os.path.dirname(__file__), "help_temp.png")
        try:
            title_font = self._get_font(22)      # 标题略大
            header_font = self._get_font(18)     # 表头字体
            font = self._get_font(18)            # 正文字体

            # 颜色定义 (均为 RGB 三元组)
            bg_color = (253, 246, 227)          # #FDF6E3
            header_bg = (238, 232, 213)         # #EEE8D5
            header_text_color = (92, 79, 60)    # #5C4F3C
            line_color = (214, 202, 176)        # #D6CAB0
            desc_color = (79, 74, 66)           # #4F4A42
            cmd_color = (107, 88, 118)          # #6B5876

            # 辅助函数：获取文本宽度与高度 (基于 getbbox)
            def text_size(txt, fnt):
                bbox = fnt.getbbox(txt)
                return bbox[2] - bbox[0], bbox[3] - bbox[1]   # 宽度, 高度

            # 常量布局参数
            left_margin = 30
            top_margin = 20
            title_bottom_spacing = 20
            col_padding_h = 12          # 列内水平内边距
            row_padding_v = 8           # 行垂直内边距
            line_width = 2              # 分割线粗细

            # 计算行高 (基于正文字体)
            metrics = font.getmetrics()
            row_height = metrics[0] + metrics[1] + 2 * row_padding_v  # ascent + descent + padding
            header_height = row_height  # 表头与数据行等高

            # 计算需要绘制的指令行 (支持空指令)
            commands = list(self.commands.items()) if self.commands else [("暂无指令", "")]
            empty_mode = not self.commands

            # 计算列宽：分别取指令名称和描述的最大宽度
            max_cmd_w = 0
            max_desc_w = 0
            for cmd, desc in commands:
                cw, _ = text_size(cmd, font)
                if cw > max_cmd_w:
                    max_cmd_w = cw
                dw, _ = text_size(desc, font)
                if dw > max_desc_w:
                    max_desc_w = dw

            # 表头文字宽度
            hcmd_w, _ = text_size("Commands", header_font)
            hdesc_w, _ = text_size("Description", header_font)
            max_cmd_w = max(max_cmd_w, hcmd_w)
            max_desc_w = max(max_desc_w, hdesc_w)

            # 列总宽 (内容 + 水平内边距*2)
            cmd_col_w = max_cmd_w + 2 * col_padding_h
            desc_col_w = max_desc_w + 2 * col_padding_h
            table_width = cmd_col_w + desc_col_w

            # 图片尺寸
            title_text = "指令表"
            title_w, title_h = text_size(title_text, title_font)
            img_width = max(title_w, table_width) + 2 * left_margin
            # 计算表格部分高度
            table_x = left_margin
            table_y = top_margin + title_h + title_bottom_spacing  # 表格起始 y
            # 表头 + 数据行高度
            data_rows_height = len(commands) * row_height
            table_height = header_height + data_rows_height
            img_height = table_y + table_height + 20   # 底部留白

            # 创建画布
            img = Image.new("RGB", (img_width, img_height), bg_color)
            draw = ImageDraw.Draw(img)

            # 1. 绘制标题 (居中)
            title_x = (img_width - title_w) // 2
            draw.text((title_x, top_margin), title_text, fill=header_text_color, font=title_font)

            # 2. 绘制表头背景
            header_rect = (table_x, table_y, table_x + table_width, table_y + header_height)
            draw.rectangle(header_rect, fill=header_bg)

            # 表头文字
            cmd_header_x = table_x + col_padding_h
            desc_header_x = table_x + cmd_col_w + col_padding_h
            # 垂直居中
            header_text_y = table_y + (header_height - header_font.getmetrics()[0] - header_font.getmetrics()[1]) // 2 + header_font.getmetrics()[0]
            draw.text((cmd_header_x, table_y + row_padding_v), "Commands", fill=header_text_color, font=header_font)
            draw.text((desc_header_x, table_y + row_padding_v), "Description", fill=header_text_color, font=header_font)

            # 3. 绘制数据行
            y = table_y + header_height
            for i, (cmd, desc) in enumerate(commands):
                # 指令名称 (特殊颜色)
                draw.text((cmd_header_x, y + row_padding_v), cmd, fill=cmd_color, font=font)
                # 描述 (空指令时可能跨列显示“暂无指令”)
                if empty_mode:
                    # 跨整行居中显示
                    dw, _ = text_size("暂无指令", font)
                    draw.text((table_x + (table_width - dw) // 2, y + row_padding_v), "暂无指令",
                              fill=desc_color, font=font)
                else:
                    draw.text((desc_header_x, y + row_padding_v), desc, fill=desc_color, font=font)
                    y += row_height

            # 4. 绘制内部分割线
            # 竖线：从表头顶端到最后一个数据行底端
            line_x = table_x + cmd_col_w
            draw.line([(line_x, table_y), (line_x, table_y + table_height)],
                      fill=line_color, width=line_width)

            # 横线：在数据行之间 (最后一行下方不画)
            if not empty_mode and len(commands) > 1:
                for i in range(len(commands) - 1):
                    line_y = table_y + header_height + (i + 1) * row_height
                    draw.line([(table_x, line_y), (table_x + table_width, line_y)],
                          fill=line_color, width=line_width)

            img.save(img_path)
            logger.info(f"[MoreHelp] 图片已保存至: {img_path}")
            return img_path
        except Exception as e:
            logger.error(f"[MoreHelp] 生成图片失败: {e}\n{traceback.format_exc()}")
            raise


    async def terminate(self):
        pass
