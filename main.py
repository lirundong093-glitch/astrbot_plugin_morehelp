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
        else:
            font_paths = [
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
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
            raw_cmd = args[0].strip()
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
            raw_cmd = args[0].strip()
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
            font = self._get_font(18)
            title_font = self._get_font(20)

            if not self.commands:
                img = Image.new("RGB", (400, 100), color="white")
                draw = ImageDraw.Draw(img)
                draw.text((20, 40), "暂无帮助指令", fill="black", font=title_font)
            else:
                line_height = 30
                # 计算所有指令名称的最大绘制宽度
                max_cmd_width = 0
                for cmd in self.commands.keys():
                    bbox = font.getbbox(cmd)          # 仅计算指令名字本身
                    cmd_width = bbox[2] - bbox[0]
                    if cmd_width > max_cmd_width:
                        max_cmd_width = cmd_width

                # 说明文字的起始 x 坐标（指令最大宽度 + 右侧间距）
                desc_x = 20 + max_cmd_width + 15   # 15 是额外间距

                # 计算整张图片的宽度：说明从 desc_x 开始，需要能容纳最长的说明文本
                max_desc_width = 0
                for desc in self.commands.values():
                    bbox = font.getbbox(desc)
                    desc_width = bbox[2] - bbox[0]
                    if desc_width > max_desc_width:
                        max_desc_width = desc_width

                img_width = max(desc_x + max_desc_width + 20, 300)
                img_height = len(self.commands) * line_height + 20

                img = Image.new("RGB", (img_width, img_height), color="white")
                draw = ImageDraw.Draw(img)

                y = 10
                for cmd, desc in self.commands.items():
                    # 绘制指令名称（左对齐）
                    draw.text((20, y), cmd, fill="black", font=font)
                    # 绘制说明（从统一位置开始，保证对齐）
                    draw.text((desc_x, y), desc, fill="black", font=font)
                    y += line_height

            img.save(img_path)
            logger.info(f"[MoreHelp] 图片已保存至: {img_path}")
            return img_path
        except Exception as e:
            logger.error(f"[MoreHelp] 生成图片失败: {e}\n{traceback.format_exc()}")
            raise


    async def terminate(self):
        pass
