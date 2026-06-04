from flask import Blueprint

help_bp = Blueprint('help', __name__, template_folder='../templates/help')


@help_bp.context_processor
def inject_help_demo():
    from app.help.demo import help_demo_links
    return {'help_demo': help_demo_links()}


# Import routes after blueprint creation
from app.help import routes