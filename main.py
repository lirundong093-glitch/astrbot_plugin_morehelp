import json
import os
import platform
import traceback
from PIL import Image, ImageDraw, ImageFont
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core.star.filter.permission import PermissionType

@register("astrbot_plugin_morehelp", "Lucy", "自定义帮助插件，支持指令增删并生成图片", "1.0.0")
class HelpPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.commands_file = os.path.join(os.path.dirname(__file__), "commands.json")
        self.pending_add = {}  # 键为 session_id，值为 (cmd_key, cmd_display)
        self._load_commands()
        self.font_path = self._get_system_font()

        # 配置由框架自动注入
        if config is None:
            config = {}
        self.config = config
        self.admin_id = str(config.get("admin_id", ""))

        logger.info(f"[MoreHelp] 插件初始化完成，管理员ID: {self.admin_id}，字体路径: {self.font_path}")

    # ===== 数据加载与保存 =====
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
                "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
                "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ]

        for path in font_paths:
            if os.path.exists(path):
                logger.info(f"[MoreHelp] 使用系统路径找到字体: {path}")
                return path

        logger.warning("[MoreHelp] 未找到任何中文字体，将使用默认字体。")
        return ""

    def _get_font(self, size: int) -> ImageFont.FreeTypeFont:
        """安全加载字体，失败则回退至默认字体。"""
        font_path = self.font_path
        if font_path:
            try:
                return ImageFont.truetype(font_path, size)
            except Exception as e:
                logger.error(f"[MoreHelp] 无法加载字体 {font_path}: {e}")
        return ImageFont.load_default()

    # ===== 指令处理 =====

    # 主指令：仅响应精确的 "/帮助" 或 "/help"
    @filter.command("帮助")
    async def help_command(self, event: AstrMessageEvent):
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

    # 添加指令：管理员专用
    @filter.command("帮助 add", permission=PermissionType.ADMIN)
    async def help_add_command(self, event: AstrMessageEvent):
        """管理员添加新指令。"""
        parts = event.message_str.strip().split()
        if len(parts) < 3:
            yield event.plain_result("用法: /帮助 add <指令名称>")
            return

        raw_cmd = parts[2].strip()
        if not raw_cmd:
            yield event.plain_result("用法: /帮助 add <指令名称>")
            return

        # 统一内部存储格式：始终以 "/" 开头
        cmd_display = raw_cmd.lstrip("/")  # 用户看到的名称（无 /）
        cmd_key = "/" + cmd_display        # 存储及图片中使用的名称

        session_id = event.get_session_id()
        # 暂存显示名，稍后用于成功提示
        self.pending_add[session_id] = (cmd_key, cmd_display)

        # 先确认已记录指令名，再请求说明
        yield event.plain_result(f"已记录指令名称：{cmd_display}")
        yield event.plain_result("请发送该指令的说明：")

    # 删除指令：管理员专用
    @filter.command("帮助 remove", permission=PermissionType.ADMIN)
    async def help_remove_command(self, event: AstrMessageEvent):
        """管理员删除指定指令。"""
        parts = event.message_str.strip().split()
        if len(parts) < 3:
            yield event.plain_result("用法: /帮助 remove <指令名称>")
            return

        raw_cmd = parts[2].strip()
        if not raw_cmd:
            yield event.plain_result("用法: /帮助 remove <指令名称>")
            return

        # 统一内部存储格式
        cmd_display = raw_cmd.lstrip("/")
        cmd_key = "/" + cmd_display

        if cmd_key in self.commands:
            del self.commands[cmd_key]
            self._save_commands()
            yield event.plain_result(f"指令 {cmd_display} 已删除。")
        else:
            yield event.plain_result(f"未找到指令 {cmd_display}，请检查输入是否正确。")

    # 监听所有消息，用于接收“添加指令”的第二步说明
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_message(self, event: AstrMessageEvent):
        """处理添加指令的第二步骤（接收用户发送的说明）。"""
        # 忽略机器人自己发出的消息，避免误触发
        if event.get_self_id() == event.get_sender_id():
            return

        session_id = event.get_session_id()
        if session_id not in self.pending_add:
            return

        # 权限校验（手动，因为该监听器非 command 装饰器）
        if not self._is_admin(event.get_sender_id()):
            del self.pending_add[session_id]
            yield event.plain_result("权限不足，操作已取消。")
            return

        cmd_key, cmd_display = self.pending_add.pop(session_id)
        description = event.message_str.strip()
        if not description:
            yield event.plain_result("说明不能为空，操作已取消。")
            return

        self.commands[cmd_key] = description
        self._save_commands()
        yield event.plain_result(f"指令 {cmd_display} 已成功添加。")

    # ===== 帮助图片生成 =====
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
                max_text_width = 0
                for cmd, desc in self.commands.items():
                    text = f"{cmd}    {desc}"
                    bbox = font.getbbox(text)
                    text_width = bbox[2] - bbox[0]
                    if text_width > max_text_width:
                        max_text_width = text_width
                img_width = max(max_text_width + 40, 300)
                img_height = len(self.commands) * line_height + 20
                img = Image.new("RGB", (img_width, img_height), color="white")
                draw = ImageDraw.Draw(img)
                y = 10
                for cmd, desc in self.commands.items():
                    text = f"{cmd}    {desc}"
                    draw.text((20, y), text, fill="black", font=font)
                    y += line_height

            img.save(img_path)
            logger.info(f"[MoreHelp] 图片已保存至: {img_path}")
            return img_path
        except Exception as e:
            logger.error(f"[MoreHelp] 生成图片失败: {e}\n{traceback.format_exc()}")
            raise

    async def terminate(self):
        pass
