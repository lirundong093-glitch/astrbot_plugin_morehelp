import json
import os
import platform
import traceback
from PIL import Image, ImageDraw, ImageFont
from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import filter

@register("astrbot_plugin_morehelp", "YourName", "自定义帮助插件，支持指令增删并生成图片", "1.0.0")
class HelpPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.commands_file = os.path.join(os.path.dirname(__file__), "commands.json")
        self.pending_add = {}
        self._load_commands()
        self._load_config()
        self.font_path = self._get_system_font()
        print(f"[MoreHelp] 插件初始化完成，管理员ID: {self.admin_id}，字体路径: {self.font_path}")

    def _load_config(self):
        config_path = os.path.join(os.path.dirname(__file__), "_conf_schema.json")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                self.config = json.load(f)
        except Exception as e:
            print(f"[MoreHelp] 加载配置文件失败: {e}")
            self.config = {"admin_id": ""}
        self.admin_id = str(self.config.get("admin_id", ""))

    def _load_commands(self):
        if os.path.exists(self.commands_file):
            try:
                with open(self.commands_file, "r", encoding="utf-8") as f:
                    self.commands = json.load(f)
            except Exception as e:
                print(f"[MoreHelp] 加载指令文件失败: {e}")
                self.commands = {}
        else:
            self.commands = {}

    def _save_commands(self):
        try:
            with open(self.commands_file, "w", encoding="utf-8") as f:
                json.dump(self.commands, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[MoreHelp] 保存指令文件失败: {e}")

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
                print(f"[MoreHelp] 使用系统路径找到字体: {path}")
                return path
        print("[MoreHelp] 未找到任何中文字体，将使用默认字体。")
        return ""

    @filter.on_message()
    async def run(self, event: AstrMessageEvent) -> MessageEventResult:
        """插件主入口，通过 on_message 过滤器捕获所有消息"""
        print(f"[MoreHelp] run 方法被调用，消息内容: '{event.get_message_text()}'")
        try:
            msg = event.get_message_text().strip()
            user_id = str(event.get_sender_id())
            session_id = event.get_session_id()

            print(f"[MoreHelp] 处理消息: '{msg}' from {user_id} session {session_id}")

            # 情况1：等待添加说明状态
            if session_id in self.pending_add:
                print(f"[MoreHelp] 检测到 session {session_id} 处于等待添加状态，指令: {self.pending_add[session_id]}")
                if not self._is_admin(user_id):
                    del self.pending_add[session_id]
                    yield event.plain_result("权限不足，操作已取消。")
                    return

                cmd_name = self.pending_add.pop(session_id)
                description = msg
                if not description:
                    yield event.plain_result("说明不能为空，添加操作已取消。")
                    return

                self.commands[cmd_name] = description
                self._save_commands()
                yield event.plain_result(f"指令 {cmd_name} 已成功添加。")
                return

            # 情况2：匹配主命令
            if msg.startswith("/帮助") or msg.startswith("/help"):
                print(f"[MoreHelp] 匹配到命令: {msg}")
                if not self._is_admin(user_id):
                    yield event.plain_result(f"权限不足，仅管理员可用。当前用户ID: {user_id}，管理员ID: {self.admin_id}")
                    return

                parts = msg.split(maxsplit=2)

                if len(parts) == 1:
                    try:
                        img_path = self._generate_help_image()
                        if img_path and os.path.exists(img_path):
                            yield event.image_result(img_path)
                        else:
                            yield event.plain_result("生成帮助图片失败：图片文件不存在。")
                    except Exception as e:
                        error_msg = f"生成帮助图片时出错: {str(e)}"
                        print(f"[MoreHelp] {error_msg}\n{traceback.format_exc()}")
                        yield event.plain_result(error_msg)
                    return

                sub_cmd = parts[1].lower()

                if sub_cmd == "add":
                    if len(parts) < 3:
                        yield event.plain_result("用法: /帮助 add <指令名称>")
                        return
                    cmd_name = parts[2].strip()
                    if not cmd_name.startswith("/"):
                        cmd_name = "/" + cmd_name
                    self.pending_add[session_id] = cmd_name
                    yield event.plain_result(f"请输入指令 {cmd_name} 的说明：")
                    return

                elif sub_cmd == "remove":
                    if len(parts) < 3:
                        yield event.plain_result("用法: /帮助 remove <指令名称>")
                        return
                    cmd_name = parts[2].strip()
                    if not cmd_name.startswith("/"):
                        cmd_name = "/" + cmd_name
                    if cmd_name in self.commands:
                        del self.commands[cmd_name]
                        self._save_commands()
                        yield event.plain_result(f"指令 {cmd_name} 已删除。")
                    else:
                        yield event.plain_result(f"未找到指令 {cmd_name}，请检查输入是否正确。")
                    return

                else:
                    yield event.plain_result("未知子命令，可用: add / remove")
                    return

            # 非本插件命令，不响应
            print(f"[MoreHelp] 命令不匹配，忽略。")
        except Exception as e:
            error_msg = f"插件运行异常: {str(e)}\n{traceback.format_exc()}"
            print(f"[MoreHelp] {error_msg}")
            yield event.plain_result(f"插件内部错误: {str(e)}")

    def _generate_help_image(self) -> str:
        img_path = os.path.join(os.path.dirname(__file__), "help_temp.png")
        try:
            font = None
            if self.font_path:
                try:
                    font = ImageFont.truetype(self.font_path, 18)
                except Exception as e:
                    print(f"[MoreHelp] 加载字体失败 {self.font_path}: {e}，使用默认字体。")
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
            print(f"[MoreHelp] 图片已保存至: {img_path}")
            return img_path
        except Exception as e:
            print(f"[MoreHelp] 生成图片失败: {e}\n{traceback.format_exc()}")
            raise

    async def terminate(self):
        pass
