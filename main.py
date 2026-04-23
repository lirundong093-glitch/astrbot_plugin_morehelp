import json
import os
from PIL import Image, ImageDraw, ImageFont
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api.message import MessageEvent

class HelpPlugin(Plugin):
    def __init__(self, context: Context):
        super().__init__(context)
        self.commands_file = os.path.join(os.path.dirname(__file__), "commands.json")
        self.pending_add = {}  # 暂存等待输入说明的用户 session_id
        self._load_commands()
        self._load_config()

    def _load_config(self):
        """从 _conf_schema.json 读取管理员ID"""
        config_path = os.path.join(os.path.dirname(__file__), "_conf_schema.json")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                self.config = json.load(f)
        except:
            self.config = {"admin_id": ""}
        self.admin_id = self.config.get("admin_id", "")

    def _load_commands(self):
        """加载已保存的指令数据"""
        if os.path.exists(self.commands_file):
            with open(self.commands_file, "r", encoding="utf-8") as f:
                self.commands = json.load(f)
        else:
            self.commands = {}

    def _save_commands(self):
        with open(self.commands_file, "w", encoding="utf-8") as f:
            json.dump(self.commands, f, ensure_ascii=False, indent=2)

    def _is_admin(self, user_id: str) -> bool:
        return user_id == self.admin_id

    @on_command("/帮助", aliases=["/help"])
    async def help_command(self, event: MessageEvent):
        user_id = str(event.get_sender_id())
        if not self._is_admin(user_id):
            await event.reply("权限不足，仅管理员可用。")
            return

        raw = event.get_message_text().strip()
        parts = raw.split(maxsplit=2)
        # 只有 /帮助 时生成图片
        if len(parts) == 1:
            img_path = self._generate_help_image()
            await event.reply_image(img_path)
            return

        sub_cmd = parts[1]
        if sub_cmd == "add":
            if len(parts) < 3:
                await event.reply("用法: /帮助 add <指令名称>")
                return
            cmd_name = parts[2].strip()
            if not cmd_name.startswith("/"):
                cmd_name = "/" + cmd_name
            # 记录该用户等待输入说明
            self.pending_add[event.get_session_id()] = cmd_name
            await event.reply("请输入该指令的说明：")
            return

        elif sub_cmd == "remove":
            if len(parts) < 3:
                await event.reply("用法: /帮助 remove <指令名称>")
                return
            cmd_name = parts[2].strip()
            if not cmd_name.startswith("/"):
                cmd_name = "/" + cmd_name
            if cmd_name in self.commands:
                del self.commands[cmd_name]
                self._save_commands()
                await event.reply("指令已消除")
            else:
                await event.reply("未找到指令，请检查输入是否正确")
            return

        else:
            await event.reply("未知子命令，可用: add / remove")
            return

    @on_command("任意消息")  # 用于捕获添加时的说明输入
    async def catch_description(self, event: MessageEvent):
        session_id = event.get_session_id()
        if session_id not in self.pending_add:
            return  # 不是等待输入的状态

        user_id = str(event.get_sender_id())
        if not self._is_admin(user_id):
            await event.reply("权限不足，仅管理员可用。")
            del self.pending_add[session_id]
            return

        cmd_name = self.pending_add[session_id]
        description = event.get_message_text().strip()
        if not description:
            await event.reply("说明不能为空，请重新输入：")
            return

        self.commands[cmd_name] = description
        self._save_commands()
        del self.pending_add[session_id]
        await event.reply(f"指令 {cmd_name} 已添加。")

    def _generate_help_image(self) -> str:
        """生成白色背景的帮助图片，返回临时文件路径"""
        if not self.commands:
            # 无指令时生成简单提示图
            img = Image.new("RGB", (400, 100), color="white")
            draw = ImageDraw.Draw(img)
            try:
                font = ImageFont.truetype("simhei.ttf", 20)
            except:
                font = ImageFont.load_default()
            draw.text((20, 40), "暂无帮助指令", fill="black", font=font)
        else:
            # 计算所需高度
            try:
                font = ImageFont.truetype("simhei.ttf", 18)
            except:
                font = ImageFont.load_default()
            line_height = 30
            max_width = 500
            # 先计算最长行宽
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

        # 保存图片
        img_path = os.path.join(os.path.dirname(__file__), "help_temp.png")
        img.save(img_path)
        return img_path

    async def teardown(self):
        pass
