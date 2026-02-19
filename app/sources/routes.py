# app/sources/routes.py
"""
Routes for source profiles - discovery, viewing, and claiming.
"""
from datetime import datetime
from app.lib.time import utcnow_naive
from flask import render_template, redirect, url_for, request, flash, current_app
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from app import db
from app.sources import sources_bp
from app.models import NewsSource, CompanyProfile
from app.sources.utils import (
    get_source_discussions,
    get_source_stats,
    get_all_sources_with_stats,
    get_unique_countries,
    get_unique_categories
)


@sources_bp.route('/')
def index():
    """
    Source discovery page - browse all news sources.
    Supports filtering by category, country, political leaning, and search.
    """
    # Get filter parameters
    category = request.args.get('category', '')
    country = request.args.get('country', '')
    leaning = request.args.get('leaning', '')
    search = request.args.get('q', '')
    sort_by = request.args.get('sort', 'name')
    page = request.args.get('page', 1, type=int)

    # Get sources with stats
    sources_with_stats, pagination = get_all_sources_with_stats(
        category=category if category else None,
        country=country if country else None,
        leaning=leaning if leaning else None,
        search=search if search else None,
        sort_by=sort_by,
        page=page,
        per_page=24
    )

    # Get filter options
    countries = get_unique_countries()
    categories = get_unique_categories()

    return render_template(
        'sources/index.html',
        sources=sources_with_stats,
        pagination=pagination,
        countries=countries,
        categories=categories,
        current_category=category,
        current_country=country,
        current_leaning=leaning,
        current_search=search,
        current_sort=sort_by
    )


@sources_bp.route('/<slug>')
def view_source(slug):
    """
    Individual source profile page.
    Shows source info, engagement stats, and discussions.
    """
    source = NewsSource.query.options(
        joinedload(NewsSource.claimed_by),
        joinedload(NewsSource.claim_requested_by)
    ).filter_by(slug=slug).first_or_404()

    # Get pagination
    page = request.args.get('page', 1, type=int)

    # Get discussions from this source
    discussions = get_source_discussions(source.id, page=page, per_page=12)

    # Get engagement stats
    stats = get_source_stats(source.id)

    # Check if current user can claim this source
    can_claim = False
    has_pending_claim = source.claim_status == 'pending'

    if current_user.is_authenticated:
        # User must have a company profile and source must be unclaimed or rejected
        if current_user.company_profile and source.claim_status in ('unclaimed', 'rejected'):
            can_claim = True
        # Check if current user has the pending claim
        if has_pending_claim and source.claim_requested_by_id == current_user.id:
            has_pending_claim = True

    return render_template(
        'sources/view_source.html',
        source=source,
        discussions=discussions,
        stats=stats,
        can_claim=can_claim,
        has_pending_claim=has_pending_claim
    )


@sources_bp.route('/<slug>/claim', methods=['GET', 'POST'])
@login_required
def claim_source(slug):
    """
    Request to claim a source profile.
    Requires user to have a company profile.
    Claims require admin approval.
    """
    source = NewsSource.query.filter_by(slug=slug).first_or_404()

    # Check if user has a company profile
    if not current_user.company_profile:
        flash('You need a company profile to claim a source. Please create one first.', 'warning')
        return redirect(url_for('profiles.create_company_profile'))

    # Check if source is already claimed or has pending claim
    if source.claim_status == 'approved':
        flash('This source has already been claimed.', 'error')
        return redirect(url_for('sources.view_source', slug=slug))

    if source.claim_status == 'pending':
        if source.claim_requested_by_id == current_user.id:
            flash('You have already requested to claim this source. Please wait for admin approval.', 'info')
        else:
            flash('Another user has already requested to claim this source.', 'error')
        return redirect(url_for('sources.view_source', slug=slug))

    # Note: 'rejected' status is allowed - users can re-apply for rejected sources

    if request.method == 'POST':
        # Submit claim request
        source.claim_status = 'pending'
        source.claim_requested_at = utcnow_naive()
        source.claim_requested_by_id = current_user.id

        try:
            db.session.commit()
            current_app.logger.info(
                f'Source claim requested: {source.name} by user {current_user.id}'
            )
            flash(
                'Your claim request has been submitted. An admin will review it shortly.',
                'success'
            )
            return redirect(url_for('sources.view_source', slug=slug))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Error submitting claim request: {str(e)}')
            flash('An error occurred. Please try again.', 'error')

    return render_template(
        'sources/claim.html',
        source=source,
        company_profile=current_user.company_profile
    )
