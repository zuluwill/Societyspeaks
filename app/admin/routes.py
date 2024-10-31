# In admin/routes.py

@admin_bp.route('/discussions/featured', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_featured_discussions():
    if request.method == 'POST':
        discussion_id = request.form.get('discussion_id')
        action = request.form.get('action')

        if action == 'feature':
            Discussion.feature_discussion(discussion_id, True)
        elif action == 'unfeature':
            Discussion.feature_discussion(discussion_id, False)
        elif action == 'auto':
            Discussion.auto_feature_discussions()

        flash('Featured discussions updated successfully')
        return redirect(url_for('admin.manage_featured_discussions'))

    featured = Discussion.get_featured()
    recent = Discussion.query.order_by(Discussion.created_at.desc()).limit(20).all()

    return render_template(
        'admin/featured_discussions.html',
        featured=featured,
        recent=recent
    )