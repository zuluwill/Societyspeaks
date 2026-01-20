"""
Regression tests for template-based briefing source population.
Tests the populate_briefing_sources_from_template utility function.
"""

import pytest


class TestPopulateBriefingSourcesEdgeCases:
    """Tests for edge cases in populate_briefing_sources_from_template utility."""

    def test_empty_sources_returns_zeros(self, app_context):
        """Empty default_sources should return 0 added, 0 failed."""
        from unittest.mock import Mock
        from app.briefing.routes import populate_briefing_sources_from_template
        
        mock_briefing = Mock()
        mock_briefing.id = 1
        mock_user = Mock()
        
        added, failed, missing = populate_briefing_sources_from_template(
            mock_briefing, None, mock_user
        )
        
        assert added == 0
        assert failed == 0
        assert missing == []

    def test_empty_list_returns_zeros(self, app_context):
        """Empty list should return 0 added, 0 failed."""
        from unittest.mock import Mock
        from app.briefing.routes import populate_briefing_sources_from_template
        
        mock_briefing = Mock()
        mock_briefing.id = 1
        mock_user = Mock()
        
        added, failed, missing = populate_briefing_sources_from_template(
            mock_briefing, [], mock_user
        )
        
        assert added == 0
        assert failed == 0
        assert missing == []

    def test_non_list_returns_zeros(self, app_context):
        """Non-list default_sources should return 0 added, 0 failed."""
        from unittest.mock import Mock
        from app.briefing.routes import populate_briefing_sources_from_template
        
        mock_briefing = Mock()
        mock_briefing.id = 1
        mock_user = Mock()
        
        added, failed, missing = populate_briefing_sources_from_template(
            mock_briefing, "not a list", mock_user
        )
        
        assert added == 0
        assert failed == 0
        assert missing == []


class TestTransactionSafety:
    """Tests for transaction atomicity."""

    def test_create_input_source_uses_flush(self, app_context):
        """create_input_source_from_news_source should use flush, not commit."""
        import inspect
        from app.briefing.routes import create_input_source_from_news_source
        
        source_code = inspect.getsource(create_input_source_from_news_source)
        
        assert 'db.session.flush()' in source_code
        assert 'db.session.commit()' not in source_code


class TestUtilityFunctionExists:
    """Tests to verify utility function is properly defined."""

    def test_populate_briefing_sources_function_exists(self, app_context):
        """Utility function should be importable."""
        from app.briefing.routes import populate_briefing_sources_from_template
        
        assert callable(populate_briefing_sources_from_template)

    def test_function_returns_three_values(self, app_context):
        """Function should return tuple of (added, failed, missing)."""
        from unittest.mock import Mock
        from app.briefing.routes import populate_briefing_sources_from_template
        
        result = populate_briefing_sources_from_template(Mock(), None, Mock())
        
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_function_docstring_exists(self, app_context):
        """Function should have documentation."""
        from app.briefing.routes import populate_briefing_sources_from_template
        
        assert populate_briefing_sources_from_template.__doc__ is not None
        assert 'source' in populate_briefing_sources_from_template.__doc__.lower()


class TestSourceFormatHandling:
    """Tests for source format handling logic via code inspection."""

    def test_handles_dict_format(self, app_context):
        """Function should handle dict format sources."""
        import inspect
        from app.briefing.routes import populate_briefing_sources_from_template
        
        source_code = inspect.getsource(populate_briefing_sources_from_template)
        
        assert "isinstance(source_ref, dict)" in source_code
        assert "source_ref.get('name')" in source_code

    def test_handles_int_format(self, app_context):
        """Function should handle integer ID sources."""
        import inspect
        from app.briefing.routes import populate_briefing_sources_from_template
        
        source_code = inspect.getsource(populate_briefing_sources_from_template)
        
        assert "isinstance(source_ref, int)" in source_code

    def test_handles_string_format(self, app_context):
        """Function should handle string name sources."""
        import inspect
        from app.briefing.routes import populate_briefing_sources_from_template
        
        source_code = inspect.getsource(populate_briefing_sources_from_template)
        
        assert "isinstance(source_ref, str)" in source_code

    def test_has_case_insensitive_fallback(self, app_context):
        """Function should have case-insensitive lookup fallback."""
        import inspect
        from app.briefing.routes import populate_briefing_sources_from_template
        
        source_code = inspect.getsource(populate_briefing_sources_from_template)
        
        assert "db.func.lower" in source_code
        assert ".lower()" in source_code


class TestLoggingBehavior:
    """Tests for logging configuration."""

    def test_logs_missing_sources(self, app_context):
        """Function should log warnings for missing sources."""
        import inspect
        from app.briefing.routes import populate_briefing_sources_from_template
        
        source_code = inspect.getsource(populate_briefing_sources_from_template)
        
        assert "logger.warning" in source_code
        assert "NewsSource not found" in source_code

    def test_logs_missing_sources_summary(self, app_context):
        """Function should log summary of missing sources."""
        import inspect
        from app.briefing.routes import populate_briefing_sources_from_template
        
        source_code = inspect.getsource(populate_briefing_sources_from_template)
        
        assert "missing_sources" in source_code
        assert "sources not found in database" in source_code


class TestDuplicateProtection:
    """Tests for duplicate source protection."""

    def test_checks_existing_briefing_source(self, app_context):
        """Function should check for existing BriefingSource before adding."""
        import inspect
        from app.briefing.routes import populate_briefing_sources_from_template
        
        source_code = inspect.getsource(populate_briefing_sources_from_template)
        
        assert "BriefingSource.query.filter_by" in source_code
        assert "briefing_id=briefing.id" in source_code
        assert "source_id=source.id" in source_code


class TestAccessControl:
    """Tests for access control."""

    def test_checks_source_access(self, app_context):
        """Function should verify user can access source."""
        import inspect
        from app.briefing.routes import populate_briefing_sources_from_template
        
        source_code = inspect.getsource(populate_briefing_sources_from_template)
        
        assert "can_access_source" in source_code
