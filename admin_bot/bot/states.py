from aiogram.fsm.state import StatesGroup, State


class AddAdminFlow(StatesGroup):
    waiting_link = State()
    waiting_name = State()


class NetworkFlow(StatesGroup):
    waiting_name = State()
    waiting_links = State()


class RefreshChannelsFlow(StatesGroup):
    waiting_links = State()


class AdminParamsFlow(StatesGroup):
    waiting_value = State()


class AdminResultsFlow(StatesGroup):
    waiting_group_subs = State()
