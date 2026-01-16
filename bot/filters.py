from aiogram.filters import BaseFilter
from aiogram.types import Message
from .settings import settings

class InTargetGroupFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return bool(message.chat and message.chat.id == settings.TARGET_GROUP_ID)

class OwnerOnlyFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        if not settings.OWNER_ONLY_MODE:
            return True
        return bool(message.from_user and message.from_user.id == settings.OWNER_USER_ID)
