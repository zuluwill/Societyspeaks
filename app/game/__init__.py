from flask import Blueprint

game_bp = Blueprint('game', __name__, url_prefix='/play')

from app.game import routes  # noqa: E402, F401
from app.game import api  # noqa: E402, F401
