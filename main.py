import json
import os
import platform
import traceback
from PIL import Image, ImageDraw, ImageFont
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core.star.filter.permission import PermissionType  # 引入权限类型

@register("astrbot_plugin_morehelp", "Lucy", "自定义帮助插件，支持指令增删并生成图片", "1.0.0")
class HelpPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.commands_file = os.path.join(os.path.dirname(__file__), "commands.json")
        self.pending_add = {}
        self._load_commands()

        # 配置已由框架自动注入，无需手动读取 _conf_schema.json
        if config is None:
            config = {}
        self.config = config
        self.admin_id = str(config.get("admin_id", ""))

        self.font_path = self._get_system_font()
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
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ]

        for path in font_paths:
            if os.path.exists(path):
                logger.info(f"[MoreHelp] 使用系统路径找到字体: {path}")
                return path

        logger.warning("[MoreHelp] 未找到任何中文字体，将使用默认字体。")
        return ""

    # ===== 指令处理 =====

    # 主指令：所有人可用（无 permission 参数，默认为无权限限制）
    @filter.command("帮助")
    async def help_command(self, event: AstrMessageEvent):
        """查看帮助图片，所有用户均可使用。"""
        user_id = str(event.get_sender_id())
        logger.info(f"[MoreHelp] 收到 /帮助 指令，来自用户: {user_id}")

        try:
            img_path = self._generate_help_image()
            if img_path and os.path.exists(img_path):
                yield event.image_result(img_path)
            else:
                yield event.plain_result("生成帮助图片失败：图片文件不存在。")
        except Exception as e:
            error_msg = f"生成帮助图片时出错: {str(e)}"
            logger.error(f"[MoreHelp] {error_msg}\n{traceback.format_exc()}")
            yield event.plain_result(error_msg)

    # 子指令：仅管理员可用
    @filter.command("帮助 add", permission=PermissionType.ADMIN)
    async def help_add_command(self, event: AstrMessageEvent):
        """添加新指令（管理员）。"""
        user_id = str(event.get_sender_id())
        session_id = event.get_session_id()

        parts = event.message_str.strip().split()
        if len(parts) < 3:
            yield event.plain_result("用法: /帮助 add <指令名称>")
            return

        cmd_name = parts[2]
        if not cmd_name.startswith("/"):
            cmd_name = "/" + cmd_name

        self.pending_add[session_id] = cmd_name
        yield event.plain_result(f"请输入指令 {cmd_name} 的说明：")

    # 子指令：仅管理员可用
    @filter.command("帮助 remove", permission=PermissionType.ADMIN)
    async def help_remove_command(self, event: AstrMessageEvent):
        """删除指令（管理员）。"""
        user_id = str(event.get_sender_id())

        parts = event.message_str.strip().split()
        if len(parts) < 3:
            yield event.plain_result("用法: /帮助 remove <指令名称>")
            return

        cmd_name = parts[2]
        if not cmd_name.startswith("/"):
            cmd_name = "/" + cmd_name

        if cmd_name in self.commands:
            del self.commands[cmd_name]
            self._save_commands()
            yield event.plain_result(f"指令 {cmd_name} 已删除。")
        else:
            yield event.plain_result(f"未找到指令 {cmd_name}，请检查输入是否正确。")

    # 监听所有消息，用于处理“添加指令说明”的第二步
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_message(self, event: AstrMessageEvent):
        """监听所有消息，处理添加指令的第二步骤（接收说明）。"""
        session_id = event.get_session_id()
        if session_id not in self.pending_add:
            return  # 不是处于等待状态的用户，忽略

        user_id = str(event.get_sender_id())
        # 手动校验权限（因为该监听器不是 command 装饰器，无法通过 permission 参数控制）
        if not self._is_admin(user_id):
            del self.pending_add[session_id]
            yield event.plain_result("权限不足，操作已取消。")
            return

        cmd_name = self.pending_add.pop(session_id)
        description = event.message_str.strip()
        if not description:
            yield event.plain_result("说明不能为空，添加操作已取消。")
            return

        self.commands[cmd_name] = description
        self._save_commands()
        yield event.plain_result(f"指令 {cmd_name} 已成功添加。")

    # ===== 图片生成 =====
    def _generate_help_image(self) -> str:
        img_path = os.path.join(os.path.dirname(__file__), "help_temp.png")
        try:
            font = None
            if self.font_path:
                try:
                    font = ImageFont.truetype(self.font_path, 18)
                except Exception as e:
                    logger.error(f"[MoreHelp] 加载字体失败 {self.font_path}: {e}，使用默认字体。")
                    font = ImageFont.load_default()
            else:
                font = ImageFont.load_default()

            if not self.commands:
                img = Image.new("RGB", (400, 100), color="white")
                draw = ImageDraw.Draw(img)
                title_font = None
                if self.font_path:
                    try:
                        title_font = ImageFont.truetype(self.font_path, 20)
                    except:
                        title_font = font
                else:
                    title_font = font
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
