from aiogram.fsm.state import StatesGroup, State

class JoinChannels(StatesGroup):
    channel_input = State()
    await_action = State()
    owner_input = State()

class CreateWatch(StatesGroup):
    admin_pick = State()
    network_pick = State()
    channel_input = State()
    template_pick = State()
    time_window = State()
    confirm = State()
    project_pick = State()

class EditWatch(StatesGroup):
    time_window = State()
    source_input = State()
