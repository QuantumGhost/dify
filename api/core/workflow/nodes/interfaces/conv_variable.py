from typing import Protocol

from core.variables import Variable


class ConversationVariableUpdater(Protocol):
    def update_conversation_variable(self, conversation_id: str, variable: Variable):
        pass
