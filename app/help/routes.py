# app/help/routes.py
from flask import Blueprint, render_template, url_for
from app.help import help_bp

@help_bp.route('/')
def help():
    categories = {
        'getting-started': {
            'title': 'Getting Started',
            'description': 'Learn the basics of Society Speaks',
            'icon': 'book-open',
            'url': url_for('help.getting_started')
        },
        'creating-discussions': {
            'title': 'Creating Discussions',
            'description': 'Learn how to create and manage discussions',
            'icon': 'message-circle',
            'url': url_for('help.creating_discussions')
        },
        'native-system': {
            'title': 'Native Debate System',
            'description': 'Learn about our advanced native debate features',
            'icon': 'chart',
            'url': url_for('help.native_system')
        },
        'managing-discussions': {
            'title': 'Managing Discussions',
            'description': 'Monitor and engage with your discussions',
            'icon': 'sparkles',
            'url': url_for('help.managing_discussions')
        }
    }

    return render_template('help/help.html', categories=categories)

@help_bp.route('/getting-started')
def getting_started():
    return render_template('help/getting_started.html')

@help_bp.route('/creating-discussions')
def creating_discussions():
    return render_template('help/creating_discussions.html')

@help_bp.route('/managing-discussions')
def managing_discussions():
    return render_template('help/managing_discussions.html')

@help_bp.route('/seed-comments')
def seed_comments():
    return render_template('help/seed_comments.html')

@help_bp.route('/polis-algorithms')
def polis_algorithms():
    return render_template('help/polis_algorithms.html')

@help_bp.route('/native-system')
def native_system():
    return render_template('help/native_system.html')