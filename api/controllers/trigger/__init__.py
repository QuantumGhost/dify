from flask import Blueprint

# Create trigger blueprint
bp = Blueprint("trigger", __name__, url_prefix="/triggers")

# Import routes after blueprint creation to avoid circular imports
from . import human_input_im, trigger, webhook

__all__ = [
    "human_input_im",
    "trigger",
    "webhook",
]
