import asyncio
import os
import json
import tempfile
from typing import Optional, List
from datetime import datetime

import astrbot.api.message_components as Comp
from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
from astrbot.api.platform import Platform

from .config import PluginConfig
from .api_client import QWeatherClient
from .image_generator import WeatherImageGenerator
from .scheduler import WeatherScheduler
from .llm_guide import LLMGuideGenerator
from .holiday import HolidayChecker


@register("astrbot_plugin_everyday_weatherforecast", "Lucy", "和风天气预报插件", "1.1.1")
class WeatherPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.plugin_dir = os.path.dirname(os.path.abspath(__file__))

        # ---------- 核心：使用 AstrBot 原生配置系统 ----------
        self.config = PluginConfig(config, self.plugin_dir)

        # ---------- 和风天气 API 客户端 ----------
        self.api_client = QWeatherClient(
            self.config.qweather_key,
            self.config.api_host,
            self.plugin_dir,
            indices_types=self.config.indices_types
        )

        # ---------- 图片生成器 ----------
        self.image_generator = WeatherImageGenerator(plugin_dir=self.plugin_dir)

        # ---------- 节假日检测器 ----------
        self.holiday_checker = HolidayChecker(
            cache_dir=self.plugin_dir,
            enabled=self.config.llm_enabled
        )

        # ---------- LLM 指南生成器 ----------
        if self.config.llm_enabled:
            self.llm_generator = LLMGuideGenerator(
                provider=self.config.llm_provider,
                api_key=self.config.llm_api_key,
                base_url=self.config.llm_base_url,
                model=self.config.llm_model,
                holiday_checker=self.holiday_checker
            )
        else:
            self.llm_generator = None

        # ---------- 定时任务调度器（调度器稍后在 start() 中配置） ----------
        self.scheduler = WeatherScheduler(timezone_str=self.config.timezone)
        # 直接绑定回调
        self.scheduler.set_callback(self._daily_push)
        
        # ---------- 立即启动调度器 ----------
        if self.config.daily_push_time:
            self.scheduler.update_schedule(self.config.daily_push_time)
        self.scheduler.start()
        jobs = self.scheduler.scheduler.get_jobs()
        logger.info(f"[Main] 调度器已启动（在 __init__ 中），当前任务数: {len(jobs)}")
        for job in jobs:
            logger.info(f"[Main] 任务: {job.id}, 下次运行: {job.next_run_time}")

        logger.info("和风天气预报插件已初始化")

    def _get_unified_origins(self) -> List[str]:
        """返回白名单中填写的完整会话标识符列表（直接用于发送）"""
        return self.config.whitelist_groups or []

    def _check_admin(self, event: AstrMessageEvent) -> bool:
        """检查消息发送者是否在插件管理员列表中，未配置则拒绝"""
        sender_id = event.get_sender_id()
        admin_users = self.config.admin_users
        if not admin_users:
            # 未配置管理员列表时，拒绝所有操作，引导配置
            return False
        return str(sender_id) in [str(uid) for uid in admin_users]

    async def _get_weather_image(self, city: str) -> Optional[bytes]:
        """根据城市获取天气数据并生成图片字节流"""
        weather_data = await self.api_client.get_complete_weather(city)
        if not weather_data:
            return None
        return self.image_generator.generate(weather_data)

    async def _daily_push(self):
        """每日定时推送任务（被调度器回调）"""
        logger.info(f"[DailyPush] ========== 开始执行每日天气推送 ==========")
        logger.info(f"[DailyPush] 当前时间: {datetime.now()}")
        logger.info(f"[DailyPush] 默认城市: {self.config.default_city}")

        # 1. 检查基本配置
        if not self.config.qweather_key or not self.config.api_host:
            logger.error("[DailyPush] API Key 或 Host 未配置，跳过推送")
            return

        if not self.config.whitelist_groups:
            logger.warning("[DailyPush] 白名单群列表为空，无法推送")
            return

        # 2. 获取天气数据并生成图片
        city = self.config.default_city or "北京"
        weather_data = await self.api_client.get_complete_weather(city)
        if not weather_data:
            logger.error("[DailyPush] 获取天气数据失败，中止")
            return

        image_bytes = self.image_generator.generate(weather_data)

        # 3. 生成 LLM 指南（可选）
        guide_text = ""
        if self.config.llm_enabled and self.llm_generator:
            guide_text = await self.llm_generator.generate_guide(
                city=city,
                weather_data=weather_data
            )

        # 4. 准备图片临时文件
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_file:
            tmp_file.write(image_bytes)
            tmp_path = tmp_file.name

        try:
            # 5. 向所有白名单群发送推送
            origins = self._get_unified_origins()
            success_count = 0
            for origin in origins:
                try:
                    # 构建图文消息链
                    image_chain = MessageChain() \
                        .message(f"☀️ 每日天气预报 - {city}") \
                        .file_image(tmp_path)
                    await self.context.send_message(origin, image_chain)

                    if guide_text:
                        await self.context.send_message(
                            origin,
                            MessageChain().message(guide_text)
                        )
                    success_count += 1
                    logger.info(f"[DailyPush] ✅ 成功向 {origin} 发送")
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.error(f"[DailyPush] ❌ 向 {origin} 发送失败: {e}", exc_info=True)

            logger.info(f"[DailyPush] 推送完成: {success_count}/{len(origins)}")
        finally:
            # 清理临时文件
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    # ==================== 指令注册 ====================

    @filter.command("weather")
    async def weather(self, event: AstrMessageEvent):
        """查询天气指令：/weather 或 /weather 城市名"""

        if not self.config.qweather_key or not self.config.api_host:
            yield event.plain_result("⚠️ 请先配置和风天气 API Key 和 API Host")
            return

        message = event.message_str.strip()
        parts = message.split(maxsplit=1)

        if len(parts) > 1:
            city = parts[1].strip()
        else:
            city = self.config.default_city

        if not city:
            yield event.plain_result("⚠️ 请指定城市名称，或先配置默认城市")
            return

        logger.info(f"查询天气: {city}")
        image_bytes = await self._get_weather_image(city)

        if not image_bytes:
            yield event.plain_result(f"❌ 无法获取「{city}」的天气信息")
            return

        chain = [
            Comp.Plain(f"📍 {city} 当前天气："),
            Comp.Image.fromBytes(image_bytes)
        ]
        yield event.chain_result(chain)

    @filter.command("weather_test_push")
    async def weather_test_push(self, event: AstrMessageEvent):
        """手动触发一次定时推送（调试用）"""
        logger.info("[TestPush] 收到手动推送指令")
        await self._daily_push()
        yield event.plain_result("✅ 手动推送已执行，请查看日志")

    @filter.command("weather_config")
    async def weather_config(self, event: AstrMessageEvent, key: str = None, value: str = None):
        """
        配置指令：/weather_config [key] [value]
        需要插件管理员权限。
        """
        # ---------- 管理员权限检查 ----------
        if not self._check_admin(event):
            yield event.plain_result("⛔ 权限不足：您不是插件管理员。请在 _conf_schema.json 的 admin_users 中添加您的 ID。")
            return

        if not key:
            # 显示当前配置
            whitelist_display = ', '.join(str(g) for g in self.config.whitelist_groups) if self.config.whitelist_groups else '全部群聊'
            admin_display = ', '.join(str(uid) for uid in self.config.admin_users) if self.config.admin_users else '未配置'
            info = f"""📋 当前配置：
• 和风天气 Key: {'已设置' if self.config.qweather_key else '❌ 未设置'}
• API Host: {self.config.api_host or '❌ 未设置'}
• 默认城市: {self.config.default_city}
• 推送时间: {self.config.daily_push_time}
• 白名单群: {whitelist_display}
• 管理员列表: {admin_display}
• LLM 指南: {'开启' if self.config.llm_enabled else '关闭'}
• LLM 提供商: {self.config.llm_provider}
• LLM 模型: {self.config.llm_model}
• 节假日功能: {'开启' if self.config.holiday_cache_enabled else '关闭'}"""
            yield event.plain_result(info)
            return

        if not value and key not in ["llm_enabled", "holiday_cache_enabled"]:
            yield event.plain_result("⚠️ 请提供配置值")
            return

        msg = self.config.update_config(key, value)

        # 实时应用某些配置变更
        if key == "qweather_key":
            self.api_client.api_key = value
        elif key == "api_host":
            self.api_client.api_host = value.strip()
            self.api_client._build_endpoints()
        elif key == "daily_push_time":
            self.scheduler.update_schedule(self.config.daily_push_time)
        elif key == "llm_enabled":
            enabled = value.lower() in ["true", "1", "yes", "on"]
            self.holiday_checker.enabled = enabled
            if enabled and not self.llm_generator:
                self.llm_generator = LLMGuideGenerator(
                    provider=self.config.llm_provider,
                    api_key=self.config.llm_api_key,
                    base_url=self.config.llm_base_url,
                    model=self.config.llm_model,
                    holiday_checker=self.holiday_checker
                )
            elif not enabled:
                self.llm_generator = None

        yield event.plain_result(msg)

    # ==================== 生命周期管理 ====================

    async def start(self):
        await super().start()
        logger.info("=== [Main] start() 被调用（调度器已在 __init__ 中启动）===")
    # 可以在此进行其他需要等待框架就绪的操作

    async def terminate(self):
        self.scheduler.shutdown()
        logger.info("和风天气预报插件已卸载")
