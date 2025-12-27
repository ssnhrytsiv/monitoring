from aiogram.fsm.state import StatesGroup, State

class JoinChannels(StatesGroup):
    channel_input = State()
    await_action = State()
    owner_input = State()

class CreateWatch(StatesGroup):
    channel_input = State()
    template_pick = State()
    time_window = State()
    confirm = State()

class EditWatch(StatesGroup):
    time_window = State()
    source_input = State()


class BotWatch(StatesGroup):
    bot_input = State()
    expected_input = State()
    time_window = State()
    confirm = State()
